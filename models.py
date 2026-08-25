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


class AdNetwork(str, Enum):
    ADSGRAM = "adsgram"
    MONETAG = "monetag"
    GIGAPUB = "gigapub"


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

    # Which PolicySetting.version this Admin last tapped "Accept" on (see
    # PolicySetting below). 0 means "never accepted anything" — a brand
    # new Admin. Whenever the Owner edits the policy text, its version
    # increments, which makes every existing Admin's stored value stale
    # again until they accept the new text too (bot.py's PolicyGate
    # re-prompts on their next interaction).
    policy_accepted_version: int = 0
    policy_accepted_at: Optional[str] = None


class Link(BaseModel):
    """`ad_count` used to independently control how many ads a viewer
    watched (cycling through AdNetworkSetting.slot_sequence to fill it).
    It's kept here for backward compatibility and historical stats, but
    the actual number of ads shown to a viewer is now simply
    `len(AdNetworkSetting.slot_sequence)` — see that field's docstring.
    The Owner-only per-link override (storage.set_link_ad_count / POST
    /api/admin/links/{short_code}/ad-count) still exists but no longer
    changes what a viewer experiences.
    """

    short_code: str
    owner_telegram_id: int
    destination_url: str
    ad_count: int = 3
    created_at: str = Field(default_factory=now_iso)


class View(BaseModel):
    """One row per completed ad-viewing (the number of ads is the
    owning Link's `ad_count`, not a fixed count — see Link.ad_count).

    `credited_amount` is filled in the moment this view's status becomes
    CONFIRMED — immediately in Real-time mode, or at cycle-close time in
    Scheduled mode (since the PRD's no-retroactive-rate-splitting rule
    means the rate isn't known until the cycle actually closes). It's
    None for a still-pending view. This is what lets the Owner's
    per-Admin stats (today's income, lifetime income) be reconstructed
    accurately after the fact, instead of only ever knowing the current
    balance total.

    `daily_capped` is set once, by cpm_engine.credit_new_view, when this
    view is the one that crosses the Admin's daily anti-abuse limit
    (CPMSetting.max_daily_views_per_admin) for its viewer. The viewer
    still watches every ad as normal; this view is simply routed
    straight to CONFIRMED with `credited_amount = 0` instead of adding to
    anyone's balance, so a viewer hammering one Admin's links repeatedly
    in a day can't keep dragging that Admin's CPM down.
    """

    view_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    short_code: str
    viewer_telegram_id: int
    counted_status: CountedStatus = CountedStatus.PENDING_PAYOUT
    cpm_cycle_id: Optional[str] = None
    credited_amount: Optional[float] = None
    credited_at: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    daily_capped: bool = False


class CPMSetting(BaseModel):
    """Single active record. `cycle_id` is an implementation addition (not
    spelled out verbatim in the PRD JSON shape) so that View.cpm_cycle_id
    can unambiguously reference exactly which scheduled cycle a view
    belongs to.

    `ad_view_delay_seconds` is a platform-wide UX setting (not a CPM/payout
    concept) piggybacked on this same record since it already lives behind
    the Owner's CPM Settings screen: Adsgram doesn't have the next reward
    ad ready the instant one finishes, so `webapp/viewer.html` pauses this
    many seconds between ad N finishing and ad N+1 becoming tappable.

    `min_withdraw_amount` is likewise platform-wide, Owner-only config with
    nowhere else to sit: the smallest confirmed-balance amount an Admin is
    allowed to request as a withdrawal. Both `/withdraw` in the bot and the
    panel's withdrawal form reject a request below this amount before it's
    ever created.

    `max_daily_views_per_admin` is the Anti-Abuse System's cap: the most
    views a single viewer can have *credited* against one Admin's links
    per calendar day (UTC, same convention `admin_stats` already uses for
    "today's income"). `0` means no cap. Once a viewer crosses it,
    cpm_engine.credit_new_view still lets every further view play its 3
    ads and reach the destination as normal — it just stops adding to
    that Admin's balance, marking the view `daily_capped` instead, so a
    single viewer re-opening many of one Admin's links in a day can't
    keep dragging that Admin's CPM down.
    """

    mode: CPMMode = CPMMode.REALTIME
    current_cpm: float = 0.5
    cycle_duration_hours: float = 24
    cycle_started_at: str = Field(default_factory=now_iso)
    cycle_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ad_view_delay_seconds: float = 7
    min_withdraw_amount: float = 0
    max_daily_views_per_admin: int = 0
    updated_at: str = Field(default_factory=now_iso)
    updated_by: Optional[int] = None


class AdNetworkSetting(BaseModel):
    """Single active record (same one-row pattern as CPMSetting /
    PolicySetting) holding every ad network's credentials plus the
    per-slot network sequence `webapp/viewer.html` follows when playing
    back a Link's `ad_count` ads.

    Each network's credentials are independent and optional — the Owner
    can fill in just Adsgram, just Monetag, just GigaPub, or any mix,
    and only reference the ones actually configured in `slot_sequence`.
    A slot pointed at a network with no ID filled in simply fails to
    load for the viewer, surfacing as the same "ad didn't load, try
    again" state the app already shows for any other ad-load failure —
    there's no separate validation blocking that combination.

    `monetag_sdk_url` is the full `<script src="...">` URL copied from
    the Monetag dashboard's "Get SDK" tag for this zone, not just a
    domain — Monetag personalizes this domain per publisher/zone for
    anti-adblock reasons, so there's no single fixed URL this platform
    could default to (see README's "Ad networks" section).

    `slot_sequence` is an ordered list of AdNetwork values, one per ad
    position (Ad 1, Ad 2, Ad 3, ...). This list's length *is* how many
    ads every link on the platform makes a viewer watch — Ad1, then
    Ad2, and so on down to the last slot the Owner has added, with no
    padding or repeating. A single-entry sequence means every link is a
    one-ad unlock; a three-entry sequence means every link is a
    three-ad unlock. Defaults to three Adsgram slots, matching the
    platform's original fixed single-network behavior.
    """

    adsgram_block_id: str = ""
    monetag_zone_id: str = ""
    monetag_sdk_url: str = ""
    gigapub_project_id: str = ""
    slot_sequence: list[AdNetwork] = Field(
        default_factory=lambda: [AdNetwork.ADSGRAM, AdNetwork.ADSGRAM, AdNetwork.ADSGRAM]
    )
    updated_at: str = Field(default_factory=now_iso)
    updated_by: Optional[int] = None


DEFAULT_POLICY_TEXT = (
    "১. ফেক/বট ট্রাফিক ব্যবহার করলে সাথে সাথে অ্যাকাউন্ট ব্যান করা হবে।\n\n"
    "২. আপনার ট্রাফিক সোর্স অবশ্যই ১০০% নিজের ও অরিজিনাল হতে হবে। কোনো পেমেন্ট "
    "দেওয়ার আগে অ্যাডমিন নিজে যাচাই-বাছাই করে তবেই পেমেন্ট করবে।\n\n"
    "৩. অন্য কারো প্রাইভেট/কপিরাইটেড মুভি বা এমন কোনো কনটেন্ট যা পাবলিকলি শেয়ার "
    "করা বৈধ নয়, এবং যেকোনো ধরনের মড (Mod) APK শেয়ার করা সম্পূর্ণভাবে ব্যবহারকারীর "
    "নিজস্ব দায়িত্ব — এর জন্য বটের মালিক বা কোম্পানি কোনোভাবেই দায়ী থাকবে না।\n\n"
    "৪. Adult/প্রাপ্তবয়স্ক কনটেন্ট এই প্ল্যাটফর্মে সম্পূর্ণভাবে নিষিদ্ধ।\n\n"
    "চালিয়ে যেতে হলে এই শর্তাবলীতে সম্মতি জানাতে হবে।"
)


class PolicySetting(BaseModel):
    """Single active record (same one-row pattern as CPMSetting) holding
    the Owner-editable policy text every user must accept before using
    the bot (see bot.py's PolicyGateMiddleware + the /api/admin/policy
    endpoints in app.py, and the panel's Policy settings card).

    `version` starts at 1 and is incremented by storage.update_policy_text
    every time the Owner changes `text` — bumping it is what makes every
    Admin's previously-stored `policy_accepted_version` stale again, so
    they're re-prompted with the new text on their next interaction
    rather than being silently grandfathered in under the old one.
    """

    version: int = 1
    text: str = DEFAULT_POLICY_TEXT
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
