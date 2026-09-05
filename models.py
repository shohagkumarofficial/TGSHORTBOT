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


def effective_cpm(admin: "Admin", cpm_setting: "CPMSetting") -> float:
    """The CPM rate that actually applies when crediting one of this
    Admin's views, checked in priority order:

      1. `Admin.sub_admin_cpm` — this specific Sub Admin's own override
         (storage.set_sub_admin_cpm), if the Owner set one for them
         individually.
      2. `CPMSetting.admin_cpm` / `CPMSetting.sub_admin_cpm` — the
         platform-wide rate for their *role*, if the Owner set one on
         the CPM Settings screen (storage.update_cpm_setting).
      3. `CPMSetting.current_cpm` — the platform's base rate, used for
         any role with nothing more specific configured (including the
         Owner's own links, if any).

    Shared by cpm_engine.py (crediting) and storage.admin_stats (the
    Owner's pending-earnings estimate) so the two can never disagree
    about which rate is "the" rate for a given Admin.
    """
    if admin.role == Role.SUB_ADMIN:
        if admin.sub_admin_cpm is not None:
            return admin.sub_admin_cpm
        if cpm_setting.sub_admin_cpm is not None:
            return cpm_setting.sub_admin_cpm
    elif admin.role == Role.ADMIN and cpm_setting.admin_cpm is not None:
        return cpm_setting.admin_cpm
    return cpm_setting.current_cpm


def effective_ad_count(
    admin: Optional["Admin"],
    ad_network_setting: "AdNetworkSetting",
    category: Optional["Category"] = None,
) -> int:
    """How many sequential ads a viewer must watch to unlock any link
    owned by `admin`, checked in priority order:

      1. `Category.ad_count` — the *link's own category's* Owner-set ad
         count (storage.set_category_ad_count / POST /api/admin/admins/
         {telegram_id}/categories/{category_id}/ad-count), if this link
         is tagged with a category and the Owner gave that specific
         category its own count. Checked before the per-Admin override
         because a category is a statement about the *content* a link
         points to (e.g. every link an Admin tags "Movie" showing 10
         ads, "Natok" showing 7), which is a more specific signal than a
         blanket per-Admin setting — an Admin with their own
         `Admin.ad_count` set can still have individual categories
         override it link-by-link.
      2. `Admin.ad_count` — this specific Admin/Sub Admin's own
         profile-level override (storage.set_admin_ad_count /
         POST /api/admin/admins/{telegram_id}/ad-count), if the Owner
         set one for them individually and the link's category (if any)
         didn't already decide the count above. Unlike the old per-link
         control, this is read fresh on every view rather than baked
         into a Link at creation time, so setting it once on an
         Admin/Sub Admin's profile applies instantly to every link they
         already have and every new one — no per-link action needed.
      3. `len(AdNetworkSetting.slot_sequence)` — the platform-wide
         default (Owner's "Ad display order" screen), used for any
         Admin/Sub Admin with no override, any category with no override
         (or no category at all), and for `admin=None`.

    Mirrors effective_cpm()'s per-Admin-override-over-platform-default
    shape, but is available to Role.ADMIN as well as Role.SUB_ADMIN —
    the ad-count override isn't tier-restricted the way CPM overrides
    are. `Link.ad_count` is never consulted here; see its docstring.

    `category` is optional and independent of `admin` — pass None
    whenever the link has no `category_id`, or the caller genuinely
    doesn't have per-link context (e.g. resolving a generic "your admin
    tools" count with no specific link in view); every existing caller
    that predates categories still works unchanged by simply omitting
    this argument.
    """
    base_count = max(1, len(ad_network_setting.slot_sequence or []))
    if category is not None and category.ad_count is not None:
        return category.ad_count
    if admin is not None and admin.ad_count is not None:
        return admin.ad_count
    return base_count


class Role(str, Enum):
    """Power ranks from highest to lowest: OWNER > ADMIN > SUB_ADMIN >
    VIEWER. A brand new bot user starts as VIEWER; adding their first
    Traffic Source auto-promotes them to SUB_ADMIN (see
    storage.add_traffic_source). SUB_ADMIN -> ADMIN only happens when the
    Owner approves an Admin request (see storage.resolve_admin_request) —
    it's never automatic. OWNER is fixed at boot time (OWNER_TELEGRAM_ID)
    and never assigned any other way.
    """

    OWNER = "owner"
    ADMIN = "admin"
    SUB_ADMIN = "sub_admin"
    VIEWER = "viewer"


class AdminRequestStatus(str, Enum):
    PENDING = "pending"
    REJECTED = "rejected"


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


class Category(BaseModel):
    """One user-defined label an Admin/Sub Admin can tag their own short
    links with (e.g. "Movies", "Giveaway", "YouTube promo") — mostly a
    personal organizational tool, plus one Owner-only lever: a fixed ad
    count per category (see `ad_count` below). Never read by CPM
    crediting. Scoped to whichever Admin created it, the same way TrafficSource is: it lives inside that Admin's own `categories`
    list rather than a shared platform-wide table, so two different
    Admins can each have a category named the same thing without
    colliding, and one Admin's categories are never shown or selectable
    by another.

    Renaming isn't supported — delete and recreate covers it, since
    (unlike a Link) removing a Category loses nothing: no view history
    or balance is attached to a category itself, only to the links that
    once referenced it (and storage.delete_category clears their
    `category_id` back to None rather than leaving it dangling).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    created_at: str = Field(default_factory=now_iso)

    # Owner-only per-category ad count override (storage.
    # set_category_ad_count / POST /api/admin/admins/{telegram_id}/
    # categories/{category_id}/ad-count) — e.g. every link this Admin
    # tags "Movie" shows 10 ads, "Natok" shows 7, regardless of the
    # Admin's own Admin.ad_count profile setting. None means "no
    # category-level override" — falls through to the Admin-level
    # override, then the platform default; see effective_ad_count()'s
    # full priority order in this module. Unlike the category itself,
    # this can never be set by the Admin who owns the category — only
    # the Owner's per-Admin detail page can change it.
    ad_count: Optional[int] = None


class Admin(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    role: Role = Role.VIEWER
    balance_confirmed: float = 0.0
    balance_pending: float = 0.0
    created_at: str = Field(default_factory=now_iso)
    status: AdminStatus = AdminStatus.ACTIVE

    traffic_sources: list[TrafficSource] = Field(default_factory=list)
    categories: list[Category] = Field(default_factory=list)

    # Which PolicySetting.version this Admin last tapped "Accept" on (see
    # PolicySetting below). 0 means "never accepted anything" — a brand
    # new Admin. Whenever the Owner edits the policy text, its version
    # increments, which makes every existing Admin's stored value stale
    # again until they accept the new text too (bot.py's PolicyGate
    # re-prompts on their next interaction).
    policy_accepted_version: int = 0
    policy_accepted_at: Optional[str] = None

    # -- Sub Admin tier (Owner > Admin > Sub Admin > Viewer) -------------

    # Owner-only, per-Sub-Admin CPM override (storage.set_sub_admin_cpm).
    # None means "use the platform-wide CPMSetting.current_cpm" — this is
    # only ever looked at for a Role.SUB_ADMIN; it's meaningless (and
    # ignored by cpm_engine) for any other role.
    sub_admin_cpm: Optional[float] = None

    # Owner-only, per-Sub-Admin auto-delete window in months for every
    # *new* link this Sub Admin creates from now on (storage.
    # set_link_auto_delete / storage.SUB_ADMIN_AUTO_DELETE_CHOICES —
    # 1, 3, 6, or 12). None/0 means links never auto-expire. Existing
    # links keep whatever expiry they were created with — changing this
    # is never retroactive, matching how a CPM-rate change never
    # re-prices views that already happened.
    link_auto_delete_months: Optional[int] = None

    # -- Ad count override (applies to both Admin and Sub Admin) --------

    # Owner-only, per-Admin/Sub-Admin override for how many sequential
    # ads a viewer watches to unlock ANY link this person owns
    # (storage.set_admin_ad_count / storage.MIN_AD_COUNT..MAX_AD_COUNT).
    # None means "use the platform-wide AdNetworkSetting.slot_sequence
    # length" — see effective_ad_count() above for the full priority
    # order. Unlike sub_admin_cpm/link_auto_delete_months, this is not
    # cleared on a role change between Admin and Sub Admin — it applies
    # to both tiers and simply carries over across a promotion/demotion
    # between them.
    ad_count: Optional[int] = None

    # -- Sub Admin -> Admin promotion request -----------------------------
    # A Sub Admin can ask the Owner to be promoted to Admin
    # (storage.submit_admin_request); the Owner approves or rejects
    # (storage.resolve_admin_request). `admin_request_status` is None
    # until a request is submitted, "pending" while awaiting a decision,
    # or "rejected" after the Owner declines (an approval clears it back
    # to None since the role itself — now ADMIN — is the record of it).
    admin_request_status: Optional[AdminRequestStatus] = None
    admin_request_note: Optional[str] = None
    admin_request_at: Optional[str] = None
    admin_request_reason: Optional[str] = None
    admin_request_resolved_at: Optional[str] = None


class ApiKey(BaseModel):
    """A long-lived credential an Owner or Admin generates from the
    panel's API tab to call the public REST API (see API_DOCS.md) from
    their own site/server, instead of the Telegram-initData auth every
    Mini App call uses.

    The raw secret (`storage.create_api_key`'s return value) is shown to
    its creator exactly once, at creation time, and is never persisted
    or shown again — only its SHA-256 hash (`key_hash`) is stored, the
    same principle as a password. `key_prefix` (the first 12 characters
    of the raw key) is kept in the clear purely so the owner can tell
    their keys apart in a list without re-seeing the secret.

    A key authenticates as whichever Admin generated it, at that Admin's
    *current* role and permissions — it is not a separate identity or a
    fixed snapshot of permissions. So demoting, banning, or role-changing
    that Admin instantly changes what any of their keys can do too, and
    every key an Admin holds stops working the moment that Admin is
    banned (see app.py's `require_api_key`).
    """

    key_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_telegram_id: int
    name: str
    key_hash: str
    key_prefix: str
    created_at: str = Field(default_factory=now_iso)
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None


class Link(BaseModel):
    """`ad_count` used to independently control how many ads a viewer
    watched. It's kept here for backward compatibility and historical
    stats only — the actual number of ads shown to a viewer is now
    `effective_ad_count()`'s result: the owning Admin/Sub Admin's own
    `Admin.ad_count` profile override if the Owner set one, otherwise
    `len(AdNetworkSetting.slot_sequence)`. The old Owner-only per-link
    override (storage.set_link_ad_count / POST
    /api/admin/links/{short_code}/ad-count) still exists but no longer
    changes what a viewer experiences — set the ad count on the
    Admin/Sub Admin's profile instead (storage.set_admin_ad_count) to
    affect every link they own at once, in real time.
    """

    short_code: str
    owner_telegram_id: int
    destination_url: str
    # Optional, Admin-set label for this link (e.g. "August giveaway
    # post") — purely a display convenience so an Admin with many links
    # can tell them apart at a glance in "My Links" / the Owner's
    # per-Admin link list, without having to remember what a bare
    # short_code or destination_url was for. Always optional: POST
    # /api/links and POST /api/v1/links both accept it but never require
    # it, and nothing else in the app (ad-serving, CPM crediting, the
    # bot's /newlink flow) reads or depends on it — it's display-only.
    title: Optional[str] = None
    # References one of the owning Admin's own Category.id values (see
    # Category's docstring) — never validated against a foreign key at
    # this model level, only at request time in app.py, the same
    # division of labor `title`'s own length check follows. A dangling
    # value (the category was since deleted) is treated as "no
    # category" everywhere this is read, never an error — see
    # storage.delete_category and Storage._category_name.
    category_id: Optional[str] = None
    ad_count: int = 3
    created_at: str = Field(default_factory=now_iso)

    # Set at creation time from the owning Admin's
    # `Admin.link_auto_delete_months` (Sub Admin auto-delete feature) —
    # None means this link never expires on its own. Purged by
    # storage.purge_expired_links, run periodically from app.py's
    # lifespan alongside the CPM cycle watcher.
    expires_at: Optional[str] = None


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

    # Platform-wide, per-*role* CPM overrides (Owner's CPM Settings
    # screen) — distinct from Admin.sub_admin_cpm, which overrides the
    # rate for one specific Sub Admin. None means "use current_cpm" for
    # that role. See effective_cpm() for the full priority order.
    admin_cpm: Optional[float] = None
    sub_admin_cpm: Optional[float] = None

    # Platform-wide default `Admin.link_auto_delete_months` applied
    # automatically to a Viewer the moment they're promoted to Sub Admin
    # (storage.add_traffic_source) — so the Owner doesn't have to
    # remember to open every new Sub Admin's profile and set it by hand.
    # None/0 means "don't auto-set anything" (a fresh Sub Admin keeps
    # the same 'never' default as before this setting existed). Changing
    # this later is never retroactive: it only affects Sub Admins
    # promoted from now on, exactly like a CPM-rate change never
    # re-prices views that already happened. The Owner can still
    # override any individual Sub Admin's value afterward from their
    # profile — that per-person value always wins from then on.
    default_sub_admin_auto_delete_months: Optional[int] = None

    # Owner-only kill switch for POST /api/withdraw (storage.
    # set_withdrawals_paused) — meant for when the Owner is busy or on
    # leave and can't review/pay out withdrawal requests promptly.
    # `False` (default) is normal operation. While `True`, every Admin/
    # Sub Admin's withdrawal *request* is rejected outright (400, with
    # `withdrawals_paused_message` as the detail if set) before a
    # WithdrawRequest row is even created — nothing queues up invisibly
    # to be dealt with later, the Admin just tries again once the Owner
    # flips it back. This only blocks *new* requests: any withdrawal
    # already PENDING when the pause is turned on stays exactly as
    # pending, and the Owner can still resolve it normally — pausing
    # is not the same as freezing the whole withdrawal queue.
    withdrawals_paused: bool = False
    withdrawals_paused_message: Optional[str] = None

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
    position (Ad 1, Ad 2, Ad 3, ...). This list's length is the
    platform-wide *default* ad count — Ad1, then Ad2, and so on down to
    the last slot the Owner has added, with no padding or repeating —
    used for any Admin/Sub Admin with no ad_count override of their own
    (see effective_ad_count()). When an Admin/Sub Admin's link needs a
    different-length sequence than this base pattern (their own
    `Admin.ad_count` is set), the pattern is cycled to fill that length
    rather than padded with a fixed network, so every slot still points
    at a real, Owner-configured network. Defaults to three Adsgram
    slots, matching the platform's original fixed single-network
    behavior.
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
