"""In-memory + JSON-file-backed storage for TGSHORTBOT (MVP).

Everything lives in memory for fast reads; every mutation is flushed to
`data/store.json` immediately (write-through) using an atomic
tmp-file-then-rename so a crash mid-write can never corrupt the store.

An `asyncio.Lock` serializes all mutations. Because the whole app runs on
a single asyncio event loop, this is sufficient to make check-then-act
sequences (e.g. the view dedupe check) atomic with no real concurrency
bugs, without needing a database transaction.

Swapping this module for a SQLite/Postgres-backed one later can reuse the
exact same method signatures and the Link/View/Admin/etc. models
unchanged (see PRD Section 9.3).
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

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
    def __init__(self, data_file: str):
        self.data_file = data_file
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

    @staticmethod
    def _migrate_admin_dict(v: dict) -> dict:
        """Upgrades a pre-multi-traffic-source Admin record (a single
        `traffic_source_platform` / `traffic_source_url` pair) into the
        current `traffic_sources: [...]` list shape, in place, so old
        `data/store.json` files keep working after this change instead of
        crash-looping on the first load.
        """
        if "traffic_sources" in v and v["traffic_sources"] is not None:
            return v
        legacy_url = v.pop("traffic_source_url", None)
        legacy_platform = v.pop("traffic_source_platform", None)
        legacy_updated_at = v.pop("traffic_source_updated_at", None)
        if legacy_url:
            v["traffic_sources"] = [
                {
                    "platform": legacy_platform or "Other",
                    "url": legacy_url,
                    "created_at": legacy_updated_at or now_iso(),
                    "updated_at": legacy_updated_at or now_iso(),
                }
            ]
        else:
            v["traffic_sources"] = []
        return v

    @staticmethod
    def _as_dict_items(raw_value, id_field: str):
        """Normalizes a stored collection to an iterable of (key, value) dicts.

        The store is supposed to always hold collections as JSON objects
        (dict keyed by id), but a legacy/corrupt file could have them as a
        JSON array instead. Without this, a single bad field permanently
        crash-loops the app on every restart since load() never gets far
        enough to re-save a corrected file. Unknown/other shapes are
        treated as empty rather than raising.
        """
        if isinstance(raw_value, dict):
            return raw_value.items()
        if isinstance(raw_value, list):
            return [(str(item.get(id_field)), item) for item in raw_value if isinstance(item, dict)]
        return []

    async def load(self) -> None:
        os.makedirs(os.path.dirname(self.data_file) or ".", exist_ok=True)
        if os.path.exists(self.data_file):
            with open(self.data_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.admins = {
                int(k): Admin(**self._migrate_admin_dict(dict(v)))
                for k, v in self._as_dict_items(raw.get("admins", {}), "telegram_id")
            }
            self.links = {
                k: Link(**v) for k, v in self._as_dict_items(raw.get("links", {}), "short_code")
            }
            self.views = {
                k: View(**v) for k, v in self._as_dict_items(raw.get("views", {}), "view_id")
            }
            self.withdrawals = {
                k: WithdrawRequest(**v)
                for k, v in self._as_dict_items(raw.get("withdrawals", {}), "request_id")
            }
            if raw.get("cpm_setting"):
                self.cpm_setting = CPMSetting(**raw["cpm_setting"])
            self.cpm_history = [CPMHistoryEntry(**e) for e in raw.get("cpm_history", [])]
            self._view_index = {
                (v.short_code, v.viewer_telegram_id): v.view_id for v in self.views.values()
            }
            async with self._lock:
                await self._save_locked()
        else:
            await self._save_locked()
        self._loaded = True

    async def _save_locked(self) -> None:
        """Caller must already hold self._lock."""
        payload = {
            "admins": {str(k): v.model_dump() for k, v in self.admins.items()},
            "links": {k: v.model_dump() for k, v in self.links.items()},
            "views": {k: v.model_dump() for k, v in self.views.items()},
            "withdrawals": {k: v.model_dump() for k, v in self.withdrawals.items()},
            "cpm_setting": self.cpm_setting.model_dump(),
            "cpm_history": [e.model_dump() for e in self.cpm_history],
        }
        dir_name = os.path.dirname(self.data_file) or "."
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".store_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.data_file)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

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
                await self._save_locked()
            return changed

    # ------------------------------------------------------------------
    # Link
    # ------------------------------------------------------------------

    async def create_link(self, short_code: str, owner_telegram_id: int, destination_url: str) -> Link:
        async with self._lock:
            link = Link(
                short_code=short_code,
                owner_telegram_id=owner_telegram_id,
                destination_url=destination_url,
            )
            self.links[short_code] = link
            await self._save_locked()
            return link

    async def get_link(self, short_code: str) -> Optional[Link]:
        return self.links.get(short_code)

    async def list_links_by_owner(self, owner_telegram_id: int) -> List[Link]:
        return [l for l in self.links.values() if l.owner_telegram_id == owner_telegram_id]

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
        held.
        """
        async with self._lock:
            key = (short_code, viewer_telegram_id)
            if key in self._view_index:
                return None
            view = View(short_code=short_code, viewer_telegram_id=viewer_telegram_id)
            self.views[view.view_id] = view
            self._view_index[key] = view.view_id
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

    async def platform_stats(self) -> dict:
        from models import CountedStatus  # local import avoids a cycle at module load

        pending_payout_views = len(
            [v for v in self.views.values() if v.counted_status == CountedStatus.PENDING_PAYOUT]
        )
        daily_capped_views = len([v for v in self.views.values() if v.daily_capped])
        total_confirmed_liability = sum(a.balance_confirmed for a in self.admins.values())
        total_paid_out = sum(w.amount for w in self.withdrawals.values() if w.status == WithdrawStatus.PAID)
        return {
            "total_admins": len(self.admins),
            "total_links": len(self.links),
            "total_views": len(self.views),
            "pending_payout_views": pending_payout_views,
            "daily_capped_views": daily_capped_views,
            "total_confirmed_liability": round(total_confirmed_liability, 4),
            "total_paid_out": round(total_paid_out, 4),
        }

    async def admin_stats(self, telegram_id: int) -> Optional[dict]:
        """Everything the Owner's per-Admin detail view needs in one call:
        today's income, lifetime income (computed from each view's own
        `credited_amount`, not just the current balance — so it stays
        accurate even after a manual balance correction), withdrawal
        totals, and link/view counts. This is the read side of the
        fraud-watching feature; `set_admin_balance` is the write side.

        `daily_capped_views` is the read side of the Anti-Abuse System
        (see CPMSetting.max_daily_views_per_admin / cpm_engine.py): how
        many of this Admin's views were watched but excluded from
        earnings for crossing a viewer's daily cap.
        """
        from models import CountedStatus  # local import avoids a cycle at module load

        admin = self.admins.get(telegram_id)
        if not admin:
            return None

        views = await self.list_views_by_owner(telegram_id)
        confirmed_views = [v for v in views if v.counted_status == CountedStatus.CONFIRMED]
        pending_views = [v for v in views if v.counted_status == CountedStatus.PENDING_PAYOUT]

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
        daily_capped_views = len([v for v in views if v.daily_capped])

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
            "total_views": len(views),
            "confirmed_views": len(confirmed_views),
            "pending_views": len(pending_views),
            "daily_capped_views": daily_capped_views,
            "estimated_pending_amount": round(len(pending_views) * self.cpm_setting.current_cpm, 6),
        }

    async def list_balance_adjustments(self, telegram_id: int, limit: int = 20) -> List[dict]:
        entries = [
            e.model_dump()
            for e in self.cpm_history
            if e.event == "balance_adjustment" and e.detail.get("telegram_id") == telegram_id
        ]
        entries.sort(key=lambda e: e["created_at"], reverse=True)
        return entries[:limit]
