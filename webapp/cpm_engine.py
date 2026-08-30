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

from models import CountedStatus, CPMHistoryEntry, CPMMode, Link, View, effective_cpm, now_iso
from storage import Storage

logger = logging.getLogger("cpm_engine")


def _is_daily_capped(storage: Storage, view: View, link: Link, max_daily_views: int) -> bool:
    """Anti-Abuse System check (see CPMSetting.max_daily_views_per_admin).

    Counts how many *other* views this same viewer already has logged
    today against this same Admin's links (across every link the Admin
    owns, not just this one — a viewer could otherwise dodge the cap by
    spreading views across several of the Admin's links) and reports
    whether the view being credited right now would be the one that
    crosses the limit. Already-capped views don't count toward this
    tally, since they never earned anything to begin with.

    Must be called with `storage._lock` already held, so the count and
    the crediting decision that follows it are atomic — otherwise two
    views logged in the same instant could each see a count just under
    the limit and both get credited, letting the cap slip by one.
    """
    today = datetime.now(timezone.utc).date()
    counted_today = 0
    for other in storage.views.values():
        if other.view_id == view.view_id or other.daily_capped:
            continue
        if other.viewer_telegram_id != view.viewer_telegram_id:
            continue
        other_link = storage.links.get(other.short_code)
        if not other_link or other_link.owner_telegram_id != link.owner_telegram_id:
            continue
        created = datetime.fromisoformat(other.created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created.astimezone(timezone.utc).date() == today:
            counted_today += 1
    return counted_today >= max_daily_views


async def credit_new_view(storage: Storage, view: View, link: Link) -> None:
    """Call right after a View row is created. Credits it immediately
    (Real-time mode) or queues it for the current cycle (Scheduled mode)
    — unless the viewer has already hit this Admin's daily anti-abuse
    view cap today, in which case the view is logged as watched (the
    viewer's ads still played and Adsgram still paid out) but earns
    nothing.
    """
    cpm_setting = await storage.get_cpm_setting()
    async with storage._lock:
        max_daily_views = cpm_setting.max_daily_views_per_admin
        if max_daily_views > 0 and _is_daily_capped(storage, view, link, max_daily_views):
            view.counted_status = CountedStatus.CONFIRMED
            view.credited_amount = 0.0
            view.credited_at = now_iso()
            view.daily_capped = True
        elif cpm_setting.mode == CPMMode.REALTIME:
            admin = storage.admins.get(link.owner_telegram_id)
            rate = effective_cpm(admin, cpm_setting) if admin else cpm_setting.current_cpm
            if admin:
                admin.balance_confirmed = round(admin.balance_confirmed + rate, 6)
            view.counted_status = CountedStatus.CONFIRMED
            view.cpm_cycle_id = cpm_setting.cycle_id
            view.credited_amount = rate
            view.credited_at = now_iso()
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
        platform_rate = cs.current_cpm
        payouts_by_admin: dict[str, float] = {}
        views_paid = 0
        paid_at = now_iso()

        for v in storage.views.values():
            if v.counted_status != CountedStatus.PENDING_PAYOUT or v.cpm_cycle_id != closing_cycle_id:
                continue
            link = storage.links.get(v.short_code)
            if not link:
                continue
            admin = storage.admins.get(link.owner_telegram_id)
            # Each view is priced at whatever rate is active *for that
            # Admin* right now — their own Sub Admin CPM override, then
            # their role's platform-wide rate, then the base rate — never
            # a per-day split of rates that changed mid-cycle, per the
            # PRD's no-retroactive-rate-splitting rule.
            rate = effective_cpm(admin, cs) if admin else platform_rate
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
            v.credited_amount = rate
            v.credited_at = paid_at
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

    logger.info(
        "Closed CPM cycle %s: %d views paid (platform rate %s, per-Sub-Admin overrides may differ)",
        closing_cycle_id, views_paid, platform_rate,
    )
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


async def run_link_expiry_watcher(storage: Storage, interval_seconds: int = 3600) -> None:
    """Background loop for the Sub Admin link auto-delete feature:
    periodically purges every Link whose `expires_at` has passed (see
    storage.purge_expired_links / Admin.link_auto_delete_months). Runs
    for the lifetime of the app, started alongside run_cpm_cycle_watcher
    in app.py's lifespan. Defaults to hourly since link expiry windows
    are measured in months, not seconds — no need to poll as tightly as
    the CPM cycle watcher does.
    """
    while True:
        try:
            purged = await storage.purge_expired_links()
            if purged:
                logger.info("Purged %d auto-expired link(s)", purged)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("link expiry watcher tick failed")
        await asyncio.sleep(interval_seconds)
