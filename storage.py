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
is enough to make check-then-act sequences (e.g. the view dedupe check)
atomic — no real concurrency bugs, no need for a DB transaction. The
`views` table's `(short_code, viewer_telegram_id)` UNIQUE constraint is
kept as a second, database-level safety net in `create_view` in case
that assumption is ever wrong (e.g. two Render instances one day).

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
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from supabase import AsyncClient, create_async_client

from models import (
    Admin,
    AdminStatus,
    CPMHistoryEntry,
    CPMSetting,
    Link,
    Role,
    TrafficSource,
    View,
    WithdrawMethod,
    WithdrawRequest,
    WithdrawStatus,
    now_iso,
)


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
        self.cpm_history: List[CPMHistoryEntry] = []

        self._view_index: Dict[Tuple[str, int], str] = {}
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
        cpm_history_res = await self.client.table("cpm_history").select("*").execute()

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

        self.cpm_history = [CPMHistoryEntry(**row) for row in cpm_history_res.data]

        self._view_index = {
            (v.short_code, v.viewer_telegram_id): v.view_id for v in self.views.values()
        }

        async with self._lock:
            await self._save_locked()
        self._loaded = True

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
        cpm_history_rows = [e.model_dump(mode="json") for e in self.cpm_history]

        if admin_rows:
            await self.client.table("admins").upsert(admin_rows, on_conflict="telegram_id").execute()
        if traffic_rows:
            await self.client.table("traffic_sources").upsert(traffic_rows, on_conflict="id").execute()
        if link_rows:
            await self.client.table("links").upsert(link_rows, on_conflict="short_code").execute()
        if view_rows:
            await self.client.table("views").upsert(view_rows, on_conflict="view_id").execute()
        if withdrawal_rows:
            await self.client.table("withdrawals").upsert(withdrawal_rows, on_conflict="request_id").execute()
        await self.client.table("cpm_settings").upsert(cpm_setting_row, on_conflict="id").execute()
        if cpm_history_rows:
            await self.client.table("cpm_history").upsert(cpm_history_rows, on_conflict="entry_id").execute()

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
        """Auto-creates an Admin/Owner record on first /start (Section 2)."""
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if admin:
                if username and admin.username != username:
                    admin.username = username
                    await self._save_locked()
                return admin
            role = Role.OWNER if telegram_id == owner_id else Role.ADMIN
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

    async def add_traffic_source(self, telegram_id: int, platform: str, url: str) -> Optional[TrafficSource]:
        """Appends one more "where do your viewers come from" entry for
        this Admin. An Admin can hold several at once (one per platform,
        or several on the same platform) and needs at least one before
        creating any short links.
        """
        async with self._lock:
            admin = self.admins.get(telegram_id)
            if not admin:
                return None
            source = TrafficSource(platform=platform, url=url)
            admin.traffic_sources.append(source)
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

    async def create_link(
        self,
        short_code: str,
        owner_telegram_id: int,
        destination_url: str,
        ad_count: Optional[int] = None,
    ) -> Link:
        async with self._lock:
            link = Link(
                short_code=short_code,
                owner_telegram_id=owner_telegram_id,
                destination_url=destination_url,
                ad_count=ad_count if ad_count is not None else self.DEFAULT_AD_COUNT,
            )
            self.links[short_code] = link
            await self._save_locked()
            return link

    async def get_link(self, short_code: str) -> Optional[Link]:
        return self.links.get(short_code)

    async def list_links_by_owner(self, owner_telegram_id: int) -> List[Link]:
        return [l for l in self.links.values() if l.owner_telegram_id == owner_telegram_id]

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

    async def find_view(self, short_code: str, viewer_telegram_id: int) -> Optional[View]:
        vid = self._view_index.get((short_code, viewer_telegram_id))
        return self.views.get(vid) if vid else None

    async def create_view(self, short_code: str, viewer_telegram_id: int) -> Optional[View]:
        """Returns None if this (short_code, viewer) pair already has a
        view — the dedupe rule from Section 9.3. The check-then-insert is
        atomic because no `await` happens between them while the lock is
        held. The `views` table's UNIQUE(short_code, viewer_telegram_id)
        constraint is a second safety net in case that in-process
        assumption is ever violated.
        """
        async with self._lock:
            key = (short_code, viewer_telegram_id)
            if key in self._view_index:
                return None
            view = View(short_code=short_code, viewer_telegram_id=viewer_telegram_id)
            try:
                await self.client.table("views").insert(view.model_dump(mode="json")).execute()
            except Exception as exc:
                if "duplicate" in str(exc).lower() or "23505" in str(exc):
                    return None
                raise
            self.views[view.view_id] = view
            self._view_index[key] = view.view_id
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

    async def append_history(self, event: str, detail: dict) -> None:
        async with self._lock:
            self.cpm_history.append(CPMHistoryEntry(event=event, detail=detail))
            await self._save_locked()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    # Everything below reads only from the in-memory dicts populated by
    # load()/_save_locked() — no direct Supabase calls needed, so this
    # section is unchanged from the original JSON-backed version.

    async def platform_stats(self) -> dict:
        """Platform-wide numbers for the Owner's Stats tab.

        `total_views` deliberately excludes every `daily_capped` view — a
        capped view earned nothing, so it must never inflate the headline
        view count. Missed views are still fully visible to the Owner,
        just via the separate `daily_capped_views` counter and the
        `missed_earnings_*` breakdowns below, never folded into
        `total_views` itself.
        """
        from models import CountedStatus  # local import avoids a cycle at module load

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
        from models import CountedStatus  # local import avoids a cycle at module load

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
            "estimated_pending_amount": round(len(pending_views) * self.cpm_setting.current_cpm, 6),
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

    async def list_balance_adjustments(self, telegram_id: int, limit: int = 20) -> List[dict]:
        entries = [
            e.model_dump()
            for e in self.cpm_history
            if e.event == "balance_adjustment" and e.detail.get("telegram_id") == telegram_id
        ]
        entries.sort(key=lambda e: e["created_at"], reverse=True)
        return entries[:limit]
