"""Telegram bot (aiogram 3) — commands and conversational flows.

The bot itself never talks to storage's lock-guarded internals directly
except through Storage's public async methods; CPM crediting is delegated
to cpm_engine so bot.py and app.py can't drift into different business
logic for the same operation.
"""
from __future__ import annotations

import logging
import random
import string
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    TelegramObject,
    WebAppInfo,
)

from models import AdminRequestStatus, CountedStatus, CPMMode, Role, WithdrawMethod, WithdrawStatus
from validators import bd_mobile_validation_error, normalize_bd_mobile_number

logger = logging.getLogger("bot")

TRAFFIC_PLATFORMS = [
    ("telegram", "Telegram"),
    ("youtube", "YouTube"),
    ("facebook", "Facebook"),
    ("tiktok", "TikTok"),
    ("other", "Other"),
]


class NewLinkStates(StatesGroup):
    waiting_for_url = State()


class TrafficSourceStates(StatesGroup):
    """An Admin can hold several traffic sources at once and add/edit/
    remove them at any time, so this flow branches into an "add a new
    one" path and an "edit an existing one" path rather than a single
    platform->url sequence.
    """

    waiting_for_new_platform = State()
    waiting_for_new_url = State()
    waiting_for_edit_platform = State()
    waiting_for_edit_url = State()


class WithdrawStates(StatesGroup):
    waiting_for_method = State()
    waiting_for_account = State()
    waiting_for_amount = State()


class AdminRequestStates(StatesGroup):
    """A Sub Admin's /requestadmin flow — a short optional note about
    their traffic source, sent along with the request so the Owner has
    something to verify against before deciding.
    """

    waiting_for_note = State()


class AdminReviewStates(StatesGroup):
    """The Owner's side of resolving a pending Admin request from their
    Telegram DM: tapping "❌ Reject" (see notify_owner_of_admin_request)
    drops the Owner into this state to type the required reason before
    the rejection is actually recorded.
    """

    waiting_for_reject_reason = State()


def build_bot_and_dispatcher(bot_token: str) -> tuple[Bot, Dispatcher]:
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    return bot, dp


def _default_bot_commands() -> list[BotCommand]:
    """The command list Telegram shows behind the native "/" menu button
    next to the message input — a second, native way to reach every
    command besides the persistent reply keyboard from
    `_main_menu_keyboard`. Kept in one place so the two never drift apart.
    """
    return [
        BotCommand(command="start", description="বট শুরু করুন / মূল মেনু"),
        BotCommand(command="newlink", description="নতুন শর্ট লিংক তৈরি করুন"),
        BotCommand(command="trafficsource", description="ট্রাফিক সোর্স যোগ/এডিট/মুছুন"),
        BotCommand(command="mybalance", description="ব্যালেন্স ও পেআউট তথ্য দেখুন"),
        BotCommand(command="withdraw", description="টাকা তোলার আবেদন করুন"),
        BotCommand(command="requestadmin", description="Sub Admin থেকে Admin হওয়ার আবেদন করুন"),
        BotCommand(command="panel", description="পূর্ণাঙ্গ ড্যাশবোর্ড খুলুন"),
        BotCommand(command="privacy", description="প্রাইভেসি পলিসি ও শর্তাবলী দেখুন"),
        BotCommand(command="help", description="সাহায্য ও কমান্ড তালিকা"),
    ]


async def set_bot_commands(bot: Bot) -> None:
    """Registers the "/" command menu with Telegram. Safe to call on every
    startup — Telegram just overwrites the previous list, and failure here
    (e.g. no network yet) shouldn't block the rest of startup, so callers
    are expected to wrap this the same way they already wrap set_webhook.
    """
    await bot.set_my_commands(_default_bot_commands())


ROLE_LABELS = {
    Role.OWNER: "👑 ওনার",
    Role.ADMIN: "🛡️ অ্যাডমিন",
    Role.SUB_ADMIN: "⭐ সাব অ্যাডমিন",
    Role.VIEWER: "👁️ ভিউয়ার",
}


def _role_label(role: Role) -> str:
    return ROLE_LABELS.get(role, str(role.value))


def _welcome_text(admin) -> str:
    label = _role_label(admin.role)
    if admin.role == Role.VIEWER:
        return (
            f"স্বাগতম! আপনি এখন <b>{label}</b>। 👋\n\n"
            "<b>TGSHORTBOT</b>-এ লিংক শর্ট করে আয় করা শুরু করতে প্রথমে একটি "
            "<b>Traffic Source</b> (আপনার চ্যানেল/গ্রুপ/প্রোফাইল) যোগ করুন — "
            "এটি করার সাথে সাথেই আপনি স্বয়ংক্রিয়ভাবে <b>⭐ সাব অ্যাডমিন</b> হয়ে যাবেন এবং লিংক তৈরি করতে পারবেন।\n\n"
            "📡 ট্রাফিক সোর্স বাটনে চাপ দিয়ে এখনই শুরু করুন:"
        )
    return (
        f"স্বাগতম, {label}! 👋\n\n"
        "<b>TGSHORTBOT</b> দিয়ে লিংক শর্ট করুন, শেয়ার করুন, আর প্রতিটি ভিউ থেকে আয় করুন।\n\n"
        "নিচের বাটন থেকে যেকোনো অপশনে ট্যাপ করুন:"
    )


def _gen_short_code(length: int = 7) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choices(alphabet, k=length))


# ---------------------------------------------------------------------------
# Policy gate — every user must Accept the Owner-editable policy text
# (models.PolicySetting) before doing anything else with the bot. New users
# hit this on their very first /start (either entry point below); existing
# users hit it again the moment the Owner edits the text and bumps its
# version (see storage.update_policy_text), via PolicyGateMiddleware.
# ---------------------------------------------------------------------------

POLICY_ACCEPT_PREFIX = "policy:accept:"
POLICY_REJECT_PREFIX = "policy:reject:"
_NO_RESUME = "none"  # sentinel meaning "no deep-linked view to resume after Accept"


def _policy_keyboard(resume_code: str | None) -> InlineKeyboardMarkup:
    token = resume_code or _NO_RESUME
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Accept", callback_data=f"{POLICY_ACCEPT_PREFIX}{token}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"{POLICY_REJECT_PREFIX}{token}"),
            ]
        ]
    )


async def _prompt_policy(event: Message | CallbackQuery, policy, resume_code: str | None = None) -> None:
    """Sends the Accept/Reject popup. `resume_code` — the short_code from
    a deep-linked /start — is carried inside the button's own callback_data
    so a first-time viewer who clicked someone's shared link still lands
    on that link's ad-unlock button after tapping Accept, instead of losing
    that context and landing on the generic main menu.
    """
    text = f"📜 <b>নিয়মাবলী ও শর্তাবলী</b>\n\n{policy.text}"
    kb = _policy_keyboard(resume_code)
    if isinstance(event, CallbackQuery):
        await event.answer("অনুগ্রহ করে আগে নিয়মাবলী গ্রহণ করুন।", show_alert=True)
        if event.message:
            await event.message.answer(text, reply_markup=kb)
    else:
        await event.answer(text, reply_markup=kb)


class PolicyGateMiddleware(BaseMiddleware):
    """Intercepts every Message/CallbackQuery for an *existing* Admin whose
    `policy_accepted_version` is behind the currently active PolicySetting
    (i.e. the Owner edited the policy after this Admin already accepted an
    older version) and re-prompts instead of running the real handler.

    Brand-new users (no Admin row yet) are deliberately let through here —
    they're gated inside the /start handlers themselves once `_ensure_admin`
    has created their row, since only those handlers know whether a
    deep-linked short_code needs to be preserved through the prompt.

    The Accept/Reject callback itself is always let through (matched by
    its callback_data prefix), or the popup could never be dismissed.
    """

    def __init__(self, storage) -> None:
        self.storage = storage
        super().__init__()

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if isinstance(event, CallbackQuery) and (
            event.data or ""
        ).startswith((POLICY_ACCEPT_PREFIX, POLICY_REJECT_PREFIX)):
            return await handler(event, data)

        admin = await self.storage.get_admin(user.id)
        if admin is None:
            return await handler(event, data)  # /start will create + gate it

        if not await self.storage.has_accepted_current_policy(user.id):
            await _prompt_policy(event, await self.storage.get_policy_setting())
            return None  # swallow — don't run the real handler

        return await handler(event, data)


# Labels for the persistent bottom keyboard — every command is a tap away
# instead of something the user has to remember and type out.
MAIN_MENU_LABELS = {
    "newlink": "🔗 নতুন লিংক",
    "trafficsource": "📡 ট্রাফিক সোর্স",
    "mybalance": "💰 ব্যালেন্স",
    "withdraw": "💸 উইথড্র",
    "privacy": "🔒 প্রাইভেসি পলিসি",
    "help": "❓ সাহায্য",
}


def _main_menu_keyboard(panel_url: str) -> ReplyKeyboardMarkup:
    """Persistent reply keyboard shown after /start and /help so the
    Admin never has to type a command by hand — every button here maps
    1:1 onto one of the bot's slash commands (see the `menu_*` handlers
    in register_handlers).

    Deliberately has no Dashboard button of its own anymore. A reply-
    keyboard `web_app` button pointing at a URL that's identical (or
    even cache-busted-but-similar) every time has been observed
    occasionally opening a stale outside-Telegram-looking page instead
    of the real Mini App — a real risk with an ad network's moderator
    tapping around the bot (Adsgram Clause 5: "the bot must be working
    at the time of moderation"). The BotFather-configured Menu Button
    and the `/panel` command's own inline button remain as the two ways
    into the dashboard; `panel_url` is kept as a parameter here only so
    every existing call site doesn't need to change.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=MAIN_MENU_LABELS["newlink"]),
                KeyboardButton(text=MAIN_MENU_LABELS["trafficsource"]),
            ],
            [
                KeyboardButton(text=MAIN_MENU_LABELS["mybalance"]),
                KeyboardButton(text=MAIN_MENU_LABELS["withdraw"]),
            ],
            [
                KeyboardButton(text=MAIN_MENU_LABELS["help"]),
                KeyboardButton(text=MAIN_MENU_LABELS["privacy"]),
            ],
        ],
        resize_keyboard=True,
    )


def _traffic_source_menu(admin) -> tuple[str, InlineKeyboardMarkup]:
    """Builds the "your traffic sources" list message + inline keyboard —
    reused after every add/edit/delete so the Admin always lands back on
    an up-to-date view of everything they've got on file.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if admin.traffic_sources:
        lines = ["📡 <b>আপনার ট্রাফিক সোর্সসমূহ</b>\n"]
        for i, s in enumerate(admin.traffic_sources, start=1):
            lines.append(f"{i}. <b>{s.platform}</b> — {s.url}")
            rows.append(
                [
                    InlineKeyboardButton(text=f"✏️ {i} এডিট", callback_data=f"ts_edit:{s.id}"),
                    InlineKeyboardButton(text=f"🗑 {i} মুছুন", callback_data=f"ts_del:{s.id}"),
                ]
            )
        text = "\n".join(lines)
    else:
        text = (
            "📡 <b>ট্রাফিক সোর্স</b>\n\nএখনো কোনো ট্রাফিক সোর্স যোগ করা হয়নি।\n"
            "লিংক তৈরির আগে অন্তত একটি সোর্স যোগ করতে হবে।"
        )
    rows.append([InlineKeyboardButton(text="➕ নতুন সোর্স যোগ করুন", callback_data="ts_add")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def notify_owner_of_withdrawal(bot: Bot, settings, admin, req) -> None:
    """Pings the Owner's Telegram chat the moment a withdrawal is
    requested — whether it came from the bot's own /withdraw flow or from
    the panel's withdrawal form — so the Owner never has to go looking
    for it.
    """
    who = f"@{admin.username}" if admin.username else f"id {admin.telegram_id}"
    if admin.traffic_sources:
        ts_line = "\n" + "\n".join(
            f'• {s.platform}: <a href="{s.url}">{s.url}</a>' for s in admin.traffic_sources
        )
    else:
        ts_line = "সেট করা নেই"
    method_label = "bKash" if req.method.value == "bkash" else "Nagad"

    text = (
        "🔔 <b>নতুন উইথড্র রিকোয়েস্ট</b>\n\n"
        f"Admin: {who}\n"
        f"পরিমাণ: <b>{req.amount:.2f}</b>\n"
        f"পদ্ধতি: {method_label}\n"
        f"অ্যাকাউন্ট: <code>{req.account_number}</code>\n"
        f"Traffic Source: {ts_line}"
    )
    panel_url = f"{settings.WEBAPP_BASE_URL}/panel"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📊 প্যানেলে রিভিউ করুন", web_app=WebAppInfo(url=panel_url))]]
    )
    try:
        await bot.send_message(settings.OWNER_TELEGRAM_ID, text, reply_markup=kb)
    except Exception:
        logger.exception("failed to notify owner about withdrawal request")


async def notify_admin_of_withdrawal_resolution(bot: Bot, settings, admin, req) -> None:
    """Pings the *requesting* Admin's Telegram chat the moment the Owner
    resolves their withdrawal — Paid or Rejected — so they find out
    immediately instead of having to keep re-opening the panel.
    """
    method_label = "bKash" if req.method.value == "bkash" else "Nagad"
    if req.status == WithdrawStatus.PAID:
        text = (
            "✅ <b>আপনার টাকা পাঠানো হয়েছে</b>\n\n"
            f"পরিমাণ: <b>{req.amount:.2f}</b>\n"
            f"পদ্ধতি: {method_label}\n"
            f"অ্যাকাউন্ট: <code>{req.account_number}</code>\n\n"
            f"আপনার {method_label} অ্যাকাউন্টে পেমেন্টটি চেক করুন।"
        )
    else:
        reason_line = f"\nকারণ: {req.reject_reason}" if req.reject_reason else ""
        text = (
            "❌ <b>আপনার উইথড্র রিকোয়েস্টটি প্রত্যাখ্যান করা হয়েছে</b>\n\n"
            f"পরিমাণ: <b>{req.amount:.2f}</b>\n"
            f"পদ্ধতি: {method_label}{reason_line}\n\n"
            "বিস্তারিত জানতে Owner-এর সাথে যোগাযোগ করুন।"
        )
    try:
        await bot.send_message(admin.telegram_id, text)
    except Exception:
        logger.exception("failed to notify admin about withdrawal resolution")


ADMIN_REQUEST_APPROVE_PREFIX = "areq:approve:"
ADMIN_REQUEST_REJECT_PREFIX = "areq:reject:"


async def notify_owner_of_admin_request(bot: Bot, settings, admin, note: str | None, stats: dict | None = None) -> None:
    """Pings the Owner the instant a Sub Admin submits an Admin request
    (bot's /requestadmin flow, or the panel's equivalent button) — with
    enough at-a-glance context (traffic sources, link/view/earning
    totals) to actually judge the PRD's "strong traffic source + works
    regularly" bar, plus one-tap Approve/Reject right from the DM so the
    Owner doesn't have to open the panel just to say yes.
    """
    who = f"@{admin.username}" if admin.username else f"id {admin.telegram_id}"
    if admin.traffic_sources:
        ts_line = "\n" + "\n".join(
            f'• {s.platform}: <a href="{s.url}">{s.url}</a>' for s in admin.traffic_sources
        )
    else:
        ts_line = " সেট করা নেই"
    stats_line = ""
    if stats:
        stats_line = (
            f"\nমোট লিংক: <b>{stats.get('total_links', 0)}</b> · "
            f"মোট ভিউ: <b>{stats.get('total_views', 0)}</b> · "
            f"লাইফটাইম আয়: <b>{stats.get('lifetime_income', 0):.2f}</b>"
        )
    note_line = f"\n\nবার্তা: {note}" if note else ""
    text = (
        "🆙 <b>নতুন Admin রিকোয়েস্ট</b>\n\n"
        f"সাব অ্যাডমিন: {who} (<code>{admin.telegram_id}</code>)\n"
        f"সদস্য হয়েছেন: {admin.created_at[:10]}\n"
        f"Traffic Source:{ts_line}"
        f"{stats_line}"
        f"{note_line}"
    )
    panel_url = f"{settings.WEBAPP_BASE_URL}/panel"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ গ্রহণ করুন", callback_data=f"{ADMIN_REQUEST_APPROVE_PREFIX}{admin.telegram_id}"),
                InlineKeyboardButton(text="❌ প্রত্যাখ্যান করুন", callback_data=f"{ADMIN_REQUEST_REJECT_PREFIX}{admin.telegram_id}"),
            ],
            [InlineKeyboardButton(text="📊 প্যানেলে দেখুন", web_app=WebAppInfo(url=panel_url))],
        ]
    )
    try:
        await bot.send_message(settings.OWNER_TELEGRAM_ID, text, reply_markup=kb)
    except Exception:
        logger.exception("failed to notify owner about admin request")


async def notify_sub_admin_of_admin_request_resolution(bot: Bot, admin, approved: bool, reason: str | None) -> None:
    """Pings the requesting Sub Admin the moment the Owner approves or
    rejects their Admin request."""
    if approved:
        text = (
            f"🎉 <b>অভিনন্দন! আপনি এখন {_role_label(Role.ADMIN)}!</b>\n\n"
            "আপনার Admin রিকোয়েস্ট গ্রহণ করা হয়েছে। এখন থেকে আপনার নতুন ক্ষমতা কার্যকর।"
        )
    else:
        reason_line = f"\nকারণ: {reason}" if reason else ""
        text = (
            "❌ <b>আপনার Admin রিকোয়েস্টটি প্রত্যাখ্যান করা হয়েছে</b>\n"
            f"{reason_line}\n\n"
            "আরও শক্তিশালী ট্রাফিক সোর্স ও নিয়মিত কাজের মাধ্যমে যোগ্যতা অর্জন করে আবার /requestadmin দিয়ে আবেদন করতে পারবেন।"
        )
    try:
        await bot.send_message(admin.telegram_id, text)
    except Exception:
        logger.exception("failed to notify sub admin about admin request resolution")


async def notify_sub_admin_of_cpm_change(bot: Bot, admin, cpm: float | None) -> None:
    """Owner-only per-Sub-Admin CPM override changed from the panel."""
    if cpm is None:
        text = "ℹ️ আপনার জন্য নির্ধারিত আলাদা CPM রেট সরিয়ে ফেলা হয়েছে — এখন থেকে প্ল্যাটফর্মের সাধারণ CPM প্রযোজ্য হবে।"
    else:
        text = f"ℹ️ Owner আপনার জন্য একটি আলাদা CPM রেট নির্ধারণ করেছেন: <b>{cpm:.4f}</b> প্রতি ভিউ।"
    try:
        await bot.send_message(admin.telegram_id, text)
    except Exception:
        logger.exception("failed to notify sub admin about cpm change")


async def notify_sub_admin_of_auto_delete_change(bot: Bot, admin, months: int | None) -> None:
    """Owner-only per-Sub-Admin link auto-delete window changed from the
    panel — this is the "ম্যাসেজ" the Owner sends about it, per the
    feature spec: a heads-up DM rather than a silent setting change.
    """
    if months:
        text = (
            f"ℹ️ Owner আপনার লিংকের জন্য একটি অটো-ডিলেট সময়সীমা নির্ধারণ করেছেন: "
            f"<b>{months} মাস</b>। আজ থেকে তৈরি করা নতুন লিংকগুলো {months} মাস পর স্বয়ংক্রিয়ভাবে মুছে যাবে। "
            "আগের তৈরি করা লিংকে এটি প্রযোজ্য নয়।"
        )
    else:
        text = "ℹ️ Owner আপনার লিংকের অটো-ডিলেট সময়সীমা বাতিল করেছেন — নতুন লিংকগুলো আর নিজে থেকে মুছে যাবে না।"
    try:
        await bot.send_message(admin.telegram_id, text)
    except Exception:
        logger.exception("failed to notify sub admin about auto-delete change")


def _bot_short_url_for(code: str, settings) -> str:
    """Mirrors app.py's _short_url_for — kept as a separate copy since
    bot.py builds links directly through storage rather than calling its
    own HTTP API. When settings.MINI_APP_SHORT_NAME is configured (a
    Mini App attached to this bot via @BotFather's /newapp), viewers who
    tap the shared link land straight on the ad-lock page with no chat
    step in between; otherwise this falls back to the original
    t.me/<bot>?start=<code> flow handled by start_with_code below.
    """
    if getattr(settings, "MINI_APP_SHORT_NAME", ""):
        return f"https://t.me/{settings.BOT_USERNAME}/{settings.MINI_APP_SHORT_NAME}?startapp={code}"
    return f"https://t.me/{settings.BOT_USERNAME}?start={code}"


async def _effective_ad_count(storage) -> int:
    """How many ads a viewer actually watches to unlock any link on the
    platform right now — see AdNetworkSetting.slot_sequence's docstring
    in models.py. Used only for the human-readable count in bot
    messages; the real enforcement lives in app.py/webapp/viewer.html.
    """
    ans = await storage.get_ad_network_setting()
    return max(1, len(ans.slot_sequence or []))


def register_handlers(dp: Dispatcher, storage, settings) -> None:
    # Runs before every other handler below — see PolicyGateMiddleware's
    # own docstring for exactly what it does and doesn't intercept.
    policy_gate = PolicyGateMiddleware(storage)
    dp.message.middleware(policy_gate)
    dp.callback_query.middleware(policy_gate)

    async def _ensure_admin(telegram_id: int, username: str | None):
        return await storage.get_or_create_admin(telegram_id, username, settings.OWNER_TELEGRAM_ID)

    async def _create_link_and_reply(message: Message, admin, url: str) -> None:
        code = _gen_short_code()
        while await storage.get_link(code):
            code = _gen_short_code()
        link = await storage.create_link(code, admin.telegram_id, url)
        short_url = _bot_short_url_for(code, settings)
        ad_count = await _effective_ad_count(storage)
        panel_url = f"{settings.WEBAPP_BASE_URL}/panel"
        await message.answer(
            f"✅ শর্ট লিংক তৈরি হয়েছে:\n<code>{short_url}</code>\n\n"
            "লিংকটি আপনার Traffic Source-এ (চ্যানেল/গ্রুপ/পোস্ট) শেয়ার করুন। "
            f"ভিউয়াররা এতে ক্লিক করলে {ad_count}টি বিজ্ঞাপন দেখাবে, তারপর গন্তব্যে পৌঁছাবে।",
            reply_markup=_main_menu_keyboard(panel_url),
        )

    # ------------------------------------------------------------------
    # Persistent main-menu buttons — registered first (before any FSM
    # state handler further down) so a tap always wins, even mid-flow
    # (e.g. partway through /withdraw), instead of being swallowed as
    # free text by that state's own handler. Each one clears whatever
    # state was active and then delegates to the matching slash-command
    # handler, so the two stay in lockstep by construction.
    # ------------------------------------------------------------------

    @dp.message(F.text == MAIN_MENU_LABELS["newlink"])
    async def menu_newlink(message: Message, state: FSMContext) -> None:
        await state.clear()
        await newlink_cmd(message, SimpleNamespace(args=None), state)

    @dp.message(F.text == MAIN_MENU_LABELS["trafficsource"])
    async def menu_trafficsource(message: Message, state: FSMContext) -> None:
        await trafficsource_cmd(message, state)

    @dp.message(F.text == MAIN_MENU_LABELS["mybalance"])
    async def menu_mybalance(message: Message, state: FSMContext) -> None:
        await state.clear()
        await mybalance_cmd(message)

    @dp.message(F.text == MAIN_MENU_LABELS["withdraw"])
    async def menu_withdraw(message: Message, state: FSMContext) -> None:
        await state.clear()
        await withdraw_cmd(message, state)

    @dp.message(F.text == MAIN_MENU_LABELS["help"])
    async def menu_help(message: Message, state: FSMContext) -> None:
        await state.clear()
        await help_cmd(message)

    @dp.message(F.text == MAIN_MENU_LABELS["privacy"])
    async def menu_privacy(message: Message, state: FSMContext) -> None:
        await state.clear()
        await privacy_cmd(message)

    # ------------------------------------------------------------------
    # /start
    # ------------------------------------------------------------------

    @dp.message(CommandStart(deep_link=True))
    async def start_with_code(message: Message, command) -> None:
        code = command.args
        await _ensure_admin(message.from_user.id, message.from_user.username)
        if not await storage.has_accepted_current_policy(message.from_user.id):
            await _prompt_policy(message, await storage.get_policy_setting(), resume_code=code)
            return
        link = await storage.get_link(code) if code else None
        if not link:
            await message.answer("এই শর্ট লিংকটি খুঁজে পাওয়া যায়নি বা মেয়াদোত্তীর্ণ।")
            return
        ad_count = await _effective_ad_count(storage)
        view_url = f"{settings.WEBAPP_BASE_URL}/r/{code}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"👉 চালিয়ে যান ({ad_count}টি বিজ্ঞাপন দেখুন)", web_app=WebAppInfo(url=view_url)
                )]
            ]
        )
        await message.answer(
            f"লিংকটি খুলতে নিচের বাটনে চাপ দিন। {ad_count}টি বিজ্ঞাপন দেখা শেষ হলে আপনি স্বয়ংক্রিয়ভাবে গন্তব্য পেজে পৌঁছে যাবেন।",
            reply_markup=kb,
        )

    @dp.message(CommandStart())
    async def start_plain(message: Message) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        if not await storage.has_accepted_current_policy(message.from_user.id):
            await _prompt_policy(message, await storage.get_policy_setting())
            return
        panel_url = f"{settings.WEBAPP_BASE_URL}/panel"
        await message.answer(
            _welcome_text(admin),
            reply_markup=_main_menu_keyboard(panel_url),
        )

    @dp.callback_query(F.data.startswith(POLICY_ACCEPT_PREFIX))
    async def policy_accept_cb(callback: CallbackQuery) -> None:
        admin = await _ensure_admin(callback.from_user.id, callback.from_user.username)
        admin = await storage.accept_policy(callback.from_user.id) or admin
        await callback.answer("ধন্যবাদ! ✅")
        if callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        resume_code = callback.data[len(POLICY_ACCEPT_PREFIX):]
        if resume_code and resume_code != _NO_RESUME:
            link = await storage.get_link(resume_code)
            if link:
                ad_count = await _effective_ad_count(storage)
                view_url = f"{settings.WEBAPP_BASE_URL}/r/{resume_code}"
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(
                            text=f"👉 চালিয়ে যান ({ad_count}টি বিজ্ঞাপন দেখুন)",
                            web_app=WebAppInfo(url=view_url),
                        )]
                    ]
                )
                await callback.message.answer(
                    f"লিংকটি খুলতে নিচের বাটনে চাপ দিন। {ad_count}টি বিজ্ঞাপন দেখা শেষ হলে আপনি "
                    "স্বয়ংক্রিয়ভাবে গন্তব্য পেজে পৌঁছে যাবেন।",
                    reply_markup=kb,
                )
                return

        panel_url = f"{settings.WEBAPP_BASE_URL}/panel"
        await callback.message.answer(
            _welcome_text(admin),
            reply_markup=_main_menu_keyboard(panel_url),
        )

    @dp.callback_query(F.data.startswith(POLICY_REJECT_PREFIX))
    async def policy_reject_cb(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await callback.message.answer(
                "আপনি শর্তাবলী গ্রহণ করেননি, তাই বটটি এখন ব্যবহার করা যাচ্ছে না।\n"
                "মত পরিবর্তন করলে /start লিখে আবার চেষ্টা করুন।"
            )

    # ------------------------------------------------------------------
    # /trafficsource
    # ------------------------------------------------------------------

    @dp.message(Command("trafficsource"))
    async def trafficsource_cmd(message: Message, state: FSMContext) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        await state.clear()
        text, kb = _traffic_source_menu(admin)
        await message.answer(text, reply_markup=kb)

    @dp.callback_query(F.data == "ts_menu")
    async def trafficsource_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
        admin = await _ensure_admin(callback.from_user.id, callback.from_user.username)
        await state.clear()
        text, kb = _traffic_source_menu(admin)
        if callback.message:
            await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()

    # -- add a new source --------------------------------------------

    @dp.callback_query(F.data == "ts_add")
    async def trafficsource_add_start(callback: CallbackQuery, state: FSMContext) -> None:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=label, callback_data=f"ts_newplat:{key}")]
                for key, label in TRAFFIC_PLATFORMS
            ]
            + [[InlineKeyboardButton(text="⬅️ ফিরে যান", callback_data="ts_menu")]]
        )
        await state.set_state(TrafficSourceStates.waiting_for_new_platform)
        if callback.message:
            await callback.message.edit_text("নতুন সোর্সের প্ল্যাটফর্মটি বেছে নিন:", reply_markup=kb)
        await callback.answer()

    @dp.callback_query(TrafficSourceStates.waiting_for_new_platform, F.data.startswith("ts_newplat:"))
    async def trafficsource_new_platform_chosen(callback: CallbackQuery, state: FSMContext) -> None:
        platform_key = (callback.data or "").split(":", 1)[1]
        label = dict(TRAFFIC_PLATFORMS).get(platform_key, "Other")
        await state.update_data(platform=label)
        await state.set_state(TrafficSourceStates.waiting_for_new_url)
        if callback.message:
            await callback.message.edit_text(
                f"প্ল্যাটফর্ম: <b>{label}</b>\n\n"
                f"এখন আপনার {label} চ্যানেল/গ্রুপ/প্রোফাইলের লিংকটি পাঠান (যেখানে আপনি শর্ট লিংক শেয়ার করবেন):"
            )
        await callback.answer()

    @dp.message(TrafficSourceStates.waiting_for_new_url)
    async def trafficsource_new_url_received(message: Message, state: FSMContext) -> None:
        url = (message.text or "").strip()
        if not url.startswith(("http://", "https://")):
            await message.answer("সঠিক লিংক দিন (http:// বা https:// দিয়ে শুরু হতে হবে)।")
            return
        data = await state.get_data()
        platform = data.get("platform", "Other")
        was_viewer = (await _ensure_admin(message.from_user.id, message.from_user.username)).role == Role.VIEWER
        await storage.add_traffic_source(message.from_user.id, platform, url)
        await state.clear()
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        text, kb = _traffic_source_menu(admin)
        promo_line = (
            f"\n\n🎉 অভিনন্দন! আপনি এখন <b>{_role_label(Role.SUB_ADMIN)}</b> — এখন থেকে লিংক তৈরি করে আয় করতে পারবেন।"
            if was_viewer and admin.role == Role.SUB_ADMIN
            else ""
        )
        await message.answer(
            f"✅ নতুন ট্রাফিক সোর্স যোগ হয়েছে:\n<b>{platform}</b> — {url}\n\nএখন আপনি /newlink দিয়ে লিংক শর্ট করতে পারবেন।"
            + promo_line + "\n\n" + text,
            reply_markup=kb,
        )

    # -- edit an existing source --------------------------------------

    @dp.callback_query(F.data.startswith("ts_edit:"))
    async def trafficsource_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
        source_id = (callback.data or "").split(":", 1)[1]
        await state.update_data(edit_source_id=source_id)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=label, callback_data=f"ts_editplat:{key}")]
                for key, label in TRAFFIC_PLATFORMS
            ]
            + [[InlineKeyboardButton(text="⬅️ ফিরে যান", callback_data="ts_menu")]]
        )
        await state.set_state(TrafficSourceStates.waiting_for_edit_platform)
        if callback.message:
            await callback.message.edit_text(
                "নতুন প্ল্যাটফর্মটি বেছে নিন (আগেরটাই রাখতে চাইলে সেটিই আবার বেছে নিন):", reply_markup=kb
            )
        await callback.answer()

    @dp.callback_query(TrafficSourceStates.waiting_for_edit_platform, F.data.startswith("ts_editplat:"))
    async def trafficsource_edit_platform_chosen(callback: CallbackQuery, state: FSMContext) -> None:
        platform_key = (callback.data or "").split(":", 1)[1]
        label = dict(TRAFFIC_PLATFORMS).get(platform_key, "Other")
        await state.update_data(platform=label)
        await state.set_state(TrafficSourceStates.waiting_for_edit_url)
        if callback.message:
            await callback.message.edit_text(f"প্ল্যাটফর্ম: <b>{label}</b>\n\nনতুন লিংকটি পাঠান:")
        await callback.answer()

    @dp.message(TrafficSourceStates.waiting_for_edit_url)
    async def trafficsource_edit_url_received(message: Message, state: FSMContext) -> None:
        url = (message.text or "").strip()
        if not url.startswith(("http://", "https://")):
            await message.answer("সঠিক লিংক দিন (http:// বা https:// দিয়ে শুরু হতে হবে)।")
            return
        data = await state.get_data()
        source_id = data.get("edit_source_id")
        platform = data.get("platform")
        updated = await storage.update_traffic_source(
            message.from_user.id, source_id, platform=platform, url=url
        )
        await state.clear()
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        text, kb = _traffic_source_menu(admin)
        if updated:
            await message.answer(
                f"✅ সোর্সটি আপডেট হয়েছে:\n<b>{updated.platform}</b> — {updated.url}\n\n" + text, reply_markup=kb
            )
        else:
            await message.answer("সোর্সটি খুঁজে পাওয়া যায়নি — হয়তো ইতিমধ্যে মুছে ফেলা হয়েছে।\n\n" + text, reply_markup=kb)

    # -- delete a source ------------------------------------------------

    @dp.callback_query(F.data.startswith("ts_del:"))
    async def trafficsource_delete(callback: CallbackQuery, state: FSMContext) -> None:
        source_id = (callback.data or "").split(":", 1)[1]
        await storage.delete_traffic_source(callback.from_user.id, source_id)
        await state.clear()
        admin = await _ensure_admin(callback.from_user.id, callback.from_user.username)
        text, kb = _traffic_source_menu(admin)
        if callback.message:
            await callback.message.edit_text("🗑 সোর্সটি মুছে ফেলা হয়েছে।\n\n" + text, reply_markup=kb)
        await callback.answer()

    # ------------------------------------------------------------------
    # /newlink
    # ------------------------------------------------------------------

    @dp.message(Command("newlink"))
    async def newlink_cmd(message: Message, command, state: FSMContext) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        if not admin.traffic_sources:
            await message.answer(
                "লিংক শর্ট করার আগে আপনার অন্তত একটি <b>Traffic Source</b> যোগ করতে হবে — অর্থাৎ আপনি কোথা থেকে "
                "ভিউয়ার আনবেন (টেলিগ্রাম চ্যানেল, ইউটিউব চ্যানেল ইত্যাদির লিংক)।\n\n"
                "/trafficsource কমান্ড দিয়ে এখনই যোগ করুন।"
            )
            return
        url = command.args.strip() if command.args else None
        if url:
            if not url.startswith(("http://", "https://")):
                await message.answer(
                    "সঠিক লিংক দিন, http:// অথবা https:// দিয়ে শুরু হতে হবে।\nউদাহরণ: /newlink https://example.com"
                )
                return
            await _create_link_and_reply(message, admin, url)
            return
        await state.set_state(NewLinkStates.waiting_for_url)
        await message.answer("যে লিংকটি শর্ট করতে চান সেটি পাঠান (http:// বা https:// দিয়ে শুরু হতে হবে):")

    @dp.message(NewLinkStates.waiting_for_url)
    async def newlink_receive_url(message: Message, state: FSMContext) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        url = (message.text or "").strip()
        if not url.startswith(("http://", "https://")):
            await message.answer("সঠিক লিংক দিন, যেমন https://example.com দিয়ে শুরু হতে হবে।")
            return
        await state.clear()
        await _create_link_and_reply(message, admin, url)

    # ------------------------------------------------------------------
    # /mybalance
    # ------------------------------------------------------------------

    @dp.message(Command("mybalance"))
    async def mybalance_cmd(message: Message) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        cpm_setting = await storage.get_cpm_setting()
        my_cpm = admin.sub_admin_cpm if (admin.role == Role.SUB_ADMIN and admin.sub_admin_cpm is not None) else None
        lines = [
            f"{_role_label(admin.role)}",
            f"💰 নিশ্চিত ব্যালেন্স: <b>{admin.balance_confirmed:.2f}</b>",
        ]

        if cpm_setting.mode == CPMMode.SCHEDULED:
            started = datetime.fromisoformat(cpm_setting.cycle_started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            deadline = started + timedelta(hours=cpm_setting.cycle_duration_hours)
            remaining = max(0, int((deadline - datetime.now(timezone.utc)).total_seconds()))
            h, rem = divmod(remaining, 3600)
            m, _ = divmod(rem, 60)

            my_codes = {l.short_code for l in storage.links.values() if l.owner_telegram_id == admin.telegram_id}
            pending_views = len(
                [v for v in storage.views.values() if v.short_code in my_codes and v.counted_status == CountedStatus.PENDING_PAYOUT]
            )
            lines.append(f"⏳ পরবর্তী পেআউট: {h}ঘ {m}মি পরে")
            lines.append(f"👀 এই চক্রে পেন্ডিং ভিউ: {pending_views}")
            if my_cpm is not None:
                lines.append(f"ℹ️ আপনার জন্য নির্ধারিত আলাদা CPM: <b>{my_cpm:.4f}</b> (পেআউটের মুহূর্তে প্রযোজ্য হবে)।")
            else:
                lines.append("ℹ️ পেমেন্টের চূড়ান্ত রেট পেআউটের মুহূর্তে নির্ধারিত হয়।")
        else:
            effective = my_cpm if my_cpm is not None else cpm_setting.current_cpm
            lines.append(f"📈 বর্তমান CPM (Real-time): {effective:.4f}" + (" (আপনার জন্য আলাদা রেট)" if my_cpm is not None else ""))

        if admin.role == Role.SUB_ADMIN:
            if admin.admin_request_status == AdminRequestStatus.PENDING:
                lines.append("\n🆙 আপনার Admin রিকোয়েস্ট পর্যালোচনাধীন।")
            elif admin.admin_request_status == AdminRequestStatus.REJECTED:
                lines.append(f"\n🆙 আপনার আগের Admin রিকোয়েস্ট প্রত্যাখ্যাত হয়েছে। কারণ: {admin.admin_request_reason or '—'}\nআবার আবেদন করতে /requestadmin লিখুন।")
            else:
                lines.append("\n🆙 যোগ্যতা অর্জন করলে /requestadmin দিয়ে Admin হওয়ার আবেদন করতে পারেন।")

        await message.answer("\n".join(lines))

    # ------------------------------------------------------------------
    # /withdraw
    # ------------------------------------------------------------------

    @dp.message(Command("withdraw"))
    async def withdraw_cmd(message: Message, state: FSMContext) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        cpm_setting = await storage.get_cpm_setting()
        if admin.balance_confirmed <= 0:
            await message.answer("তোলার মতো কোনো নিশ্চিত ব্যালেন্স নেই।")
            return
        if admin.balance_confirmed < cpm_setting.min_withdraw_amount:
            await message.answer(
                f"সর্বনিম্ন উইথড্র পরিমাণ <b>{cpm_setting.min_withdraw_amount:.2f}</b>।\n"
                f"আপনার নিশ্চিত ব্যালেন্স ({admin.balance_confirmed:.2f}) এখনো এই সীমায় পৌঁছায়নি।"
            )
            return
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="bKash"), KeyboardButton(text="Nagad")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await state.set_state(WithdrawStates.waiting_for_method)
        min_line = (
            f"\nসর্বনিম্ন উইথড্র: {cpm_setting.min_withdraw_amount:.2f}"
            if cpm_setting.min_withdraw_amount > 0
            else ""
        )
        await message.answer(
            f"নিশ্চিত ব্যালেন্স: {admin.balance_confirmed:.2f}{min_line}\nপদ্ধতি বেছে নিন:", reply_markup=kb
        )

    @dp.message(WithdrawStates.waiting_for_method, F.text.in_({"bKash", "Nagad"}))
    async def withdraw_method(message: Message, state: FSMContext) -> None:
        await state.update_data(method="bkash" if message.text == "bKash" else "nagad")
        await state.set_state(WithdrawStates.waiting_for_account)
        await message.answer(
            "১১ ডিজিটের বিকাশ/নগদ নম্বরটি পাঠান (যেমন: 017XXXXXXXX):", reply_markup=ReplyKeyboardRemove()
        )

    @dp.message(WithdrawStates.waiting_for_method)
    async def withdraw_method_invalid(message: Message) -> None:
        await message.answer("অনুগ্রহ করে নিচের বাটন থেকে bKash অথবা Nagad বেছে নিন।")

    @dp.message(WithdrawStates.waiting_for_account)
    async def withdraw_account(message: Message, state: FSMContext) -> None:
        account_raw = (message.text or "").strip()
        error = bd_mobile_validation_error(account_raw)
        if error:
            await message.answer(f"❌ {error}\n\nআবার সঠিক নম্বরটি পাঠান, যেমন: 017XXXXXXXX")
            return
        await state.update_data(account_number=normalize_bd_mobile_number(account_raw))
        await state.set_state(WithdrawStates.waiting_for_amount)
        await message.answer("কত টাকা তুলতে চান? (শুধু সংখ্যা লিখুন)")

    @dp.message(WithdrawStates.waiting_for_amount)
    async def withdraw_amount(message: Message, state: FSMContext) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        cpm_setting = await storage.get_cpm_setting()
        try:
            amount = float((message.text or "").strip())
        except ValueError:
            await message.answer("সঠিক সংখ্যা লিখুন, যেমন 250 অথবা 250.50")
            return
        if amount <= 0 or amount > admin.balance_confirmed:
            await message.answer(
                f"পরিমাণ অবশ্যই ০ থেকে বড় এবং নিশ্চিত ব্যালেন্সের ({admin.balance_confirmed:.2f}) মধ্যে হতে হবে।"
            )
            return
        if amount < cpm_setting.min_withdraw_amount:
            await message.answer(
                f"সর্বনিম্ন উইথড্র পরিমাণ <b>{cpm_setting.min_withdraw_amount:.2f}</b>। এর কম অ্যামাউন্টে আবেদন করা যাবে না।\n"
                "সঠিক পরিমাণ লিখুন:"
            )
            return
        data = await state.get_data()
        req = await storage.create_withdrawal(
            admin.telegram_id, amount, WithdrawMethod(data["method"]), data["account_number"]
        )
        await state.clear()
        await notify_owner_of_withdrawal(message.bot, settings, admin, req)
        panel_url = f"{settings.WEBAPP_BASE_URL}/panel"
        await message.answer(
            f"✅ আবেদন গ্রহণ করা হয়েছে (ID: <code>{req.request_id[:8]}</code>)।\n"
            "Owner-কে সাথে সাথে জানানো হয়েছে — তিনি যাচাই করে টাকা পাঠাবেন।",
            reply_markup=_main_menu_keyboard(panel_url),
        )

    # ------------------------------------------------------------------
    # /requestadmin — Sub Admin asks to be promoted to Admin
    # ------------------------------------------------------------------

    @dp.message(Command("requestadmin"))
    async def requestadmin_cmd(message: Message, state: FSMContext) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        if admin.role != Role.SUB_ADMIN:
            if admin.role == Role.ADMIN:
                await message.answer("আপনি ইতিমধ্যে একজন Admin। 🛡️")
            elif admin.role == Role.OWNER:
                await message.answer("আপনি Owner — আপনার এই কমান্ডের দরকার নেই।")
            else:
                await message.answer(
                    "Admin হওয়ার আবেদন করার আগে আপনাকে প্রথমে Sub Admin হতে হবে — "
                    "/trafficsource দিয়ে অন্তত একটি Traffic Source যোগ করুন।"
                )
            return
        if admin.admin_request_status == AdminRequestStatus.PENDING:
            await message.answer("আপনার Admin রিকোয়েস্টটি এখনো Owner-এর কাছে পর্যালোচনাধীন। ফলাফলের জন্য অপেক্ষা করুন।")
            return
        await state.set_state(AdminRequestStates.waiting_for_note)
        await message.answer(
            "🆙 <b>Admin হওয়ার আবেদন</b>\n\n"
            "আপনার ট্রাফিক সোর্স কতটা শক্তিশালী এবং আপনি কতটা নিয়মিত কাজ করছেন তা সংক্ষেপে লিখুন "
            "(Owner এটি যাচাই করে সিদ্ধান্ত নেবেন)। বার্তা ছাড়া পাঠাতে চাইলে <code>skip</code> লিখুন।"
        )

    @dp.message(AdminRequestStates.waiting_for_note)
    async def requestadmin_note_received(message: Message, state: FSMContext) -> None:
        raw = (message.text or "").strip()
        note = None if raw.lower() == "skip" else raw
        await state.clear()
        admin = await storage.submit_admin_request(message.from_user.id, note)
        if not admin:
            await message.answer("দুঃখিত, কিছু একটা ভুল হয়েছে — আবার /requestadmin দিয়ে চেষ্টা করুন।")
            return
        stats = await storage.admin_stats(message.from_user.id)
        await notify_owner_of_admin_request(message.bot, settings, admin, note, stats)
        panel_url = f"{settings.WEBAPP_BASE_URL}/panel"
        await message.answer(
            "✅ আপনার Admin রিকোয়েস্ট Owner-এর কাছে পাঠানো হয়েছে। ফলাফল জানানো হবে।",
            reply_markup=_main_menu_keyboard(panel_url),
        )

    @dp.callback_query(F.data.startswith(ADMIN_REQUEST_APPROVE_PREFIX))
    async def admin_request_approve_cb(callback: CallbackQuery) -> None:
        if callback.from_user.id != settings.OWNER_TELEGRAM_ID:
            await callback.answer("শুধুমাত্র Owner এই সিদ্ধান্ত নিতে পারবেন।", show_alert=True)
            return
        telegram_id = int((callback.data or "").rsplit(":", 1)[1])
        admin = await storage.resolve_admin_request(telegram_id, approve=True, reason=None, resolved_by=callback.from_user.id)
        if not admin:
            await callback.answer("এই রিকোয়েস্টটি আর পেন্ডিং নেই (হয়তো আগেই সমাধান করা হয়েছে)।", show_alert=True)
            return
        await notify_sub_admin_of_admin_request_resolution(callback.bot, admin, approved=True, reason=None)
        await callback.answer("Admin হিসেবে গৃহীত হয়েছে ✅")
        if callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
                who = f"@{admin.username}" if admin.username else f"id {admin.telegram_id}"
                await callback.message.answer(f"✅ {who} এখন Admin।")
            except Exception:
                pass

    @dp.callback_query(F.data.startswith(ADMIN_REQUEST_REJECT_PREFIX))
    async def admin_request_reject_cb(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.from_user.id != settings.OWNER_TELEGRAM_ID:
            await callback.answer("শুধুমাত্র Owner এই সিদ্ধান্ত নিতে পারবেন।", show_alert=True)
            return
        telegram_id = int((callback.data or "").rsplit(":", 1)[1])
        target = await storage.get_admin(telegram_id)
        if not target or target.admin_request_status != AdminRequestStatus.PENDING:
            await callback.answer("এই রিকোয়েস্টটি আর পেন্ডিং নেই (হয়তো আগেই সমাধান করা হয়েছে)।", show_alert=True)
            return
        await state.set_state(AdminReviewStates.waiting_for_reject_reason)
        await state.update_data(reject_telegram_id=telegram_id)
        await callback.answer()
        if callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await callback.message.answer("প্রত্যাখ্যানের কারণ লিখে পাঠান (এটি সাব অ্যাডমিনকে জানানো হবে):")

    @dp.message(AdminReviewStates.waiting_for_reject_reason)
    async def admin_request_reject_reason_received(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        telegram_id = data.get("reject_telegram_id")
        reason = (message.text or "").strip()
        await state.clear()
        if not telegram_id or not reason:
            await message.answer("কারণ পাওয়া যায়নি — কিছু ভুল হয়েছে, প্যানেল থেকে চেষ্টা করুন।")
            return
        admin = await storage.resolve_admin_request(
            int(telegram_id), approve=False, reason=reason, resolved_by=message.from_user.id
        )
        if not admin:
            await message.answer("এই রিকোয়েস্টটি আর পেন্ডিং নেই।")
            return
        await notify_sub_admin_of_admin_request_resolution(message.bot, admin, approved=False, reason=reason)
        panel_url = f"{settings.WEBAPP_BASE_URL}/panel"
        who = f"@{admin.username}" if admin.username else f"id {admin.telegram_id}"
        await message.answer(f"❌ {who}-এর Admin রিকোয়েস্ট প্রত্যাখ্যান করা হয়েছে এবং তাকে জানানো হয়েছে।", reply_markup=_main_menu_keyboard(panel_url))

    # ------------------------------------------------------------------
    # /panel, /help
    # ------------------------------------------------------------------

    @dp.message(Command("panel"))
    async def panel_cmd(message: Message) -> None:
        await _ensure_admin(message.from_user.id, message.from_user.username)
        panel_url = f"{settings.WEBAPP_BASE_URL}/panel?_t={int(datetime.now(timezone.utc).timestamp())}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📊 ড্যাশবোর্ড খুলুন", web_app=WebAppInfo(url=panel_url))]]
        )
        await message.answer("আপনার ড্যাশবোর্ড খুলতে নিচের বাটনে চাপ দিন:", reply_markup=kb)

    @dp.message(Command("help"))
    async def help_cmd(message: Message) -> None:
        panel_url = f"{settings.WEBAPP_BASE_URL}/panel"
        await message.answer(
            "নিচের বাটন থেকে যেকোনো অপশনে ট্যাপ করুন:\n\n"
            "🔗 নতুন লিংক — নতুন শর্ট লিংক তৈরি\n"
            "📡 ট্রাফিক সোর্স — সোর্স যোগ/এডিট/মুছুন\n"
            "💰 ব্যালেন্স — ব্যালেন্স ও পেআউট তথ্য\n"
            "💸 উইথড্র — টাকা তোলার আবেদন\n"
            "🔒 প্রাইভেসি পলিসি — নিয়মাবলী ও শর্তাবলী দেখুন\n"
            "🆙 /requestadmin — Sub Admin থেকে Admin হওয়ার আবেদন করুন\n\n"
            "📊 পূর্ণাঙ্গ ড্যাশবোর্ড খুলতে /panel লিখুন, অথবা চ্যাট বক্সের বাম পাশের মেনু বাটন ব্যবহার করুন।",
            reply_markup=_main_menu_keyboard(panel_url),
        )

    @dp.message(Command("privacy"))
    async def privacy_cmd(message: Message) -> None:
        policy = await storage.get_policy_setting()
        privacy_url = f"{settings.WEBAPP_BASE_URL}/privacy"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🌐 ব্রাউজারে খুলুন", url=privacy_url)]]
        )
        await message.answer(
            f"🔒 <b>প্রাইভেসি পলিসি ও শর্তাবলী</b>\n\n{policy.text}",
            reply_markup=kb,
        )
