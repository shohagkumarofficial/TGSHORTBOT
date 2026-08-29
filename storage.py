"""In-memory + Supabase(Postgres)-backed storage for TGSHORTBOT.

This is a drop-in replacement for the original JSON-file-backed storage
module: every public method keeps the exact same name and signature, so
bot.py / app.py / cpm_engine.py needed no changes at all — including the
places that reach directly into `storage.admins`, `storage.links`,
`storage.views`, `storage.cpm_setting`, `storage.cpm_history`, and
`storage._lock` (cpm_engine.py's crediting logic mutates those objects
in place and then calls `storage._save_locked()`).

Everything still lives in memory for fast reads. The one thing that
changed is *where* `_save_locked()` flushes to: instead of rewriting a
single `data/store.json` file, it upserts the full current in-memory
state to Supabase, one batched call per table. This keeps the same
write-through philosophy the JSON version used (every mutation is
persisted immediately, so a Render restart never loses data) while
moving the actual storage off Render's ephemeral disk and onto
Supabase's persistent Postgres database.

An `asyncio.Lock` still serializes all mutations for the same reason as
before: the whole app runs on a single asyncio event loop, so this alone
is enough to make check-then-act sequences (e.g. the Anti-Abuse System's
daily-cap check in cpm_engine._is_daily_capped) atomic — no real
concurrency bugs, no need for a DB transaction.

NOTE: the `views` table's old UNIQUE(short_code, viewer_telegram_id)
constraint must be DROPPED in Supabase. Repeat visits by the same viewer
to the same link now each create their own View row and count toward
that link's owner's balance (see create_view's docstring) — the only
thing still limiting a viewer's repeat views is the Anti-Abuse System's
daily cap, not a one-view-per-link ceiling. With the old constraint
still in place, every repeat-view insert fails outright.

NOTE (known trade-off, fine for the current MVP scale): `_save_locked()`
re-upserts every admin/link/view/withdrawal on every single mutation,
mirroring how the old JSON version rewrote the whole file on every
mutation. This is simple and correct, but it's O(total rows) per write.
If/when views get into the tens of thousands, this is the first place
to optimize — swap the blanket upsert for a targeted single-row
upsert/update per call site.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from supabase import AsyncClient, create_async_client

from models import (
    Admin,
    AdminRequestStatus,
    AdminStatus,
    AdNetwork,
    AdNetworkSetting,
    ApiKey,
    CountedStatus,
    CPMHistoryEntry,
    CPMSetting,
    Link,
    PolicySetting,
    Role,
    TrafficSource,
    View,
    WithdrawMethod,
    WithdrawRequest,
    WithdrawStatus,
    effective_cpm,
    now_iso,
)

logger = logging.getLogger("tgshortbot.storage")

# Matches PostgREST's "column not found" error (code PGRST204), e.g.:
# "Could not find the 'expires_at' column of 'links' in the schema cache"
# — i.e. a model field exists on the Python side but the corresponding
# `alter table` migration from README.md hasn't been run against this
# Supabase project yet.
_MISSING_COLUMN_RE = re.compile(r"Could not find the '([a-zA-Z_][a-zA-Z0-9_]*)' column")

# Sentinel default for update_cpm_setting's admin_cpm/sub_admin_cpm kwargs,
# so the caller can tell "leave this alone" (omit the kwarg) apart from
# "clear it back to the platform base rate" (pass cpm=None explicitly) —
# the same distinction set_sub_admin_cpm already makes for a single Admin.
_UNSET = object()


class Storage:
    def __init__(self, supabase_url: str, supabase_key: str):
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.client: Optional[AsyncClient] = None
        self._lock = asyncio.Lock()

        self.admins: Dict[int, Admin] = {}
        self.links: Dict[str, Link] = {}
        self.views: Dict[str, View] = {}
        self.withdrawals: Dict[str, WithdrawRequest] = {}
        self.cpm_setting: CPMSetting = CPMSetting()
        self.policy_setting: PolicySetting = PolicySetting()
        self.ad_network_setting: AdNetworkSetting = AdNetworkSetting()
        self.cpm_history: List[CPMHistoryEntry] = []
        self.api_keys: Dict[str, ApiKey] = {}

        # raw-key SHA-256 hash -> key_id, so require_api_key can resolve a
        # request's Authorization header without scanning every ApiKey on
        # every single API call.
        self._api_key_hash_index: Dict[str, str] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Load / persist
    # ------------------------------------------------------------------

    async def load(self) -> None:
        """Connects to Supabase and pulls every table into memory. Call
        once at startup (same as the JSON version's `load()`)."""
        self.client = await create_async_client(self.supabase_url, self.supabase_key)

        admins_res = await self.client.table("admins").select("*").execute()
        traffic_res = await self.client.table("traffic_sources").select("*").execute()
        links_res = await self.client.table("links").select("*").execute()
        views_res = await self.client.table("views").select("*").execute()
        withdrawals_res = await self.client.table("withdrawals").select("*").execute()
        cpm_setting_res = await self.client.table("cpm_settings").select("*").eq("id", 1).execute()
        policy_setting_res = await self.client.table("policy_settings").select("*").eq("id", 1).execute()
        ad_network_setting_res = await self.client.table("ad_network_settings").select("*").eq("id", 1).execute()
        cpm_history_res = await self.client.table("cpm_history").select("*").execute()
        api_keys_res = await self._select_or_empty("api_keys")

        traffic_by_admin: Dict[int, List[TrafficSource]] = {}
        for row in traffic_res.data:
            row = dict(row)
            admin_id = row.pop("admin_telegram_id")
            traffic_by_admin.setdefault(admin_id, []).append(TrafficSource(**row))

        self.admins = {}
        for row in admins_res.data:
            row = dict(row)
            row["traffic_sources"] = traffic_by_admin.get(row["telegram_id"], [])
            self.admins[row["telegram_id"]] = Admin(**row)

        self.links = {row["short_code"]: Link(**row) for row in links_res.data}
        self.views = {row["view_id"]: View(**row) for row in views_res.data}
        self.withdrawals = {row["request_id"]: WithdrawRequest(**row) for row in withdrawals_res.data}

        if cpm_setting_res.data:
            cs_row = dict(cpm_setting_res.data[0])
            cs_row.pop("id", None)
            self.cpm_setting = CPMSetting(**cs_row)
        else:
            # Shouldn't happen (the schema script seeds this row), but
            # self-heal instead of crash-looping if it's ever missing.
            self.cpm_setting = CPMSetting()

        if policy_setting_res.data:
            ps_row = dict(policy_setting_res.data[0])
            ps_row.pop("id", None)
            self.policy_setting = PolicySetting(**ps_row)
        else:
            self.policy_setting = PolicySetting()

        if ad_network_setting_res.data:
            ans_row = dict(ad_network_setting_res.data[0])
            ans_row.pop("id", None)
            self.ad_network_setting = AdNetworkSetting(**ans_row)
        else:
            # Shouldn't happen once the `ad_network_settings` table is
            # created (see README), but self-heal instead of
            # crash-looping if it's ever missing — the platform falls
            # back to the three-Adsgram-slots default until the Owner
            # saves something from the panel's Ad Networks tab.
            self.ad_network_setting = AdNetworkSetting()

        self.cpm_history = [CPMHistoryEntry(**row) for row in cpm_history_res.data]
        self.api_keys = {row["key_id"]: ApiKey(**row) for row in api_keys_res.data}

        self._api_key_hash_index = {k.key_hash: k.key_id for k in self.api_keys.values()}

        async with self._lock:
            await self._save_locked()
        self._loaded = True

    async def _select_or_empty(self, table: str):
        """Like `self.client.table(table).select("*").execute()`, but
        self-heals to an empty result instead of crash-looping the whole
        `load()` if `table` doesn't exist yet — i.e. the `create table`
        migration for a newer feature (e.g. `api_keys`, see README.md)
        hasn't been run against this Supabase project yet. Mirrors the
        same self-heal philosophy `_safe_upsert` already applies to a
        single missing *column*, just one level up, for a missing table.
        """
        try:
            return await self.client.table(table).select("*").execute()
        except Exception as exc:
            if "PGRST205" in str(exc) or "Could not find the table" in str(exc):
                logger.warning(
                    "Supabase table '%s' doesn't exist yet (pending migration — "
                    "see README.md's schema notes). Starting empty until it's created.",
                    table,
                )

                class _Empty:
                    data = []

                return _Empty()
            raise

    async def _safe_upsert(
        self, table: str, rows: list[dict], on_conflict: str, tolerate_missing_table: bool = False
    ) -> None:
        """Upserts `rows` into `table`, tolerating a field that exists on
        the Python model but not yet as a real column in Supabase — i.e.
        a pending `alter table` migration from README.md. Without this,
        every write to a table with one missing column 500s on *every*
        request that touches it (e.g. shortening a link, right after
        adding `Link.expires_at`, if `links.expires_at` hasn't been
        migrated in yet) until someone notices and runs the SQL. Instead:
        strip whichever column PostgREST reports as missing and retry,
        logging a warning each time so the pending migration is still
        very visible in the logs — the request itself just succeeds
        without persisting that one field until the migration is run.

        `tolerate_missing_table=True` additionally self-heals a *whole
        table* not existing yet (mirrors `_select_or_empty`'s tolerance
        at load time) — used only for genuinely optional, newer-feature
        tables like `api_keys` (see README.md's schema notes). Those
        rows are simply not persisted for now; the in-memory state this
        call was writing from (e.g. `self.api_keys`) already has them,
        so the feature still works for the life of this process, it
        just won't survive a restart until the migration is run. Left
        False (the default) for every other table — those are core data
        (balances, links, views...) where silently swallowing a failed
        write would risk masking real data loss, so a missing core table
        should keep raising loudly instead.
        """
        if not rows:
            return
        remaining = rows
        for _ in range(10):  # generous cap: covers a whole migration being missed, not just one column
            try:
                await self.client.table(table).upsert(remaining, on_conflict=on_conflict).execute()
                return
            except Exception as exc:
                if tolerate_missing_table and ("PGRST205" in str(exc) or "Could not find the table" in str(exc)):
                    logger.warning(
                        "Supabase table '%s' doesn't exist yet (pending migration — see "
                        "README.md's schema notes). This write's rows are kept in memory "
                        "for now but won't be persisted until the table is created.",
                        table,
                    )
                    return
                match = _MISSING_COLUMN_RE.search(str(exc))
                if not match:
                    raise
                column = match.group(1)
                logger.warning(
                    "Supabase table '%s' has no '%s' column yet (pending migration — "
                    "see README.md's schema notes). Dropping it from this write so the "
                    "request still succeeds; run the migration to actually persist it.",
                    table, column,
                )
                remaining = [{k: v for k, v in row.items() if k != column} for row in remaining]
        # Retries exhausted (10 distinct missing columns in one write is basically
        # "wrong table entirely") — let the real error surface instead of looping forever.
        await self.client.table(table).upsert(remaining, on_conflict=on_conflict).execute()

    async def _save_locked(self) -> None:
        """Caller must already hold self._lock. Pushes the full current
        in-memory state to Supabase. Batched: one upsert call per table,
        regardless of how many rows changed.
        """
        admin_rows = [a.model_dump(mode="json", exclude={"traffic_sources"}) for a in self.admins.values()]
        traffic_rows = [
            {**s.model_dump(mode="json"), "admin_telegram_id": a.telegram_id}
            for a in self.admins.values()
            for s in a.traffic_sources
        ]
        link_rows = [l.model_dump(mode="json") for l in self.links.values()]
        view_rows = [v.model_dump(mode="json") for v in self.views.values()]
        withdrawal_rows = [w.model_dump(mode="json") for w in self.withdrawals.values()]
        cpm_setting_row = {"id": 1, **self.cpm_setting.model_dump(mode="json")}
        policy_setting_row = {"id": 1, **self.policy_setting.model_dump(mode="json")}
        ad_network_setting_row = {"id": 1, **self.ad_network_setting.model_dump(mode="json")}
        cpm_history_rows = [e.model_dump(mode="json") for e in self.cpm_history]
        api_key_rows = [k.model_dump(mode="json") for k in self.api_keys.values()]

        await self._safe_upsert("admins", admin_rows, on_conflict="telegram_id")
        await self._safe_upsert("traffic_sources", traffic_rows, on_conflict="id")
        await self._safe_upsert("links", link_rows, on_conflict="short_code")
        await self._safe_upsert("views", view_rows, on_conflict="view_id")
        await self._safe_upsert("withdrawals", withdrawal_rows, on_conflict="request_id")
        await self._safe_upsert("cpm_settings", [cpm_setting_row], on_conflict="id")
        await self._safe_upsert("policy_settings", [policy_setting_row], on_conflict="id")
        await self._safe_upsert("ad_network_settings", [ad_network_setting_row], on_conflict="id")
        await self._safe_upsert("cpm_history", cpm_history_rows, on_conflict="entry_id")
        await self._safe_upsert("api_keys", api_key_rows, on_conflict="key_id", tolerate_missing_table=True)

    async def save(self) -> None:
        async with self._lock:
            await self._save_locked()

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------

    async def get_admin(self, telegram_id: int) -> Optional[Admin]:
        return self.admins.get(telegram_id)

    async def get_or_create_admin(
        self, telegram_id: int, username: Optional[str], owner_id: int
    ) -> Admin:
        """Auto-creates a record on first /start (Section 2).

        Owner > Admin > Sub Admin > Viewer: anyone who isn't the
        configured Owner starts out as a plain Viewer — the lowest tier,
        with no earning power — and only becomes a Sub Admin the moment
        they add their first Traffic Source (see add_traffic_source
        below). There's no more "everyone who isn't the Owner is
        automatically an Admin" shortcut.
        """
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if admin:
                if username and admin.username != username:
                    admin.username = username
                    await self._save_locked()
                return admin
            role = Role.OWNER if telegram_id == owner_id else Role.VIEWER
            admin = Admin(telegram_id=telegram_id, username=username, role=role)
            self.admins[telegram_id] = admin
            await self._save_locked()
            return admin

    async def list_admins(self) -> List[Admin]:
        return list(self.admins.values())

    async def set_admin_status(self, telegram_id: int, status: AdminStatus) -> Optional[Admin]:
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin:
                return None
            admin.status = status
            await self._save_locked()
            return admin

    async def set_admin_balance(
        self, telegram_id: int, new_balance: float, reason: Optional[str], changed_by: int
    ) -> Optional[Admin]:
        """Owner-only manual correction of an Admin's confirmed balance —
        e.g. to fix a mistake or claw back a fraudulent payout. Always
        logged to cpm_history (old value, new value, reason, who did it)
        so this is never a silent, untraceable edit even though the
        affected Admin isn't notified.
        """
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin:
                return None
            old_balance = admin.balance_confirmed
            admin.balance_confirmed = round(new_balance, 6)
            self.cpm_history.append(
                CPMHistoryEntry(
                    event="balance_adjustment",
                    detail={
                        "telegram_id": telegram_id,
                        "old_balance": old_balance,
                        "new_balance": admin.balance_confirmed,
                        "reason": reason,
                        "by": changed_by,
                    },
                )
            )
            await self._save_locked()
            return admin

    async def set_role(self, telegram_id: int, role: Role, changed_by: int) -> Optional[Admin]:
        """Owner-only direct role change (promote or demote), for the
        Owner's general "Admins" management screen — separate from the
        guided Sub-Admin-requests-Admin flow in submit_admin_request /
        resolve_admin_request below. Never used to assign Role.OWNER
        (that's fixed at boot time from OWNER_TELEGRAM_ID).
        """
        if role == Role.OWNER:
            return None
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin or admin.role == Role.OWNER:
                return None
            old_role = admin.role
            if old_role == role:
                return admin
            admin.role = role
            # Demoting out of Sub Admin clears anything that only makes
            # sense for that tier, so a later re-promotion starts clean
            # instead of silently inheriting a stale CPM override or
            # auto-delete window.
            if role != Role.SUB_ADMIN:
                admin.sub_admin_cpm = None
                admin.link_auto_delete_months = None
            self.cpm_history.append(
                CPMHistoryEntry(
                    event="role_change",
                    detail={
                        "telegram_id": telegram_id,
                        "from": old_role.value,
                        "to": role.value,
                        "by": changed_by,
                    },
                )
            )
            await self._save_locked()
            return admin

    async def add_traffic_source(self, telegram_id: int, platform: str, url: str) -> Optional[TrafficSource]:
        """Appends one more "where do your viewers come from" entry for
        this Admin. An Admin can hold several at once (one per platform,
        or several on the same platform) and needs at least one before
        creating any short links.

        Also the Viewer -> Sub Admin promotion trigger: a brand new user
        starts as a plain Viewer (see get_or_create_admin) with no
        earning power; the moment they add their first Traffic Source
        they're auto-promoted to Sub Admin. This never fires again for
        someone already at Sub Admin or above — adding a 2nd/3rd source
        doesn't do anything to role.
        """
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin:
                return None
            source = TrafficSource(platform=platform, url=url)
            admin.traffic_sources.append(source)
            if admin.role == Role.VIEWER:
                admin.role = Role.SUB_ADMIN
                # Pre-fill this new Sub Admin's link auto-delete window
                # from the Owner's platform-wide default, if one is set,
                # so it doesn't sit on "never" until someone remembers to
                # open their profile — see CPMSetting.
                # default_sub_admin_auto_delete_months's docstring.
                if self.cpm_setting.default_sub_admin_auto_delete_months:
                    admin.link_auto_delete_months = self.cpm_setting.default_sub_admin_auto_delete_months
                self.cpm_history.append(
                    CPMHistoryEntry(
                        event="role_change",
                        detail={
                            "telegram_id": telegram_id,
                            "from": Role.VIEWER.value,
                            "to": Role.SUB_ADMIN.value,
                            "reason": "added first traffic source",
                        },
                    )
                )
            await self._save_locked()
            return source

    async def update_traffic_source(
        self, telegram_id: int, source_id: str, platform: Optional[str] = None, url: Optional[str] = None
    ) -> Optional[TrafficSource]:
        """Edits an existing entry in place (by id) rather than replacing
        the whole list, so an Admin can update one source's link without
        disturbing the others.
        """
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin:
                return None
            for source in admin.traffic_sources:
                if source.id == source_id:
                    if platform is not None:
                        source.platform = platform
                    if url is not None:
                        source.url = url
                    source.updated_at = now_iso()
                    await self._save_locked()
                    return source
            return None

    async def delete_traffic_source(self, telegram_id: int, source_id: str) -> bool:
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin:
                return False
            before = len(admin.traffic_sources)
            admin.traffic_sources = [s for s in admin.traffic_sources if s.id != source_id]
            changed = len(admin.traffic_sources) != before
            if changed:
                # A blanket upsert alone would never remove this row from
                # Supabase (upsert only adds/updates), so it needs an
                # explicit delete before the usual full-state save.
                await self.client.table("traffic_sources").delete().eq("id", source_id).execute()
                await self._save_locked()
            return changed

    # ------------------------------------------------------------------
    # Link
    # ------------------------------------------------------------------

    DEFAULT_AD_COUNT = 3
    MIN_AD_COUNT = 1
    MAX_AD_COUNT = 10

    # Sub Admin link auto-delete feature: the only durations the Owner
    # can pick from `webapp/panel.html`'s per-Sub-Admin setting (0 means
    # "never", i.e. Admin.link_auto_delete_months = None).
    SUB_ADMIN_AUTO_DELETE_CHOICES = (1, 3, 6, 12)

    async def create_link(
        self,
        short_code: str,
        owner_telegram_id: int,
        destination_url: str,
        ad_count: Optional[int] = None,
    ) -> Link:
        """`expires_at` is derived here, at creation time, from the
        creating Admin's *current* `link_auto_delete_months` — never
        recomputed later, so changing (or clearing) that setting
        afterward only ever affects links created from then on, exactly
        like a CPM-rate change never re-prices views that already
        happened.
        """
        async with self._lock:
            owner = self.admins.get(owner_telegram_id)
            expires_at = None
            if owner and owner.link_auto_delete_months:
                expires_at = (
                    datetime.now(timezone.utc) + timedelta(days=30 * owner.link_auto_delete_months)
                ).isoformat()
            link = Link(
                short_code=short_code,
                owner_telegram_id=owner_telegram_id,
                destination_url=destination_url,
                ad_count=ad_count if ad_count is not None else self.DEFAULT_AD_COUNT,
                expires_at=expires_at,
            )
            self.links[short_code] = link
            await self._save_locked()
            return link

    async def purge_expired_links(self) -> int:
        """Removes every Link whose `expires_at` has passed from memory
        (Sub Admin auto-delete feature) — so it stops resolving, stops
        showing up in `list_links_by_owner`/the panel, and stops counting
        toward anyone's link total. Intended to be called periodically
        from a background loop (see app.py's lifespan, alongside the CPM
        cycle watcher) — not from any request path.

        Deliberately does NOT delete the Supabase `links` row (this used
        to also run a matching `.delete()` against Supabase; that was
        removed after it caused a production incident — see below). That
        link's View rows are left alone either way, same reasoning as
        delete_link: they've already been credited, so removing them
        would only make old earnings harder to audit without changing
        anyone's balance. But `views.short_code` has a foreign-key
        constraint on `links.short_code`, so hard-deleting the Link row
        while its Views survive left those Views permanently orphaned —
        and since `_save_locked()` re-upserts the *entire* views table on
        every single mutation (see its docstring), one orphaned row was
        then enough to make every future write to *any* table fail with a
        `views_short_code_fkey` violation, not just writes touching that
        link. Leaving the Supabase `links` row in place keeps the foreign
        key satisfied forever, at the cost of an inert row lingering in
        Postgres for an expired link — a fine trade, since nothing in the
        app ever reads `links` from Supabase again after `load()` rebuilds
        `self.links` at startup, and `load()`'s own call to this method
        (via app.py's periodic watcher) purges it from memory again before
        it could ever look like an active link.
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            expired_codes = []
            for code, link in self.links.items():
                if not link.expires_at:
                    continue
                try:
                    expires = datetime.fromisoformat(link.expires_at)
                except ValueError:
                    continue
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires <= now:
                    expired_codes.append(code)
            for code in expired_codes:
                del self.links[code]
            return len(expired_codes)

    async def get_link(self, short_code: str) -> Optional[Link]:
        return self.links.get(short_code)

    async def list_links_by_owner(self, owner_telegram_id: int) -> List[Link]:
        return [l for l in self.links.values() if l.owner_telegram_id == owner_telegram_id]

    async def delete_link(self, short_code: str, requester_telegram_id: int, is_owner: bool) -> bool:
        """Removes a Link so it 404s for any future viewer and drops off
        the owning Admin's "My Links" list. An Admin may only delete
        their own links; the Owner (is_owner=True) may delete anyone's.

        Deliberately leaves that link's View rows alone — they've
        already fed into the owning Admin's stored balance_confirmed /
        balance_pending (see Admin's docstring), so deleting them here
        wouldn't change anyone's balance, it'd just make old earnings
        harder to audit later. For that reason this only removes the
        Link from memory and does NOT delete the Supabase `links` row
        (used to also run a matching `.delete()` there; removed after it
        caused a production incident — same one purge_expired_links hit
        and explains in more detail): `views.short_code` has a foreign
        key on `links.short_code`, so hard-deleting a Link while its
        Views survive leaves those Views permanently orphaned, and
        `_save_locked()`'s blanket views upsert then fails on every
        future write anywhere in the app, not just ones touching this
        link. Leaving the inert Supabase row behind costs nothing —
        nothing reads `links` from Supabase again after `load()` builds
        `self.links` at startup.
        """
        async with self._lock:
            link = self.links.get(short_code)
            if not link:
                return False
            if not is_owner and link.owner_telegram_id != requester_telegram_id:
                return False
            del self.links[short_code]
            return True

    async def set_link_ad_count(self, short_code: str, ad_count: int) -> Optional[Link]:
        """Owner-only: how many sequential ads this one link requires
        before it unlocks. Nothing about an Admin's own access changes —
        `GET /api/links` shows the Admin the current count read-only, but
        only the Owner-only endpoint that calls this can change it.
        """
        async with self._lock:
            link = self.links.get(short_code)
            if not link:
                return None
            link.ad_count = ad_count
            await self._save_locked()
            return link

    async def admin_links_detail(self, owner_telegram_id: int) -> List[dict]:
        """Per-link detail for the Owner's per-Admin detail view: every
        link this Admin owns, each with its own `ad_count` and a genuine
        (capped-excluded — same rule as everywhere else `view_count`
        appears) view count, so the Owner can review and adjust any one
        link's ad count without having to cross-reference the Admin's
        own "My Links" list.
        """
        links = await self.list_links_by_owner(owner_telegram_id)
        out = []
        for l in links:
            views = await self.list_views_by_short_code(l.short_code)
            genuine_views = [v for v in views if not v.daily_capped]
            out.append(
                {
                    "short_code": l.short_code,
                    "destination_url": l.destination_url,
                    "ad_count": l.ad_count,
                    "created_at": l.created_at,
                    "view_count": len(genuine_views),
                    "daily_capped_views": len(views) - len(genuine_views),
                }
            )
        out.sort(key=lambda r: r["created_at"], reverse=True)
        return out

    # ------------------------------------------------------------------
    # View
    # ------------------------------------------------------------------

    async def create_view(self, short_code: str, viewer_telegram_id: int) -> View:
        """Every completed ad-watch creates its own View row now — a
        viewer revisiting the same link repeatedly all counts toward
        that link owner's balance, there's no more one-view-per-viewer-
        per-link ceiling (the old dedupe rule). The only thing still
        limiting repeat views is the Anti-Abuse System's daily cap
        (CPMSetting.max_daily_views_per_admin, enforced by
        cpm_engine.credit_new_view/_is_daily_capped across *all* of an
        Admin's links combined, same-link repeats included): once a
        viewer crosses it for one Admin in a day, every further view —
        on this link or any other of that Admin's links — is still
        logged as watched but earns nothing (`daily_capped=True`),
        rather than being silently dropped.

        REQUIRES the `views` table's old UNIQUE(short_code,
        viewer_telegram_id) constraint to be dropped in Supabase (see
        README.md's Security notes) — with it still in place, the
        insert below fails on every repeat view, and that failure is
        logged and re-raised rather than swallowed, so a still-pending
        migration is obvious instead of quietly losing views again.
        """
        async with self._lock:
            view = View(short_code=short_code, viewer_telegram_id=viewer_telegram_id)
            try:
                await self.client.table("views").insert(view.model_dump(mode="json")).execute()
            except Exception as exc:
                if "duplicate" in str(exc).lower() or "23505" in str(exc):
                    logger.error(
                        "views insert for (%s, %s) hit a duplicate-key error — the old "
                        "UNIQUE(short_code, viewer_telegram_id) constraint is probably "
                        "still on the Supabase 'views' table; drop it so repeat views by "
                        "the same viewer can be counted (see README.md's Security notes).",
                        short_code, viewer_telegram_id,
                    )
                raise
            self.views[view.view_id] = view
            await self._save_locked()
            return view

    async def list_views_by_short_code(self, short_code: str) -> List[View]:
        return [v for v in self.views.values() if v.short_code == short_code]

    async def list_views_by_owner(self, owner_telegram_id: int) -> List[View]:
        owned_codes = {l.short_code for l in self.links.values() if l.owner_telegram_id == owner_telegram_id}
        if not owned_codes:
            return []
        return [v for v in self.views.values() if v.short_code in owned_codes]

    # ------------------------------------------------------------------
    # Withdrawals
    # ------------------------------------------------------------------

    async def create_withdrawal(
        self,
        admin_telegram_id: int,
        amount: float,
        method: WithdrawMethod,
        account_number: str,
    ) -> WithdrawRequest:
        async with self._lock:
            req = WithdrawRequest(
                admin_telegram_id=admin_telegram_id,
                amount=amount,
                method=method,
                account_number=account_number,
            )
            self.withdrawals[req.request_id] = req
            await self._save_locked()
            return req

    async def list_withdrawals(self, status: Optional[WithdrawStatus] = None) -> List[WithdrawRequest]:
        vals = list(self.withdrawals.values())
        if status:
            vals = [w for w in vals if w.status == status]
        return vals

    async def get_withdrawal(self, request_id: str) -> Optional[WithdrawRequest]:
        return self.withdrawals.get(request_id)

    async def resolve_withdrawal(
        self, request_id: str, decision: WithdrawStatus, reason: Optional[str] = None
    ) -> Optional[WithdrawRequest]:
        """Balance is deducted only when marked Paid (Section 4.6 step 4)."""
        async with self._lock:
            req = self.withdrawals.get(request_id)
            if not req or req.status != WithdrawStatus.PENDING:
                return None
            req.status = decision
            req.resolved_at = now_iso()
            if reason:
                req.reject_reason = reason
            if decision == WithdrawStatus.PAID:
                admin = self.admins.get(req.admin_telegram_id)
                if admin:
                    admin.balance_confirmed = round(max(0.0, admin.balance_confirmed - req.amount), 6)
            await self._save_locked()
            return req

    # ------------------------------------------------------------------
    # CPM
    # ------------------------------------------------------------------

    async def get_cpm_setting(self) -> CPMSetting:
        return self.cpm_setting

    async def update_cpm_setting(
        self,
        *,
        mode=None,
        current_cpm: Optional[float] = None,
        cycle_duration_hours: Optional[float] = None,
        ad_view_delay_seconds: Optional[float] = None,
        min_withdraw_amount: Optional[float] = None,
        max_daily_views_per_admin: Optional[int] = None,
        admin_cpm=_UNSET,
        sub_admin_cpm=_UNSET,
        default_sub_admin_auto_delete_months=_UNSET,
        updated_by: Optional[int] = None,
    ) -> CPMSetting:
        async with self._lock:
            cs = self.cpm_setting
            detail: dict = {}
            reset_cycle = False

            if mode is not None and mode != cs.mode:
                detail["mode"] = {"from": cs.mode.value, "to": mode.value}
                cs.mode = mode
                reset_cycle = True
            if current_cpm is not None and current_cpm != cs.current_cpm:
                detail["current_cpm"] = {"from": cs.current_cpm, "to": current_cpm}
                cs.current_cpm = current_cpm
            if cycle_duration_hours is not None and cycle_duration_hours != cs.cycle_duration_hours:
                detail["cycle_duration_hours"] = {
                    "from": cs.cycle_duration_hours,
                    "to": cycle_duration_hours,
                }
                cs.cycle_duration_hours = cycle_duration_hours
                reset_cycle = True
            if ad_view_delay_seconds is not None and ad_view_delay_seconds != cs.ad_view_delay_seconds:
                detail["ad_view_delay_seconds"] = {
                    "from": cs.ad_view_delay_seconds,
                    "to": ad_view_delay_seconds,
                }
                cs.ad_view_delay_seconds = ad_view_delay_seconds
            if min_withdraw_amount is not None and min_withdraw_amount != cs.min_withdraw_amount:
                detail["min_withdraw_amount"] = {
                    "from": cs.min_withdraw_amount,
                    "to": min_withdraw_amount,
                }
                cs.min_withdraw_amount = min_withdraw_amount
            if (
                max_daily_views_per_admin is not None
                and max_daily_views_per_admin != cs.max_daily_views_per_admin
            ):
                detail["max_daily_views_per_admin"] = {
                    "from": cs.max_daily_views_per_admin,
                    "to": max_daily_views_per_admin,
                }
                cs.max_daily_views_per_admin = max_daily_views_per_admin
            # admin_cpm/sub_admin_cpm use the _UNSET sentinel (not None)
            # as their "don't touch" default, since None is itself a
            # meaningful value here — it means "clear the role override,
            # fall back to current_cpm" (see effective_cpm).
            if admin_cpm is not _UNSET and admin_cpm != cs.admin_cpm:
                detail["admin_cpm"] = {"from": cs.admin_cpm, "to": admin_cpm}
                cs.admin_cpm = admin_cpm
            if sub_admin_cpm is not _UNSET and sub_admin_cpm != cs.sub_admin_cpm:
                detail["sub_admin_cpm"] = {"from": cs.sub_admin_cpm, "to": sub_admin_cpm}
                cs.sub_admin_cpm = sub_admin_cpm
            if (
                default_sub_admin_auto_delete_months is not _UNSET
                and default_sub_admin_auto_delete_months != cs.default_sub_admin_auto_delete_months
            ):
                detail["default_sub_admin_auto_delete_months"] = {
                    "from": cs.default_sub_admin_auto_delete_months,
                    "to": default_sub_admin_auto_delete_months,
                }
                cs.default_sub_admin_auto_delete_months = default_sub_admin_auto_delete_months

            if reset_cycle:
                cs.cycle_started_at = now_iso()
                cs.cycle_id = str(uuid.uuid4())

            cs.updated_at = now_iso()
            cs.updated_by = updated_by

            if detail:
                detail["by"] = updated_by
                self.cpm_history.append(CPMHistoryEntry(event="cpm_change", detail=detail))

            await self._save_locked()
            return cs

    async def set_withdrawals_paused(
        self, paused: bool, message: Optional[str], changed_by: int
    ) -> CPMSetting:
        """Owner-only kill switch for new withdrawal requests — see
        `CPMSetting.withdrawals_paused`'s docstring for the exact
        semantics (only blocks new requests; anything already PENDING
        is untouched and still resolvable normally).
        """
        async with self._lock:
            cs = self.cpm_setting
            if cs.withdrawals_paused == paused and cs.withdrawals_paused_message == message:
                return cs
            self.cpm_history.append(
                CPMHistoryEntry(
                    event="withdrawals_paused_change",
                    detail={"from": cs.withdrawals_paused, "to": paused, "message": message, "by": changed_by},
                )
            )
            cs.withdrawals_paused = paused
            cs.withdrawals_paused_message = message
            cs.updated_at = now_iso()
            cs.updated_by = changed_by
            await self._save_locked()
            return cs

    async def append_history(self, event: str, detail: dict) -> None:
        async with self._lock:
            self.cpm_history.append(CPMHistoryEntry(event=event, detail=detail))
            await self._save_locked()

    # ------------------------------------------------------------------
    # Sub Admin tier: per-Sub-Admin CPM override + link auto-delete
    # ------------------------------------------------------------------

    async def set_sub_admin_cpm(
        self, telegram_id: int, cpm: Optional[float], changed_by: int
    ) -> Optional[Admin]:
        """Owner-only per-Sub-Admin CPM override. `cpm=None` clears the
        override, falling back to the platform-wide CPMSetting.
        current_cpm — see cpm_engine.credit_new_view for how the two are
        reconciled. Meaningful only for a Role.SUB_ADMIN, but not
        enforced here (a later promotion to Admin doesn't clear it,
        matching set_role's own docstring — it only clears on a
        *demotion away from* Sub Admin, i.e. leaving the tier
        downward).
        """
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin:
                return None
            old = admin.sub_admin_cpm
            if old == cpm:
                return admin
            admin.sub_admin_cpm = cpm
            self.cpm_history.append(
                CPMHistoryEntry(
                    event="sub_admin_cpm_change",
                    detail={"telegram_id": telegram_id, "from": old, "to": cpm, "by": changed_by},
                )
            )
            await self._save_locked()
            return admin

    async def set_admin_ad_count(
        self, telegram_id: int, ad_count: Optional[int], changed_by: int
    ) -> Optional[Admin]:
        """Owner-only per-Admin/Sub-Admin ad count override.
        `ad_count=None` clears it, falling back to the platform-wide
        `len(AdNetworkSetting.slot_sequence)` — see
        models.effective_ad_count() for the full priority order. Bounds
        (MIN_AD_COUNT..MAX_AD_COUNT) are enforced by the caller
        (app.py), same as set_sub_admin_cpm leaves its own >= 0 check to
        the caller. Unlike set_sub_admin_cpm/set_link_auto_delete, this
        applies to Role.ADMIN as well as Role.SUB_ADMIN, and is
        therefore never cleared by set_role/resolve_admin_request on a
        promotion or demotion between those two tiers — it simply
        carries over.

        Real-time by construction: nothing here touches any existing
        Link row. `effective_ad_count()` is computed fresh from this
        Admin's current `ad_count` on every `/r/{short_code}` and
        `/api/ad-config/{short_code}` call, so the change is visible on
        every link this Admin/Sub Admin owns the instant it's saved.
        """
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin:
                return None
            old = admin.ad_count
            if old == ad_count:
                return admin
            admin.ad_count = ad_count
            self.cpm_history.append(
                CPMHistoryEntry(
                    event="admin_ad_count_change",
                    detail={"telegram_id": telegram_id, "from": old, "to": ad_count, "by": changed_by},
                )
            )
            await self._save_locked()
            return admin

    async def set_link_auto_delete(
        self, telegram_id: int, months: Optional[int], changed_by: int
    ) -> Optional[Admin]:
        """Owner-only per-Sub-Admin link auto-delete window
        (SUB_ADMIN_AUTO_DELETE_CHOICES, or None/0 for "never"). Only
        ever applied to *new* links from now on — see create_link's
        docstring for why this is never retroactive.
        """
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin:
                return None
            normalized = months if months else None
            old = admin.link_auto_delete_months
            if old == normalized:
                return admin
            admin.link_auto_delete_months = normalized
            self.cpm_history.append(
                CPMHistoryEntry(
                    event="link_auto_delete_change",
                    detail={"telegram_id": telegram_id, "from": old, "to": normalized, "by": changed_by},
                )
            )
            await self._save_locked()
            return admin

    # ------------------------------------------------------------------
    # Sub Admin -> Admin promotion requests
    # ------------------------------------------------------------------

    async def submit_admin_request(self, telegram_id: int, note: Optional[str]) -> Optional[Admin]:
        """Records a Sub Admin's request to be promoted to Admin.
        Callers (app.py / bot.py) are expected to have already checked
        that this Admin is currently Role.SUB_ADMIN and doesn't already
        have a request pending — this method itself just performs the
        write, matching the rest of this module's pattern (e.g.
        create_link doesn't re-check for a Traffic Source either).
        """
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin:
                return None
            admin.admin_request_status = AdminRequestStatus.PENDING
            admin.admin_request_note = note
            admin.admin_request_at = now_iso()
            admin.admin_request_reason = None
            admin.admin_request_resolved_at = None
            self.cpm_history.append(
                CPMHistoryEntry(
                    event="admin_request_submitted",
                    detail={"telegram_id": telegram_id, "note": note},
                )
            )
            await self._save_locked()
            return admin

    async def list_admin_requests(self, status: AdminRequestStatus = AdminRequestStatus.PENDING) -> List[Admin]:
        return [a for a in self.admins.values() if a.admin_request_status == status]

    async def resolve_admin_request(
        self, telegram_id: int, approve: bool, reason: Optional[str], resolved_by: int
    ) -> Optional[Admin]:
        """Owner decision on a pending Admin request. Approving promotes
        Role.SUB_ADMIN -> Role.ADMIN and clears the same Sub-Admin-only
        fields set_role does on any demotion away from that tier (kept
        as a separate inline update here rather than calling set_role,
        since self._lock isn't reentrant); rejecting keeps the Sub Admin
        at their current tier
        and records `reason` so bot.py / panel.html can show it back to
        them. Either way `admin_request_status` stops being "pending" —
        approved requests clear it to None (the role change *is* the
        record), rejected ones flip it to "rejected" so the Sub Admin
        can still see why, and can submit a fresh request later.
        """
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin or admin.admin_request_status != AdminRequestStatus.PENDING:
                return None
            if approve:
                admin.role = Role.ADMIN
                admin.admin_request_status = None
                admin.admin_request_reason = None
                admin.sub_admin_cpm = None
                admin.link_auto_delete_months = None
                event = "admin_request_approved"
            else:
                admin.admin_request_status = AdminRequestStatus.REJECTED
                admin.admin_request_reason = reason
                event = "admin_request_rejected"
            admin.admin_request_resolved_at = now_iso()
            self.cpm_history.append(
                CPMHistoryEntry(
                    event=event,
                    detail={"telegram_id": telegram_id, "reason": reason, "by": resolved_by},
                )
            )
            await self._save_locked()
            return admin

    # ------------------------------------------------------------------
    # Policy (privacy policy / terms every user must accept)
    # ------------------------------------------------------------------

    async def get_policy_setting(self) -> PolicySetting:
        return self.policy_setting

    async def update_policy_text(self, text: str, updated_by: int) -> PolicySetting:
        """Owner-only edit (see app.py's POST /api/admin/policy and
        bot.py's /policy command). Bumping `version` is what makes every
        Admin's stored `policy_accepted_version` stale, so everyone is
        transparently re-prompted with the new text on their next
        interaction with the bot — see bot.py's PolicyGateMiddleware.
        """
        async with self._lock:
            ps = self.policy_setting
            ps.text = text
            ps.version += 1
            ps.updated_at = now_iso()
            ps.updated_by = updated_by
            self.cpm_history.append(
                CPMHistoryEntry(
                    event="policy_change",
                    detail={"new_version": ps.version, "by": updated_by},
                )
            )
            await self._save_locked()
            return ps

    async def accept_policy(self, telegram_id: int) -> Optional[Admin]:
        """Records that this Admin tapped "Accept" on the currently
        active policy version — called from bot.py's Accept callback.
        """
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin:
                return None
            admin.policy_accepted_version = self.policy_setting.version
            admin.policy_accepted_at = now_iso()
            await self._save_locked()
            return admin

    async def has_accepted_current_policy(self, telegram_id: int) -> bool:
        admin = self.admins.get(telegram_id)
        if not admin:
            return False
        return admin.policy_accepted_version >= self.policy_setting.version

    # ------------------------------------------------------------------
    # Ad networks (Adsgram / Monetag / GigaPub credentials + slot order)
    # ------------------------------------------------------------------
    # Same single-row pattern as CPMSetting/PolicySetting above. Bounded
    # by MIN_AD_COUNT/MAX_AD_COUNT below since a slot sequence longer
    # than the max possible Link.ad_count could never be fully reached.

    async def get_ad_network_setting(self) -> AdNetworkSetting:
        return self.ad_network_setting

    async def update_ad_network_setting(
        self,
        *,
        adsgram_block_id: Optional[str] = None,
        monetag_zone_id: Optional[str] = None,
        monetag_sdk_url: Optional[str] = None,
        gigapub_project_id: Optional[str] = None,
        slot_sequence: Optional[List[AdNetwork]] = None,
        updated_by: Optional[int] = None,
    ) -> AdNetworkSetting:
        async with self._lock:
            ans = self.ad_network_setting
            detail: dict = {}

            if adsgram_block_id is not None and adsgram_block_id != ans.adsgram_block_id:
                detail["adsgram_block_id"] = {"from": ans.adsgram_block_id, "to": adsgram_block_id}
                ans.adsgram_block_id = adsgram_block_id
            if monetag_zone_id is not None and monetag_zone_id != ans.monetag_zone_id:
                detail["monetag_zone_id"] = {"from": ans.monetag_zone_id, "to": monetag_zone_id}
                ans.monetag_zone_id = monetag_zone_id
            if monetag_sdk_url is not None and monetag_sdk_url != ans.monetag_sdk_url:
                detail["monetag_sdk_url"] = {"from": ans.monetag_sdk_url, "to": monetag_sdk_url}
                ans.monetag_sdk_url = monetag_sdk_url
            if gigapub_project_id is not None and gigapub_project_id != ans.gigapub_project_id:
                detail["gigapub_project_id"] = {"from": ans.gigapub_project_id, "to": gigapub_project_id}
                ans.gigapub_project_id = gigapub_project_id
            if slot_sequence is not None:
                old_values = [n.value for n in ans.slot_sequence]
                new_values = [n.value for n in slot_sequence]
                if new_values != old_values:
                    detail["slot_sequence"] = {"from": old_values, "to": new_values}
                    ans.slot_sequence = slot_sequence

            ans.updated_at = now_iso()
            ans.updated_by = updated_by

            if detail:
                detail["by"] = updated_by
                self.cpm_history.append(CPMHistoryEntry(event="ad_network_change", detail=detail))

            await self._save_locked()
            return ans

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    # Everything below reads only from the in-memory dicts populated by
    # load()/_save_locked() — no direct Supabase calls needed, so this
    # section is unchanged from the original JSON-backed version.

    async def platform_income_summary(self, days: int = 30) -> dict:
        """Platform-wide income and payout numbers for the Owner's Stats
        tab — reconciling against Adsgram's own dashboard is the whole
        point, so every figure here is derived straight from `views`'
        own `credited_amount` (same source `admin_stats`' per-Admin
        lifetime/today figures use), never from `balance_confirmed` —
        a manual balance correction (`set_admin_balance`) would then
        silently skew what's supposed to be "real ad revenue credited".

        `lifetime_income` is every CONFIRMED view's credited_amount,
        summed across every Admin — genuinely all money ever credited to
        anyone on the platform, not just what's still sitting
        unwithdrawn (`total_confirmed_liability` on platform_stats is
        that different, narrower number).

        `income_trend`/`withdrawn_trend` are day-by-day buckets over the
        trailing `days` calendar days (UTC) — `income_last_7_days` /
        `_30_days` and their withdrawn counterparts are just those same
        buckets summed, computed once here so the two never drift apart.
        A capped view earns `credited_amount = 0` (see
        cpm_engine.credit_new_view), so excluding `daily_capped` views
        below is a no-op for the totals but keeps this consistent with
        every other income/view figure in this module.
        """
        today = datetime.now(timezone.utc).date()
        earliest = today - timedelta(days=days - 1)
        income_buckets: Dict[object, float] = {earliest + timedelta(days=i): 0.0 for i in range(days)}
        withdrawn_buckets: Dict[object, float] = {earliest + timedelta(days=i): 0.0 for i in range(days)}

        lifetime_income = 0.0
        for v in self.views.values():
            if v.daily_capped or v.counted_status != CountedStatus.CONFIRMED:
                continue
            amount = v.credited_amount or 0.0
            lifetime_income += amount
            try:
                created = datetime.fromisoformat(v.created_at)
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            bucket = income_buckets.get(created.astimezone(timezone.utc).date())
            if bucket is not None:
                income_buckets[created.astimezone(timezone.utc).date()] += amount

        withdrawn_lifetime = 0.0
        for w in self.withdrawals.values():
            if w.status != WithdrawStatus.PAID:
                continue
            withdrawn_lifetime += w.amount
            if not w.resolved_at:
                continue
            try:
                resolved = datetime.fromisoformat(w.resolved_at)
            except ValueError:
                continue
            if resolved.tzinfo is None:
                resolved = resolved.replace(tzinfo=timezone.utc)
            bucket = withdrawn_buckets.get(resolved.astimezone(timezone.utc).date())
            if bucket is not None:
                withdrawn_buckets[resolved.astimezone(timezone.utc).date()] += w.amount

        today_income = income_buckets.get(today, 0.0)
        last_7 = today - timedelta(days=6)
        income_7d = sum(v for d, v in income_buckets.items() if d >= last_7)
        withdrawn_7d = sum(v for d, v in withdrawn_buckets.items() if d >= last_7)
        income_30d = sum(income_buckets.values())
        withdrawn_30d = sum(withdrawn_buckets.values())

        return {
            "lifetime_income": round(lifetime_income, 4),
            "lifetime_withdrawn": round(withdrawn_lifetime, 4),
            "today_income": round(today_income, 4),
            "income_last_7_days": round(income_7d, 4),
            "income_last_30_days": round(income_30d, 4),
            "withdrawn_last_7_days": round(withdrawn_7d, 4),
            "withdrawn_last_30_days": round(withdrawn_30d, 4),
            "income_trend": [
                {"date": d.isoformat(), "amount": round(income_buckets[d], 4)} for d in sorted(income_buckets)
            ],
            "withdrawn_trend": [
                {"date": d.isoformat(), "amount": round(withdrawn_buckets[d], 4)} for d in sorted(withdrawn_buckets)
            ],
        }

    async def own_analytics_summary(self, telegram_id: int, days: int = 30) -> dict:
        """Personal earnings + views dashboard for one Admin/Sub Admin's
        own home screen (webapp/panel.html's Overview tab) — the
        self-service, single-Admin counterpart to platform_income_summary
        above. Everything here is scoped to `telegram_id`'s own links via
        list_views_by_owner, so two different Admins calling this never
        see each other's numbers, unlike the Owner-only, platform-wide
        methods.

        Deliberately excludes anything about the Anti-Abuse System's
        daily cap (no daily_capped_views count, no missed-earnings
        breakdown) — a capped view is silently dropped from both trends
        below (0 income, not counted as a "genuine" view), mirroring the
        same visibility boundary GET /api/links already enforces for an
        Admin's own link list: an Admin never sees that a view was
        capped, it simply isn't there. That boundary is deliberately kept
        Owner-only (admin_stats / platform_stats) — this method must
        never grow a daily_capped-shaped field even if a future caller
        asks for one.

        `top_links` ranks by view count (not income) since that's the
        more actionable number for someone deciding which of their
        traffic sources to lean into — each row's income is shown
        alongside it, not used to sort.
        """
        views = await self.list_views_by_owner(telegram_id)
        genuine_views = [v for v in views if not v.daily_capped]

        today = datetime.now(timezone.utc).date()
        earliest = today - timedelta(days=days - 1)
        income_buckets: Dict[object, float] = {earliest + timedelta(days=i): 0.0 for i in range(days)}
        view_buckets: Dict[object, int] = {earliest + timedelta(days=i): 0 for i in range(days)}

        lifetime_income = 0.0
        per_link: Dict[str, dict] = {}
        for v in genuine_views:
            link = self.links.get(v.short_code)
            try:
                created = datetime.fromisoformat(v.created_at)
            except ValueError:
                created = None
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            bucket_date = created.astimezone(timezone.utc).date() if created is not None else None
            if bucket_date is not None and bucket_date in view_buckets:
                view_buckets[bucket_date] += 1

            row = per_link.setdefault(
                v.short_code,
                {
                    "short_code": v.short_code,
                    "destination_url": link.destination_url if link else None,
                    "views": 0,
                    "income": 0.0,
                },
            )
            row["views"] += 1

            if v.counted_status == CountedStatus.CONFIRMED:
                amount = v.credited_amount or 0.0
                lifetime_income += amount
                row["income"] = round(row["income"] + amount, 6)
                if bucket_date is not None and bucket_date in income_buckets:
                    income_buckets[bucket_date] += amount

        today_income = income_buckets.get(today, 0.0)
        last_7 = today - timedelta(days=6)
        income_7d = sum(v for d, v in income_buckets.items() if d >= last_7)
        views_7d = sum(v for d, v in view_buckets.items() if d >= last_7)

        top_links = sorted(per_link.values(), key=lambda r: r["views"], reverse=True)[:5]
        for r in top_links:
            r["income"] = round(r["income"], 4)

        links = await self.list_links_by_owner(telegram_id)

        return {
            "lifetime_income": round(lifetime_income, 4),
            "today_income": round(today_income, 4),
            "income_last_7_days": round(income_7d, 4),
            "views_last_7_days": views_7d,
            "total_links": len(links),
            "total_views": len(genuine_views),
            "window_days": days,
            "income_trend": [
                {"date": d.isoformat(), "amount": round(income_buckets[d], 4)} for d in sorted(income_buckets)
            ],
            "views_trend": [
                {"date": d.isoformat(), "views": view_buckets[d]} for d in sorted(view_buckets)
            ],
            "top_links": top_links,
        }

    async def platform_analytics_summary(
        self,
        role_filter: str = "both",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict:
        """Platform-wide earnings + views dashboard for the Owner's home
        screen (webapp/panel.html's Overview tab) — the aggregate,
        multi-Admin counterpart to own_analytics_summary above. Rather
        than one Admin's own links, this sums every Admin/Sub Admin's
        genuine (non-daily-capped) views across the caller-chosen
        `role_filter` and `[start_date, end_date]` window, so the Owner
        can compare "how is the whole Admin tier doing" against "how is
        the whole Sub Admin tier doing" without opening each profile
        individually.

        `role_filter` is one of "admin" (Role.ADMIN only), "sub_admin"
        (Role.SUB_ADMIN only), or "both" (default — every Admin and Sub
        Admin combined). The Owner's own links and any Viewer are always
        excluded — a Viewer has no links to speak of, and the Owner's
        own personal link income is a different, single-person concept
        this screen is deliberately not for (own_analytics_summary
        already covers that, the same way it covers any Admin's own
        links, if the Owner ever uses their own "My Links" tab).

        `start_date`/`end_date` default to a trailing 30-day window
        ending today (UTC) when omitted, matching own_analytics_summary's
        own 30-day default — but unlike that method, both can be set to
        any explicit day so the Owner can look back further than 30 days
        with exact boundaries (webapp/panel.html's custom date-range
        picker). The window is capped at 366 days to keep a single
        request's bucket count sane; an overlong request is silently
        clamped to the most recent 366 days rather than rejected
        outright, since a slightly-shorter-than-requested chart is more
        useful than an error.

        `top_performers` ranks by income (not view count, unlike
        own_analytics_summary's own `top_links`) since "who is actually
        earning well" is the more direct answer to what the Owner is
        checking here than a raw view count, which per-Admin CPM
        overrides can make misleading on its own.
        """
        role_map = {
            "admin": {Role.ADMIN},
            "sub_admin": {Role.SUB_ADMIN},
            "both": {Role.ADMIN, Role.SUB_ADMIN},
        }
        normalized_filter = role_filter if role_filter in role_map else "both"
        wanted_roles = role_map[normalized_filter]
        target_ids = {a.telegram_id for a in self.admins.values() if a.role in wanted_roles}

        today = datetime.now(timezone.utc).date()
        if end_date is None:
            end_date = today
        if start_date is None:
            start_date = end_date - timedelta(days=29)
        if end_date < start_date:
            start_date, end_date = end_date, start_date
        if (end_date - start_date).days > 365:
            start_date = end_date - timedelta(days=365)

        num_days = (end_date - start_date).days + 1
        income_buckets: Dict[object, float] = {start_date + timedelta(days=i): 0.0 for i in range(num_days)}
        view_buckets: Dict[object, int] = {start_date + timedelta(days=i): 0 for i in range(num_days)}

        total_income = 0.0
        total_views = 0
        per_admin: Dict[int, dict] = {}

        for v in self.views.values():
            if v.daily_capped:
                continue
            link = self.links.get(v.short_code)
            if not link or link.owner_telegram_id not in target_ids:
                continue
            try:
                created = datetime.fromisoformat(v.created_at)
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            d = created.astimezone(timezone.utc).date()
            if d < start_date or d > end_date:
                continue

            total_views += 1
            if d in view_buckets:
                view_buckets[d] += 1

            admin = self.admins.get(link.owner_telegram_id)
            row = per_admin.setdefault(
                link.owner_telegram_id,
                {
                    "telegram_id": link.owner_telegram_id,
                    "username": admin.username if admin else None,
                    "role": admin.role.value if admin else None,
                    "views": 0,
                    "income": 0.0,
                },
            )
            row["views"] += 1

            if v.counted_status == CountedStatus.CONFIRMED:
                amount = v.credited_amount or 0.0
                total_income += amount
                row["income"] = round(row["income"] + amount, 6)
                if d in income_buckets:
                    income_buckets[d] += amount

        top_performers = sorted(per_admin.values(), key=lambda r: r["income"], reverse=True)[:5]
        for r in top_performers:
            r["income"] = round(r["income"], 4)

        avg_daily_income = round(total_income / num_days, 4) if num_days else 0.0

        return {
            "role_filter": normalized_filter,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "window_days": num_days,
            "total_admins": len(target_ids),
            "total_income": round(total_income, 4),
            "total_views": total_views,
            "avg_daily_income": avg_daily_income,
            "income_trend": [
                {"date": d.isoformat(), "amount": round(income_buckets[d], 4)} for d in sorted(income_buckets)
            ],
            "views_trend": [
                {"date": d.isoformat(), "views": view_buckets[d]} for d in sorted(view_buckets)
            ],
            "top_performers": top_performers,
        }

    async def platform_stats(self) -> dict:
        """Platform-wide numbers for the Owner's Stats tab.

        `total_views` deliberately excludes every `daily_capped` view — a
        capped view earned nothing, so it must never inflate the headline
        view count. Missed views are still fully visible to the Owner,
        just via the separate `daily_capped_views` counter and the
        `missed_earnings_*` breakdowns below, never folded into
        `total_views` itself.

        Income/withdrawal figures (lifetime, today, last 7/30 days, plus
        their daily trends) come from `platform_income_summary()` — kept
        as its own method since it's also independently useful, and to
        keep this method's own docstring focused on the view-count side.
        """
        genuine_views = [v for v in self.views.values() if not v.daily_capped]
        pending_payout_views = len(
            [v for v in genuine_views if v.counted_status == CountedStatus.PENDING_PAYOUT]
        )
        daily_capped_views = len(self.views) - len(genuine_views)
        total_confirmed_liability = sum(a.balance_confirmed for a in self.admins.values())
        total_paid_out = sum(w.amount for w in self.withdrawals.values() if w.status == WithdrawStatus.PAID)
        return {
            "total_admins": len(self.admins),
            "total_links": len(self.links),
            "total_views": len(genuine_views),
            "pending_payout_views": pending_payout_views,
            "daily_capped_views": daily_capped_views,
            "total_confirmed_liability": round(total_confirmed_liability, 4),
            "total_paid_out": round(total_paid_out, 4),
            **await self.platform_income_summary(),
            "missed_earnings_trend": await self.missed_earnings_trend(),
            "missed_earnings_by_link": await self.missed_earnings_by_link(),
            "suggested_daily_limit": await self.suggested_daily_limit(),
        }

    async def admin_stats(self, telegram_id: int) -> Optional[dict]:
        """Everything the Owner's per-Admin detail view needs in one call:
        today's income, lifetime income (computed from each view's own
        `credited_amount`, not just the current balance — so it stays
        accurate even after a manual balance correction), withdrawal
        totals, and link/view counts. This is the read side of the
        fraud-watching feature; `set_admin_balance` is the write side.

        `total_views` / `confirmed_views` exclude every `daily_capped`
        view, same as `platform_stats` — a capped view earned nothing, so
        it never counts toward "views" here either, Owner-facing or not.
        `daily_capped_views` is the read side of the Anti-Abuse System
        (see CPMSetting.max_daily_views_per_admin / cpm_engine.py): how
        many of this Admin's views were watched but excluded from
        earnings for crossing a viewer's daily cap — the Owner's
        dedicated window onto missed views, kept separate from
        `total_views` rather than folded into it.
        """
        admin = self.admins.get(telegram_id)
        if not admin:
            return None

        views = await self.list_views_by_owner(telegram_id)
        genuine_views = [v for v in views if not v.daily_capped]
        confirmed_views = [v for v in genuine_views if v.counted_status == CountedStatus.CONFIRMED]
        pending_views = [v for v in genuine_views if v.counted_status == CountedStatus.PENDING_PAYOUT]

        today = datetime.now(timezone.utc).date()
        today_income = 0.0
        lifetime_income = 0.0
        for v in confirmed_views:
            amount = v.credited_amount or 0.0
            lifetime_income = round(lifetime_income + amount, 6)
            try:
                created = datetime.fromisoformat(v.created_at)
            except ValueError:
                created = None
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created.date() == today:
                    today_income = round(today_income + amount, 6)

        links = await self.list_links_by_owner(telegram_id)
        daily_capped_views = len(views) - len(genuine_views)

        admin_withdrawals = [w for w in self.withdrawals.values() if w.admin_telegram_id == telegram_id]
        total_withdrawn = round(
            sum(w.amount for w in admin_withdrawals if w.status == WithdrawStatus.PAID), 6
        )
        pending_withdrawals = [w for w in admin_withdrawals if w.status == WithdrawStatus.PENDING]

        return {
            "admin": admin.model_dump(),
            "today_income": today_income,
            "lifetime_income": lifetime_income,
            "total_withdrawn": total_withdrawn,
            "pending_withdrawal_count": len(pending_withdrawals),
            "pending_withdrawal_amount": round(sum(w.amount for w in pending_withdrawals), 6),
            "total_links": len(links),
            "total_views": len(genuine_views),
            "confirmed_views": len(confirmed_views),
            "pending_views": len(pending_views),
            "daily_capped_views": daily_capped_views,
            "estimated_pending_amount": round(
                len(pending_views) * effective_cpm(admin, self.cpm_setting), 6
            ),
            "missed_earnings_trend": await self.missed_earnings_trend(admin_telegram_id=telegram_id),
            "missed_earnings_by_link": await self.missed_earnings_by_link(admin_telegram_id=telegram_id),
        }

    async def missed_earnings_trend(
        self, admin_telegram_id: Optional[int] = None, days: int = 14
    ) -> List[dict]:
        """Day-by-day view of the Anti-Abuse System's bite: how many views
        were watched but excluded from earnings (`daily_capped`) on each of
        the trailing `days` calendar days (UTC), alongside that day's total
        *attempts* (capped + genuine) for context. A single cumulative
        number hides whether abuse is trending up, down, or was a one-off
        spike; this is the read side that makes the shape visible.

        `total_attempts` is deliberately a different figure from
        `total_views` elsewhere in this module: it's the denominator for
        "how much of this day's traffic was capped", so it must include
        capped views, whereas `total_views` on platform_stats/admin_stats
        must never include them.

        `estimated_missed_amount` is necessarily an estimate: a capped view
        is routed straight to `credited_amount = 0` and never learns what
        rate it would have earned (see cpm_engine.credit_new_view), so this
        multiplies the day's capped count by *today's* current_cpm rather
        than reconstructing a historical rate.

        Pass `admin_telegram_id` to scope the trend to one Admin's links
        only (the per-admin detail view); omit it for the platform-wide
        trend on the Owner's Stats tab.
        """
        cpm_setting = await self.get_cpm_setting()
        today = datetime.now(timezone.utc).date()
        earliest = today - timedelta(days=days - 1)
        buckets: Dict[object, dict] = {
            earliest + timedelta(days=i): {"capped": 0, "total": 0} for i in range(days)
        }

        for v in self.views.values():
            if admin_telegram_id is not None:
                link = self.links.get(v.short_code)
                if not link or link.owner_telegram_id != admin_telegram_id:
                    continue
            try:
                created = datetime.fromisoformat(v.created_at)
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            d = created.astimezone(timezone.utc).date()
            bucket = buckets.get(d)
            if bucket is None:
                continue
            bucket["total"] += 1
            if v.daily_capped:
                bucket["capped"] += 1

        return [
            {
                "date": d.isoformat(),
                "capped_views": buckets[d]["capped"],
                "total_attempts": buckets[d]["total"],
                "estimated_missed_amount": round(buckets[d]["capped"] * cpm_setting.current_cpm, 6),
            }
            for d in sorted(buckets.keys())
        ]

    async def missed_earnings_by_link(
        self, admin_telegram_id: Optional[int] = None, limit: int = 15
    ) -> List[dict]:
        """Ranks links by how many of their views got excluded from
        earnings by the Anti-Abuse daily cap — the read side of "which
        specific link is getting hammered", since a single Admin-level
        `daily_capped_views` count can't distinguish one abused link from
        several clean ones.

        Pass `admin_telegram_id` to restrict to one Admin's own links (their
        per-admin detail view); omit it for the platform-wide top-offenders
        list, which also carries each link's owner so abuse concentrated on
        one Admin — rather than spread thinly across many — is visible at a
        glance instead of buried in an admin-wise total.
        """
        cpm_setting = await self.get_cpm_setting()
        per_link: Dict[str, dict] = {}
        for v in self.views.values():
            link = self.links.get(v.short_code)
            if not link:
                continue
            if admin_telegram_id is not None and link.owner_telegram_id != admin_telegram_id:
                continue
            row = per_link.setdefault(v.short_code, {"total": 0, "capped": 0})
            row["total"] += 1
            if v.daily_capped:
                row["capped"] += 1

        out = []
        for short_code, row in per_link.items():
            if row["capped"] == 0:
                continue
            link = self.links.get(short_code)
            owner = self.admins.get(link.owner_telegram_id) if link else None
            out.append(
                {
                    "short_code": short_code,
                    "destination_url": link.destination_url if link else None,
                    "owner_telegram_id": link.owner_telegram_id if link else None,
                    "owner_username": owner.username if owner else None,
                    "total_attempts": row["total"],
                    "capped_views": row["capped"],
                    "capped_rate": round(row["capped"] / row["total"], 4) if row["total"] else 0.0,
                    "estimated_missed_amount": round(row["capped"] * cpm_setting.current_cpm, 6),
                }
            )
        out.sort(key=lambda r: r["capped_views"], reverse=True)
        return out[:limit]

    async def suggested_daily_limit(
        self, admin_telegram_id: Optional[int] = None, days: int = 14
    ) -> dict:
        """Anti-Abuse System tuning aid (advanced / can ship later): looks
        at how many times each (Admin, viewer) pair actually showed up per
        calendar day over the trailing `days` window — counting every
        logged View regardless of `daily_capped`, since a capped view still
        means "this viewer hit this Admin's links again today" — and
        suggests a `max_daily_views_per_admin` at roughly the 90th
        percentile of that per-viewer-per-day activity.

        The idea: a cap set there catches the heaviest ~10% of repeat-
        viewing days (the likely abuse) while leaving ordinary viewers, who
        rarely reopen the same Admin's links many times in one day,
        uncapped. This is a heuristic, not a guarantee — it's offered as a
        starting point for the Owner to review, not applied automatically.

        Pass `admin_telegram_id` to suggest a limit from one Admin's own
        traffic only; omit it to suggest a platform-wide default from
        every Admin's combined history.
        """
        today = datetime.now(timezone.utc).date()
        earliest = today - timedelta(days=days - 1)
        counts: Dict[Tuple[int, int, object], int] = {}
        for v in self.views.values():
            link = self.links.get(v.short_code)
            if not link:
                continue
            if admin_telegram_id is not None and link.owner_telegram_id != admin_telegram_id:
                continue
            try:
                created = datetime.fromisoformat(v.created_at)
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            d = created.astimezone(timezone.utc).date()
            if d < earliest or d > today:
                continue
            key = (link.owner_telegram_id, v.viewer_telegram_id, d)
            counts[key] = counts.get(key, 0) + 1

        cpm_setting = await self.get_cpm_setting()
        values = sorted(counts.values())
        n = len(values)
        if n == 0:
            return {
                "sample_size": 0,
                "window_days": days,
                "suggested_limit": None,
                "current_limit": cpm_setting.max_daily_views_per_admin,
            }

        def percentile(p: float) -> int:
            if n == 1:
                return values[0]
            idx = min(n - 1, max(0, round(p * (n - 1))))
            return values[idx]

        return {
            "sample_size": n,
            "window_days": days,
            "median_views_per_viewer_per_day": percentile(0.50),
            "p90_views_per_viewer_per_day": percentile(0.90),
            "p99_views_per_viewer_per_day": percentile(0.99),
            "suggested_limit": max(percentile(0.90), 1),
            "current_limit": cpm_setting.max_daily_views_per_admin,
        }

    # ------------------------------------------------------------------
    # API keys (Owner/Admin public REST API access — see API_DOCS.md)
    # ------------------------------------------------------------------

    _API_KEY_PREFIX = "tgs_"

    @staticmethod
    def _hash_api_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    async def create_api_key(self, telegram_id: int, name: str) -> Tuple[ApiKey, str]:
        """Generates a brand-new key for `telegram_id`, stores only its
        hash, and returns `(record, raw_key)` — the *only* moment the raw
        secret ever exists outside the caller's own hands, so app.py must
        hand it back to the requester in that same response and never log
        or re-return it afterward.
        """
        raw_key = self._API_KEY_PREFIX + secrets.token_hex(24)
        async with self._lock:
            key = ApiKey(
                owner_telegram_id=telegram_id,
                name=name,
                key_hash=self._hash_api_key(raw_key),
                key_prefix=raw_key[:12],
            )
            self.api_keys[key.key_id] = key
            self._api_key_hash_index[key.key_hash] = key.key_id
            await self._save_locked()
            return key, raw_key

    async def list_api_keys(self, telegram_id: int) -> List[ApiKey]:
        keys = [k for k in self.api_keys.values() if k.owner_telegram_id == telegram_id]
        keys.sort(key=lambda k: k.created_at, reverse=True)
        return keys

    async def revoke_api_key(self, key_id: str, telegram_id: int) -> bool:
        """Only the Admin who generated a key can revoke it — an Owner
        revoking someone else's key isn't supported here; banning that
        Admin (which `require_api_key` already checks) is the platform-
        level way to cut off all of their keys at once instead.
        """
        async with self._lock:
            key = self.api_keys.get(key_id)
            if not key or key.owner_telegram_id != telegram_id or key.revoked_at:
                return False
            key.revoked_at = now_iso()
            await self._save_locked()
            return True

    async def get_admin_by_api_key(self, raw_key: str) -> Optional[Admin]:
        """Resolves a raw `Authorization`/`X-API-Key` header value back to
        the Admin who generated it — None if the key is unknown, malformed,
        or revoked. Best-effort bumps `last_used_at` (not lock-guarded
        against a concurrent revoke/rotate racing it — acceptable, since
        the worst case is a slightly stale timestamp, never a security
        issue) so the panel's API tab can show "last used" per key.
        """
        key_id = self._api_key_hash_index.get(self._hash_api_key(raw_key))
        if not key_id:
            return None
        key = self.api_keys.get(key_id)
        if not key or key.revoked_at:
            return None
        admin = self.admins.get(key.owner_telegram_id)
        if not admin:
            return None
        async with self._lock:
            key.last_used_at = now_iso()
            await self._save_locked()
        return admin

    async def list_balance_adjustments(self, telegram_id: int, limit: int = 20) -> List[dict]:
        entries = [
            e.model_dump()
            for e in self.cpm_history
            if e.event == "balance_adjustment" and e.detail.get("telegram_id") == telegram_id
        ]
        entries.sort(key=lambda e: e["created_at"], reverse=True)
        return entries[:limit]
