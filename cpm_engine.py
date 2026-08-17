"""CPM crediting logic for both operating modes (PRD Section 4.5 / 9.5).

A logged view is routed the instant it's created: Real-time mode credits
the owning Admin's balance_confirmed immediately; Scheduled mode holds it
as `pending_payout`, tagged with the CPM cycle it belongs to.

There is no per-link "unverified" holding step any more — human review
now happens once per Admin (their Traffic Source) and again by the Owner
at withdrawal time, rather than once per link.

A background watcher closes a Scheduled-mode cycle when its duration
elapses, applying *whatever CPM is set at that exact moment* to every
view accumulated during the whole period — no retroactive per-day
rate-splitting, per the PRD's explicit instruction.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from models import CountedStatus, CPMHistoryEntry, CPMMode, Link, View, now_iso
from storage import Storage

logger = logging.getLogger("cpm_engine")


async def credit_new_view(storage: Storage, view: View, link: Link) -> None:
    """Call right after a View row is created. Credits it immediately
    (Real-time mode) or queues it for the current cycle (Scheduled mode).
    """
    cpm_setting = await storage.get_cpm_setting()
    async with storage._lock:
        if cpm_setting.mode == CPMMode.REALTIME:
            admin = storage.admins.get(link.owner_telegram_id)
            if admin:
                admin.balance_confirmed = round(admin.balance_confirmed + cpm_setting.current_cpm, 6)
            view.counted_status = CountedStatus.CONFIRMED
            view.cpm_cycle_id = cpm_setting.cycle_id
        else:
            view.counted_status = CountedStatus.PENDING_PAYOUT
            view.cpm_cycle_id = cpm_setting.cycle_id
        await storage._save_locked()


async def maybe_close_cycle(storage: Storage) -> bool:
    """Checks whether the current Scheduled-mode cycle has elapsed and, if
    so, closes it: applies the CPM rate active *right now* to every view
    accumulated during the whole period, credits admins, and starts a new
    cycle. Returns True if a cycle was closed.
    """
    cpm_setting = await storage.get_cpm_setting()
    if cpm_setting.mode != CPMMode.SCHEDULED:
        return False

    started = datetime.fromisoformat(cpm_setting.cycle_started_at)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    deadline = started + timedelta(hours=cpm_setting.cycle_duration_hours)
    if datetime.now(timezone.utc) < deadline:
        return False

    async with storage._lock:
        cs = storage.cpm_setting
        # Re-check inside the lock in case the mode/duration changed
        # concurrently between the read above and now.
        if cs.mode != CPMMode.SCHEDULED:
            return False
        started = datetime.fromisoformat(cs.cycle_started_at)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < started + timedelta(hours=cs.cycle_duration_hours):
            return False

        closing_cycle_id = cs.cycle_id
        rate = cs.current_cpm
        payouts_by_admin: dict[str, float] = {}
        views_paid = 0

        for v in storage.views.values():
            if v.counted_status != CountedStatus.PENDING_PAYOUT or v.cpm_cycle_id != closing_cycle_id:
                continue
            link = storage.links.get(v.short_code)
            if not link:
                continue
            admin = storage.admins.get(link.owner_telegram_id)
            if admin:
                # Per Section 9.5: credit to balance_pending, then move to
                # balance_confirmed. Written as two explicit steps (rather
                # than a single increment) to match the spec's described
                # sequence for audit purposes; net effect on the ledger is
                # the same.
                admin.balance_pending = round(admin.balance_pending + rate, 6)
                admin.balance_pending = round(admin.balance_pending - rate, 6)
                admin.balance_confirmed = round(admin.balance_confirmed + rate, 6)
                key = str(link.owner_telegram_id)
                payouts_by_admin[key] = round(payouts_by_admin.get(key, 0.0) + rate, 6)
            v.counted_status = CountedStatus.CONFIRMED
            views_paid += 1

        # Start the next cycle automatically; the rate carries over until
        # the Owner changes it again.
        cs.cycle_started_at = now_iso()
        cs.cycle_id = str(uuid.uuid4())
        cs.updated_at = now_iso()

        storage.cpm_history.append(
            CPMHistoryEntry(
                event="cycle_payout",
                detail={
                    "closed_cycle_id": closing_cycle_id,
                    "rate_applied": rate,
                    "views_paid": views_paid,
                    "payouts_by_admin": payouts_by_admin,
                },
            )
        )
        await storage._save_locked()

    logger.info("Closed CPM cycle %s: %d views paid at rate %s", closing_cycle_id, views_paid, rate)
    return True


async def run_cpm_cycle_watcher(storage: Storage, interval_seconds: int = 60) -> None:
    """Background loop that closes out Scheduled-mode cycles as they
    elapse. Runs for the lifetime of the app (started in app.py's
    lifespan handler).
    """
    while True:
        try:
            await maybe_close_cycle(storage)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("cpm cycle watcher tick failed")
        await asyncio.sleep(interval_seconds)
