"""Data models for TGSHORTBOT.

These mirror the JSON shapes in PRD Section 9.3 exactly, so the same
models can be reused unchanged when storage.py is swapped from JSON to
SQLite/Postgres later.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"


class AdminStatus(str, Enum):
    ACTIVE = "active"
    BANNED = "banned"


class CountedStatus(str, Enum):
    """A view is routed straight into one of these two states the instant
    it's logged (see cpm_engine.credit_new_view) — there is no longer a
    per-link "unverified" holding state. The human review step now
    happens once per Admin, at Traffic Source level, and again by the
    Owner at withdrawal time — not per link.
    """

    PENDING_PAYOUT = "pending_payout"
    CONFIRMED = "confirmed"


class CPMMode(str, Enum):
    REALTIME = "realtime"
    SCHEDULED = "scheduled"


class WithdrawMethod(str, Enum):
    BKASH = "bkash"
    NAGAD = "nagad"


class WithdrawStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    REJECTED = "rejected"


class TrafficSource(BaseModel):
    """One place this Admin brings viewers from (e.g. a Telegram channel
    or a YouTube channel link). An Admin can hold several of these at
    once — one per platform, or several on the same platform — and can
    add, edit, or remove any of them at any time via `/trafficsource` or
    the panel's Traffic Source tab. At least one is required before an
    Admin can create any links; the whole list is shown to the Owner
    alongside withdrawal requests so the Owner can judge where the
    traffic is really coming from.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    platform: str
    url: str
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class Admin(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    role: Role = Role.ADMIN
    balance_confirmed: float = 0.0
    balance_pending: float = 0.0
    created_at: str = Field(default_factory=now_iso)
    status: AdminStatus = AdminStatus.ACTIVE

    traffic_sources: list[TrafficSource] = Field(default_factory=list)


class Link(BaseModel):
    short_code: str
    owner_telegram_id: int
    destination_url: str
    created_at: str = Field(default_factory=now_iso)


class View(BaseModel):
    """One row per completed 3-ad viewing."""

    view_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    short_code: str
    viewer_telegram_id: int
    counted_status: CountedStatus = CountedStatus.PENDING_PAYOUT
    cpm_cycle_id: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class CPMSetting(BaseModel):
    """Single active record. `cycle_id` is an implementation addition (not
    spelled out verbatim in the PRD JSON shape) so that View.cpm_cycle_id
    can unambiguously reference exactly which scheduled cycle a view
    belongs to.
    """

    mode: CPMMode = CPMMode.REALTIME
    current_cpm: float = 0.5
    cycle_duration_hours: float = 24
    cycle_started_at: str = Field(default_factory=now_iso)
    cycle_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    updated_at: str = Field(default_factory=now_iso)
    updated_by: Optional[int] = None


class CPMHistoryEntry(BaseModel):
    """Audit trail entry — every CPM change and payout event (NFR in
    Section 6)."""

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event: str  # "cpm_change" | "cycle_payout" | "traffic_source_change"
    detail: dict
    created_at: str = Field(default_factory=now_iso)


class WithdrawRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    admin_telegram_id: int
    amount: float
    method: WithdrawMethod
    account_number: str
    status: WithdrawStatus = WithdrawStatus.PENDING
    created_at: str = Field(default_factory=now_iso)
    resolved_at: Optional[str] = None
    reject_reason: Optional[str] = None
