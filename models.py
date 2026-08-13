from datetime import datetime, timezone
from typing import Literal, Optional, Dict, Any
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

class Admin(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    full_name: str
    role: Literal["owner", "admin"]
    balance_confirmed: float = 0.0
    balance_pending: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["active", "banned"] = "active"
    model_config = ConfigDict(populate_by_name=True)

class Link(BaseModel):
    short_code: str
    owner_telegram_id: int
    destination_url: str
    proof_url: Optional[str] = None
    verification_status: Literal["pending", "verified", "rejected"] = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_config = ConfigDict(populate_by_name=True)

class View(BaseModel):
    view_id: UUID = Field(default_factory=uuid4)
    short_code: str
    viewer_telegram_id: int
    counted_status: Literal["unverified", "pending_payout", "confirmed", "rejected"] = "unverified"
    cpm_cycle_id: Optional[str] = None
    earned_amount: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_config = ConfigDict(populate_by_name=True)

class CPMSetting(BaseModel):
    mode: Literal["realtime", "scheduled"] = "scheduled"
    current_cpm: float = 0.50
    cycle_duration_hours: int = 24
    cycle_started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cycle_id: UUID = Field(default_factory=uuid4)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: int
    model_config = ConfigDict(populate_by_name=True)

class WithdrawRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    admin_telegram_id: int
    amount: float
    method: Literal["bkash", "nagad"]
    account_number: str
    status: Literal["pending", "paid", "rejected"] = "pending"
    reject_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    model_config = ConfigDict(populate_by_name=True)

class CPMAuditLog(BaseModel):
    event_type: Literal["cpm_change", "cycle_payout", "mode_change"]
    details: Dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    triggered_by: int
    model_config = ConfigDict(populate_by_name=True)
