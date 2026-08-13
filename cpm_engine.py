import logging
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from models import View, Link, Admin, CPMSetting, CPMAuditLog
from storage import Storage

logger = logging.getLogger(__name__)

class CPMEngine:
    """
    CPM calculation and payout engine.
    """
    def __init__(self, storage: Storage):
        self.storage = storage
        self._ensure_settings()

    def _ensure_settings(self):
        """Ensure global settings exist, create defaults if not."""
        settings = self.storage.get_cpm_setting()
        if not settings:
            logger.info("Initializing default CPM settings.")
            # Default owner_id to 0 for initial setup
            self.storage.init_cpm_setting(0)

    def process_view(self, view: View, link: Link) -> float:
        """
        Process a new view. Returns earned amount (0 if not applicable).
        If real-time mode and link is verified: credit immediately.
        If scheduled mode and link is verified: mark as pending_payout.
        If link is not verified: mark as unverified (no earning yet).
        """
        if view.counted_status in ('confirmed', 'pending_payout', 'rejected'):
            # Already processed or counted
            return 0.0

        if link.verification_status != 'verified':
            self.storage.update_view_status(view.view_id, 'unverified', 0.0)
            return 0.0

        settings = self.storage.get_cpm_setting()
        if not settings:
            return 0.0
        
        if settings.mode == 'realtime':
            earned_amount = settings.current_cpm / 1000.0
            
            # Credit Admin
            self.storage.credit_admin_balance(link.owner_telegram_id, earned_amount, 'confirmed')
            
            self.storage.update_view_status(view.view_id, 'confirmed', earned_amount)
            return earned_amount
            
        elif settings.mode == 'scheduled':
            self.storage.update_view_status(view.view_id, 'pending_payout', 0.0)
            return 0.0
            
        return 0.0

    def on_link_verified(self, short_code: str):
        """
        Called when Owner verifies a link. Updates all unverified views for this link.
        In real-time mode: credits them immediately.
        In scheduled mode: marks them as pending_payout.
        """
        self.storage.verify_link(short_code, 'verified')
        link = self.storage.get_link(short_code)
        if not link:
            return

        views = self.storage.get_views_by_link(short_code)
        unverified_views = [v for v in views if v.counted_status == 'unverified']
        if not unverified_views:
            return

        settings = self.storage.get_cpm_setting()
        if not settings:
            return

        for view in unverified_views:
            if settings.mode == 'realtime':
                earned_amount = settings.current_cpm / 1000.0
                self.storage.credit_admin_balance(link.owner_telegram_id, earned_amount, 'confirmed')
                self.storage.update_view_status(view.view_id, 'confirmed', earned_amount)
            elif settings.mode == 'scheduled':
                self.storage.update_view_status(view.view_id, 'pending_payout', 0.0)

    def on_link_rejected(self, short_code: str):
        """Called when Owner rejects a link. Marks all unverified views for this link as rejected."""
        self.storage.verify_link(short_code, 'rejected')
        views = self.storage.get_views_by_link(short_code)
        for view in views:
            if view.counted_status == 'unverified':
                self.storage.update_view_status(view.view_id, 'rejected', 0.0)

    async def check_and_process_cycle(self):
        """Background task: checks if current scheduled cycle has ended, processes payout if so."""
        settings = self.storage.get_cpm_setting()
        if not settings or settings.mode != 'scheduled':
            return

        now = datetime.now(timezone.utc)
        cycle_end_time = settings.cycle_started_at + timedelta(hours=settings.cycle_duration_hours)
        
        if now >= cycle_end_time:
            old_cycle_id = str(settings.cycle_id)
            logger.info(f"Processing cycle {old_cycle_id}")
            self._process_payout_for_cycle(old_cycle_id, settings.current_cpm)
            
            # Start new cycle
            settings.cycle_id = uuid.uuid4()
            settings.cycle_started_at = now
            settings.updated_at = now
            settings.updated_by = 0
            self.storage.update_cpm_setting(settings)
            
            # Log audit
            audit = CPMAuditLog(
                event_type="cycle_payout",
                details={
                    "old_cycle_id": old_cycle_id,
                    "new_cycle_id": str(settings.cycle_id),
                    "message": f"Cycle {old_cycle_id} ended. Processed payouts at CPM ${settings.current_cpm:.2f}."
                },
                timestamp=now,
                triggered_by=0
            )
            self.storage.add_audit_log(audit)

    def _process_payout_for_cycle(self, cycle_id: str, cpm: float):
        """Processes the actual payout for all pending views of a cycle."""
        views = self.storage.get_pending_payout_views(cycle_id)
        if not views:
            logger.info(f"No pending views for cycle {cycle_id}")
            return

        earned_amount = cpm / 1000.0
        for view in views:
            link = self.storage.get_link(view.short_code)
            if link:
                self.storage.credit_admin_balance(link.owner_telegram_id, earned_amount, 'confirmed')
            
            self.storage.update_view_status(view.view_id, 'confirmed', earned_amount)
        
        logger.info(f"Processed {len(views)} views for cycle {cycle_id} at ${cpm} CPM.")

    def get_cycle_info(self) -> Dict[str, Any]:
        """Returns current cycle info: time remaining, pending view count, mode."""
        settings = self.storage.get_cpm_setting()
        if not settings:
            return {}
            
        info = {
            "mode": settings.mode,
            "cpm": settings.current_cpm,
        }
        
        if settings.mode == 'scheduled':
            now = datetime.now(timezone.utc)
            cycle_end_time = settings.cycle_started_at + timedelta(hours=settings.cycle_duration_hours)
            time_remaining = max(0.0, (cycle_end_time - now).total_seconds())
            
            pending_views = self.storage.get_views_by_status('pending_payout')
            
            info.update({
                "cycle_id": str(settings.cycle_id),
                "time_remaining_seconds": time_remaining,
                "pending_views": len(pending_views)
            })
            
        return info

    def change_cpm_rate(self, new_rate: float, owner_id: int):
        """Owner changes CPM rate. Logs audit event."""
        settings = self.storage.get_cpm_setting()
        if not settings:
            return
            
        old_rate = settings.current_cpm
        settings.current_cpm = new_rate
        settings.updated_at = datetime.now(timezone.utc)
        settings.updated_by = owner_id
        self.storage.update_cpm_setting(settings)
        
        audit = CPMAuditLog(
            event_type="cpm_change",
            details={
                "old_rate": old_rate,
                "new_rate": new_rate,
                "message": f"CPM rate changed from {old_rate} to {new_rate}"
            },
            timestamp=datetime.now(timezone.utc),
            triggered_by=owner_id
        )
        self.storage.add_audit_log(audit)
        logger.info(f"CPM changed to {new_rate} by Owner {owner_id}")

    def change_mode(self, new_mode: str, owner_id: int, cycle_duration_hours: int = 24):
        """
        Owner switches between realtime and scheduled mode. Logs audit event.
        If switching to scheduled: starts a new cycle.
        If switching to realtime: processes any pending_payout views immediately at current rate.
        """
        if new_mode not in ['realtime', 'scheduled']:
            raise ValueError("Mode must be 'realtime' or 'scheduled'")
            
        settings = self.storage.get_cpm_setting()
        if not settings:
            return
            
        old_mode = settings.mode
        
        if old_mode == new_mode:
            return

        now = datetime.now(timezone.utc)
        settings.mode = new_mode
        settings.updated_at = now
        settings.updated_by = owner_id
        
        if new_mode == 'scheduled':
            settings.cycle_started_at = now
            settings.cycle_id = uuid.uuid4()
            settings.cycle_duration_hours = cycle_duration_hours
        elif new_mode == 'realtime':
            # Process all pending_payout views immediately
            pending_views = self.storage.get_views_by_status('pending_payout')
            earned_amount = settings.current_cpm / 1000.0
            
            for view in pending_views:
                link = self.storage.get_link(view.short_code)
                if link:
                    self.storage.credit_admin_balance(link.owner_telegram_id, earned_amount, 'confirmed')
                
                self.storage.update_view_status(view.view_id, 'confirmed', earned_amount)

        self.storage.update_cpm_setting(settings)
        
        audit = CPMAuditLog(
            event_type="mode_change",
            details={
                "old_mode": old_mode,
                "new_mode": new_mode,
                "message": f"Mode changed from {old_mode} to {new_mode}"
            },
            timestamp=now,
            triggered_by=owner_id
        )
        self.storage.add_audit_log(audit)
        logger.info(f"CPM mode changed to {new_mode} by Owner {owner_id}")


async def start_cpm_background_task(engine: CPMEngine):
    """
    Background task running an infinite loop checking 
    check_and_process_cycle() every 60 seconds.
    """
    logger.info("Starting CPM background check task.")
    while True:
        try:
            await engine.check_and_process_cycle()
        except Exception as e:
            logger.error(f"Error in CPM background task: {e}", exc_info=True)
        await asyncio.sleep(60)
