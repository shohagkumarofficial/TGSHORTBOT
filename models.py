"""Pydantic models — mirror the JSON shapes in PRD §9.3.

Same shapes will carry over to SQLite later; the storage layer hides the
backend behind a small interface.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --- enums ----------------------------------------------------------------

class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"


class AdminStatus(str, Enum):
    ACTIVE = "active"
    BANNED = "banned"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ViewCountedStatus(str, Enum):
    UNVERIFIED = "unverified"       # link not yet verified by Owner
    PENDING_PAYOUT = "pending_payout"  # verified link, waiting for CPM cycle close (Scheduled mode)
    CONFIRMED = "confirmed"         # credited to admin balance
    REJECTED = "rejected"           # link later rejected; view discarded


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


# --- entities -------------------------------------------------------------

class Admin(BaseModel):
    telegram_id: int
    username: str = ""
    role: Role = Role.ADMIN
    balance_confirmed: float = 0.0
    balance_pending: float = 0.0
    created_at: datetime
    status: AdminStatus = AdminStatus.ACTIVE


class Link(BaseModel):
    short_code: str
    owner_telegram_id: int
    destination_url: str
    proof_url: Optional[str] = None
    verification_status: VerificationStatus = VerificationStatus.PENDING
    created_at: datetime


class View(BaseModel):
    view_id: str
    short_code: str
    viewer_telegram_id: int
    counted_status: ViewCountedStatus = ViewCountedStatus.UNVERIFIED
    cpm_cycle_id: Optional[str] = None
    created_at: datetime


class CPMSetting(BaseModel):
    mode: CPMMode = CPMMode.REALTIME
    current_cpm: float = 0.0  # BDT per 1000 views
    cycle_duration_hours: int = 24
    cycle_started_at: datetime = Field(default_factory=datetime.utcnow)
    cycle_id: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: int = 0


class WithdrawRequest(BaseModel):
    request_id: str
    admin_telegram_id: int
    amount: float
    method: WithdrawMethod
    account_number: str
    status: WithdrawStatus = WithdrawStatus.PENDING
    created_at: datetime
    resolved_at: Optional[datetime] = None
    note: Optional[str] = None


class Store(BaseModel):
    """Top-level JSON document persisted to disk."""
    admins: dict[str, Admin] = Field(default_factory=dict)        # key = telegram_id (str)
    links: dict[str, Link] = Field(default_factory=dict)         # key = short_code
    views: dict[str, View] = Field(default_factory=dict)         # key = view_id
    withdrawals: dict[str, WithdrawRequest] = Field(default_factory=dict)  # key = request_id
    cpm: CPMSetting = Field(default_factory=CPMSetting)
    audit_log: list[dict] = Field(default_factory=list)
