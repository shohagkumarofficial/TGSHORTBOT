"""CPM engine — two modes (PRD §4.5).

Mode A (realtime): every verified view is credited immediately at the
current CPM rate.

Mode B (scheduled): verified views are accumulated as pending_payout
until the current cycle ends; on cycle close, the CPM rate that is set
at that exact moment is applied to all pending views in the cycle.

Cycle close is checked lazily: we look at the CPM setting on every
relevant write, plus a periodic background tick. We don't trust the
caller to remember to call close_cycle().
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from models import CPMMode, CPMSetting, ViewCountedStatus, VerificationStatus  # noqa: F401

if TYPE_CHECKING:
    import storage as storage_mod


def per_view_credit(cpm: CPMSetting) -> float:
    """BDT credited for a single countable view."""
    return cpm.current_cpm / 1000.0


def classify_view(cpm: CPMSetting) -> ViewCountedStatus:
    """Initial counted_status for a fresh view, before link verification."""
    # link is unverified at this point — caller will move it once
    # the Owner verifies the link. We return UNVERIFIED here and let
    # on_link_verified() decide the next state.
    return ViewCountedStatus.UNVERIFIED


async def on_link_verified(short_code: str) -> None:
    """Called when Owner marks a link VERIFIED.

    Move all UNVERIFIED views for that link into either CONFIRMED
    (realtime) or PENDING_PAYOUT (scheduled).
    """
    import storage as storage_mod
    s = storage_mod.get_store()
    link = s.links.get(short_code)
    if not link:
        return
    cpm = s.cpm
    new_status = (
        ViewCountedStatus.CONFIRMED
        if cpm.mode == CPMMode.REALTIME
        else ViewCountedStatus.PENDING_PAYOUT
    )
    for v in s.views.values():
        if v.short_code == short_code and v.counted_status == ViewCountedStatus.UNVERIFIED:
            v.counted_status = new_status
            if new_status == ViewCountedStatus.CONFIRMED:
                admin = s.admins.get(str(link.owner_telegram_id))
                if admin:
                    admin.balance_confirmed += per_view_credit(cpm)
                    storage_mod.audit(
                        "credit_realtime",
                        view_id=v.view_id,
                        admin_id=admin.telegram_id,
                        amount=per_view_credit(cpm),
                    )


async def close_cycle_if_due() -> bool:
    """If the scheduled CPM cycle is past its duration, close it.

    Returns True if a cycle was closed. Safe to call from any request
    handler or background task — it's idempotent w.r.t. an in-flight close.
    """
    import storage as storage_mod
    s = storage_mod.get_store()
    cpm = s.cpm
    if cpm.mode != CPMMode.SCHEDULED:
        return False
    due_at = cpm.cycle_started_at + timedelta(hours=cpm.cycle_duration_hours)
    if datetime.utcnow() < due_at:
        return False

    # Credit all pending_payout views in the closing cycle.
    closing_cycle_id = cpm.cycle_id
    per_view = per_view_credit(cpm)
    credited_per_admin: dict[int, float] = {}
    for v in s.views.values():
        if v.counted_status == ViewCountedStatus.PENDING_PAYOUT and v.cpm_cycle_id == closing_cycle_id:
            link = s.links.get(v.short_code)
            if not link:
                continue
            admin = s.admins.get(str(link.owner_telegram_id))
            if not admin:
                continue
            credited_per_admin[admin.telegram_id] = (
                credited_per_admin.get(admin.telegram_id, 0.0) + per_view
            )
            v.counted_status = ViewCountedStatus.CONFIRMED
    for admin_id, amount in credited_per_admin.items():
        admin = s.admins.get(str(admin_id))
        if admin:
            admin.balance_confirmed += amount

    storage_mod.audit(
        "cycle_closed",
        cycle_id=closing_cycle_id,
        per_view=per_view,
        credited=credited_per_admin,
    )

    # Open the next cycle with the same duration and the latest CPM value
    # (PRD §4.5: "the CPM value set at that exact moment is applied to
    # all views accumulated during the entire period"). Rate carries over
    # until Owner changes it again.
    from models import CPMSetting
    s.cpm = CPMSetting(
        mode=cpm.mode,
        current_cpm=cpm.current_cpm,
        cycle_duration_hours=cpm.cycle_duration_hours,
        cycle_started_at=datetime.utcnow(),
        cycle_id=storage_mod._id(),
        updated_at=cpm.updated_at,
        updated_by=cpm.updated_by,
    )
    await storage_mod.save()
    return True


async def cycle_tick_loop() -> None:
    """Background coroutine: tick every minute, close any due cycle.

    Started once during FastAPI startup. Sleep loop is forgiving of
    Render's free-tier sleep (it just resumes on the next request tick).
    """
    import asyncio
    import storage as storage_mod
    while True:
        try:
            await close_cycle_if_due()
        except Exception:
            # never let the tick loop die
            pass
        await asyncio.sleep(60)
