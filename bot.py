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

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from models import CountedStatus, CPMMode, Role, WithdrawMethod

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
    waiting_for_platform = State()
    waiting_for_url = State()


class WithdrawStates(StatesGroup):
    waiting_for_method = State()
    waiting_for_account = State()
    waiting_for_amount = State()


def build_bot_and_dispatcher(bot_token: str) -> tuple[Bot, Dispatcher]:
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    return bot, dp


def _gen_short_code(length: int = 7) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choices(alphabet, k=length))


async def notify_owner_of_withdrawal(bot: Bot, settings, admin, req) -> None:
    """Pings the Owner's Telegram chat the moment a withdrawal is
    requested — whether it came from the bot's own /withdraw flow or from
    the panel's withdrawal form — so the Owner never has to go looking
    for it.
    """
    who = f"@{admin.username}" if admin.username else f"id {admin.telegram_id}"
    if admin.traffic_source_url:
        platform = admin.traffic_source_platform or "Source"
        ts_line = f'{platform}: <a href="{admin.traffic_source_url}">{admin.traffic_source_url}</a>'
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


def register_handlers(dp: Dispatcher, storage, settings) -> None:
    async def _ensure_admin(telegram_id: int, username: str | None):
        return await storage.get_or_create_admin(telegram_id, username, settings.OWNER_TELEGRAM_ID)

    async def _create_link_and_reply(message: Message, admin, url: str) -> None:
        code = _gen_short_code()
        while await storage.get_link(code):
            code = _gen_short_code()
        await storage.create_link(code, admin.telegram_id, url)
        short_url = f"https://t.me/{settings.BOT_USERNAME}?start={code}"
        await message.answer(
            f"✅ শর্ট লিংক তৈরি হয়েছে:\n<code>{short_url}</code>\n\n"
            "লিংকটি আপনার Traffic Source-এ (চ্যানেল/গ্রুপ/পোস্ট) শেয়ার করুন। "
            "ভিউয়াররা এতে ক্লিক করলে টেলিগ্রাম বট খুলবে, ৩টি বিজ্ঞাপন দেখাবে, তারপর গন্তব্যে পৌঁছাবে।",
            reply_markup=ReplyKeyboardRemove(),
        )

    # ------------------------------------------------------------------
    # /start
    # ------------------------------------------------------------------

    @dp.message(CommandStart(deep_link=True))
    async def start_with_code(message: Message, command) -> None:
        code = command.args
        await _ensure_admin(message.from_user.id, message.from_user.username)
        link = await storage.get_link(code) if code else None
        if not link:
            await message.answer("এই শর্ট লিংকটি খুঁজে পাওয়া যায়নি বা মেয়াদোত্তীর্ণ।")
            return
        view_url = f"{settings.WEBAPP_BASE_URL}/r/{code}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👉 চালিয়ে যান (৩টি বিজ্ঞাপন দেখুন)", web_app=WebAppInfo(url=view_url))]
            ]
        )
        await message.answer(
            "লিংকটি খুলতে নিচের বাটনে চাপ দিন। ৩টি বিজ্ঞাপন দেখা শেষ হলে আপনি স্বয়ংক্রিয়ভাবে গন্তব্য পেজে পৌঁছে যাবেন।",
            reply_markup=kb,
        )

    @dp.message(CommandStart())
    async def start_plain(message: Message) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        role_label = "Owner" if admin.role == Role.OWNER else "Admin"
        panel_url = f"{settings.WEBAPP_BASE_URL}/panel"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📊 ড্যাশবোর্ড খুলুন", web_app=WebAppInfo(url=panel_url))]]
        )
        await message.answer(
            f"স্বাগতম, {role_label}! 👋\n\n"
            "<b>TGSHORTBOT</b> দিয়ে লিংক শর্ট করুন, শেয়ার করুন, আর প্রতিটি ভিউ থেকে আয় করুন।\n\n"
            "কমান্ডসমূহ:\n"
            "/trafficsource — আপনার ট্রাফিক সোর্স সেট/আপডেট করুন (লিংক তৈরির আগে আবশ্যক)\n"
            "/newlink &lt;url&gt; — নতুন শর্ট লিংক তৈরি করুন\n"
            "/mybalance — ব্যালেন্স ও পেআউট তথ্য দেখুন\n"
            "/withdraw — টাকা তোলার আবেদন করুন\n"
            "/panel — পূর্ণাঙ্গ ড্যাশবোর্ড খুলুন",
            reply_markup=kb,
        )

    # ------------------------------------------------------------------
    # /trafficsource
    # ------------------------------------------------------------------

    @dp.message(Command("trafficsource"))
    async def trafficsource_cmd(message: Message, state: FSMContext) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=label, callback_data=f"ts_platform:{key}")]
                for key, label in TRAFFIC_PLATFORMS
            ]
        )
        current = ""
        if admin.traffic_source_url:
            current = f"\n\nবর্তমান: <b>{admin.traffic_source_platform}</b> — {admin.traffic_source_url}"
        await state.set_state(TrafficSourceStates.waiting_for_platform)
        await message.answer(
            "আপনি যেখান থেকে ভিউয়ার/ট্রাফিক আনবেন সেই প্ল্যাটফর্মটি বেছে নিন:" + current,
            reply_markup=kb,
        )

    @dp.callback_query(TrafficSourceStates.waiting_for_platform, F.data.startswith("ts_platform:"))
    async def trafficsource_platform_chosen(callback: CallbackQuery, state: FSMContext) -> None:
        platform_key = (callback.data or "").split(":", 1)[1]
        label = dict(TRAFFIC_PLATFORMS).get(platform_key, "Other")
        await state.update_data(platform=label)
        await state.set_state(TrafficSourceStates.waiting_for_url)
        if callback.message:
            await callback.message.edit_text(
                f"প্ল্যাটফর্ম: <b>{label}</b>\n\n"
                f"এখন আপনার {label} চ্যানেল/গ্রুপ/প্রোফাইলের লিংকটি পাঠান (যেখানে আপনি শর্ট লিংক শেয়ার করবেন):"
            )
        await callback.answer()

    @dp.message(TrafficSourceStates.waiting_for_url)
    async def trafficsource_url_received(message: Message, state: FSMContext) -> None:
        url = (message.text or "").strip()
        if not url.startswith(("http://", "https://")):
            await message.answer("সঠিক লিংক দিন (http:// বা https:// দিয়ে শুরু হতে হবে)।")
            return
        data = await state.get_data()
        platform = data.get("platform", "Other")
        await storage.set_traffic_source(message.from_user.id, platform, url)
        await state.clear()
        await message.answer(
            f"✅ Traffic Source সংরক্ষণ করা হয়েছে:\n<b>{platform}</b> — {url}\n\n"
            "এখন আপনি /newlink দিয়ে লিংক শর্ট করতে পারবেন।"
        )

    # ------------------------------------------------------------------
    # /newlink
    # ------------------------------------------------------------------

    @dp.message(Command("newlink"))
    async def newlink_cmd(message: Message, command, state: FSMContext) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        if not admin.traffic_source_url:
            await message.answer(
                "লিংক শর্ট করার আগে আপনার <b>Traffic Source</b> সেট করতে হবে — অর্থাৎ আপনি কোথা থেকে "
                "ভিউয়ার আনবেন (টেলিগ্রাম চ্যানেল, ইউটিউব চ্যানেল ইত্যাদির লিংক)।\n\n"
                "/trafficsource কমান্ড দিয়ে এখনই সেট করুন।"
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
        lines = [f"💰 নিশ্চিত ব্যালেন্স: <b>{admin.balance_confirmed:.2f}</b>"]

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
            lines.append("ℹ️ পেমেন্টের চূড়ান্ত রেট পেআউটের মুহূর্তে নির্ধারিত হয়।")
        else:
            lines.append(f"📈 বর্তমান CPM (Real-time): {cpm_setting.current_cpm:.4f}")

        await message.answer("\n".join(lines))

    # ------------------------------------------------------------------
    # /withdraw
    # ------------------------------------------------------------------

    @dp.message(Command("withdraw"))
    async def withdraw_cmd(message: Message, state: FSMContext) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
        if admin.balance_confirmed <= 0:
            await message.answer("তোলার মতো কোনো নিশ্চিত ব্যালেন্স নেই।")
            return
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="bKash"), KeyboardButton(text="Nagad")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await state.set_state(WithdrawStates.waiting_for_method)
        await message.answer(f"নিশ্চিত ব্যালেন্স: {admin.balance_confirmed:.2f}\nপদ্ধতি বেছে নিন:", reply_markup=kb)

    @dp.message(WithdrawStates.waiting_for_method, F.text.in_({"bKash", "Nagad"}))
    async def withdraw_method(message: Message, state: FSMContext) -> None:
        await state.update_data(method="bkash" if message.text == "bKash" else "nagad")
        await state.set_state(WithdrawStates.waiting_for_account)
        await message.answer("অ্যাকাউন্ট নম্বর পাঠান:", reply_markup=ReplyKeyboardRemove())

    @dp.message(WithdrawStates.waiting_for_method)
    async def withdraw_method_invalid(message: Message) -> None:
        await message.answer("অনুগ্রহ করে নিচের বাটন থেকে bKash অথবা Nagad বেছে নিন।")

    @dp.message(WithdrawStates.waiting_for_account)
    async def withdraw_account(message: Message, state: FSMContext) -> None:
        account = (message.text or "").strip()
        if not account:
            await message.answer("সঠিক অ্যাকাউন্ট নম্বর পাঠান:")
            return
        await state.update_data(account_number=account)
        await state.set_state(WithdrawStates.waiting_for_amount)
        await message.answer("কত টাকা তুলতে চান? (শুধু সংখ্যা লিখুন)")

    @dp.message(WithdrawStates.waiting_for_amount)
    async def withdraw_amount(message: Message, state: FSMContext) -> None:
        admin = await _ensure_admin(message.from_user.id, message.from_user.username)
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
        data = await state.get_data()
        req = await storage.create_withdrawal(
            admin.telegram_id, amount, WithdrawMethod(data["method"]), data["account_number"]
        )
        await state.clear()
        await notify_owner_of_withdrawal(message.bot, settings, admin, req)
        await message.answer(
            f"✅ আবেদন গ্রহণ করা হয়েছে (ID: <code>{req.request_id[:8]}</code>)।\n"
            "Owner-কে সাথে সাথে জানানো হয়েছে — তিনি যাচাই করে টাকা পাঠাবেন।",
            reply_markup=ReplyKeyboardRemove(),
        )

    # ------------------------------------------------------------------
    # /panel, /help
    # ------------------------------------------------------------------

    @dp.message(Command("panel"))
    async def panel_cmd(message: Message) -> None:
        await _ensure_admin(message.from_user.id, message.from_user.username)
        panel_url = f"{settings.WEBAPP_BASE_URL}/panel"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📊 ড্যাশবোর্ড খুলুন", web_app=WebAppInfo(url=panel_url))]]
        )
        await message.answer("আপনার ড্যাশবোর্ড খুলতে নিচের বাটনে চাপ দিন:", reply_markup=kb)

    @dp.message(Command("help"))
    async def help_cmd(message: Message) -> None:
        await message.answer(
            "কমান্ডসমূহ:\n"
            "/trafficsource — ট্রাফিক সোর্স সেট/আপডেট করুন\n"
            "/newlink &lt;url&gt; — নতুন শর্ট লিংক তৈরি\n"
            "/mybalance — ব্যালেন্স ও পেআউট তথ্য\n"
            "/withdraw — টাকা তোলার আবেদন\n"
            "/panel — পূর্ণাঙ্গ ড্যাশবোর্ড খুলুন"
        )
