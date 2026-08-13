import html
import logging
import random
import re
import string
from datetime import datetime, timezone

from aiogram import Router, types, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    ReplyKeyboardMarkup, KeyboardButton
)

from models import Admin, Link, WithdrawRequest

logger = logging.getLogger(__name__)
router = Router()

# These will be set by app.py on startup
storage = None
cpm_engine = None
config = None
bot_username = None

# Temporary user withdrawal state
user_withdraw_state = {}


def setup(storage_ref, cpm_engine_ref, config_ref, bot_uname):
    """Initialize module-level references from app.py."""
    global storage, cpm_engine, config, bot_username
    storage = storage_ref
    cpm_engine = cpm_engine_ref
    config = config_ref
    bot_username = bot_uname


def get_main_keyboard(base_url: str):
    """Creates a persistent reply keyboard for easy 1-tap bot navigation."""
    panel_url = f"{base_url}/panel" if base_url else "https://example.com"
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔗 নতুন লিংক তৈরি"),
                KeyboardButton(text="📊 আমার লিংকসমূহ")
            ],
            [
                KeyboardButton(text="💰 ব্যালেন্স"),
                KeyboardButton(text="💸 উইথড্র")
            ],
            [
                KeyboardButton(text="💻 ড্যাশবোর্ড", web_app=WebAppInfo(url=panel_url)),
                KeyboardButton(text="❓ সাহায্য")
            ]
        ],
        resize_keyboard=True,
        persistent=True
    )


async def ensure_admin(message: types.Message) -> Admin:
    """Auto-registers a Telegram user as admin/owner if they don't exist in storage.
    Returns the Admin object."""
    telegram_id = message.from_user.id
    admin = storage.get_admin(telegram_id)
    is_owner = (int(telegram_id) == int(config.OWNER_TELEGRAM_ID)) if config else False

    if not admin:
        admin = Admin(
            telegram_id=telegram_id,
            username=message.from_user.username,
            full_name=message.from_user.full_name or "Unknown",
            role="owner" if is_owner else "admin",
            balance_confirmed=50.0,
            balance_pending=10.0
        )
        storage.upsert_admin(admin)
    else:
        if admin.balance_confirmed == 0.0 and admin.balance_pending == 0.0:
            admin.balance_confirmed = 50.0
            admin.balance_pending = 10.0
            storage.upsert_admin(admin)

        if is_owner and admin.role != "owner":
            admin.role = "owner"
            storage.upsert_admin(admin)

    return admin


@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: types.Message, command: CommandObject):
    """Handle /start with a deep-link parameter (viewer clicking a short link)."""
    await ensure_admin(message)
    short_code = command.args

    if not short_code:
        await message.answer("❌ কোনো লিংক কোড পাওয়া যায়নি!")
        return

    link = storage.get_link(short_code)
    if not link:
        await message.answer("❌ লিংকটি পাওয়া যায়নি!")
        return

    webapp_url = f"{config.WEBAPP_BASE_URL}/r/{short_code}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 লিংক ওপেন করুন", web_app=WebAppInfo(url=webapp_url))]
    ])
    await message.answer("🎬 লিংকটি দেখতে নিচের বাটনে ক্লিক করুন:", reply_markup=kb)


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    """Handle /start without deep-link — normal registration and welcome."""
    admin = await ensure_admin(message)
    role_title = "👑 Owner (মালিক)" if admin.role == "owner" else "👤 Admin"
    cpm_info = cpm_engine.get_cycle_info() if cpm_engine else {}
    current_cpm = cpm_info.get("cpm", 0.50)
    
    welcome_text = (
        f"👋 <b>স্বাগতম, {html.escape(message.from_user.first_name)}!</b> ({role_title})\n\n"
        f"আমি আপনার টেলিগ্রাম লিংক শর্টনার বট।\n"
        f"📈 <b>বর্তমান সিপিএম রেট:</b> ${current_cpm:.2f} / ১০০০ ভিউ\n\n"
        "নিচের বাটনগুলো ব্যবহার করে খুব সহজেই লিংক তৈরি ও আয় ম্যানেজ করুন:\n\n"
        "🔗 <b>নতুন লিংক তৈরি:</b> যেকোনো লিংক পেস্ট করুন বা বাটনে চাপুন\n"
        "📊 <b>আমার লিংকসমূহ:</b> আপনার তৈরি করা সব লিংক\n"
        "💰 <b>ব্যালেন্স:</b> আপনার উপার্জিত ডলার\n"
        "💸 <b>উইথড্র:</b> বিকাশ/নগদে বাটন চেপে টাকা তুলুন\n"
        "💻 <b>ড্যাশবোর্ড:</b> ড্যাশবোর্ড ওপেন করুন"
    )
    reply_kb = get_main_keyboard(config.WEBAPP_BASE_URL if config else "")
    await message.answer(welcome_text, reply_markup=reply_kb)


# Button text handlers for Reply Keyboard
@router.message(F.text == "🔗 নতুন লিংক তৈরি")
async def btn_new_link_prompt(message: types.Message):
    await ensure_admin(message)
    msg = (
        "🔗 <b>নতুন শর্ট লিংক তৈরি করতে:</b>\n\n"
        "যেকোনো ডেসটিনেশন URL এই চ্যাটে সরাসরি পেস্ট করুন (যেমন: <code>https://example.com/file</code>)।"
    )
    await message.answer(msg)


@router.message(F.text == "📊 আমার লিংকসমূহ")
async def btn_mylinks(message: types.Message):
    await cmd_mylinks(message)


@router.message(F.text == "💰 ব্যালেন্স")
async def btn_mybalance(message: types.Message):
    await cmd_mybalance(message)


@router.message(F.text == "💸 উইথড্র")
@router.message(Command("withdraw"))
async def btn_withdraw_prompt(message: types.Message):
    admin = await ensure_admin(message)
    cpm_info = cpm_engine.get_cycle_info() if cpm_engine else {}
    min_withdrawal = cpm_info.get("min_withdrawal_amount", 50.0)
    payout_hours = cpm_info.get("payout_processing_hours", 24)
    current_cpm = cpm_info.get("cpm", 0.50)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 bKash (বিকাশ)", callback_data="wselect_bkash"),
            InlineKeyboardButton(text="📙 Nagad (নগদ)", callback_data="wselect_nagad")
        ]
    ])

    msg = (
        f"💸 <b>উইথড্র পেমেন্ট অপশন</b>\n\n"
        f"💰 <b>আপনার কনফার্মড ব্যালেন্স:</b> ${admin.balance_confirmed:.4f}\n"
        f"📌 <b>মিনিমাম উইথড্র লিমিট:</b> ${min_withdrawal:.2f}\n"
        f"📈 <b>বর্তমান সিপিএম রেট:</b> ${current_cpm:.2f} / ১০০০ ভিউ\n"
        f"⏱️ <b>পেমেন্ট প্রসেসিং সময়:</b> {payout_hours} ঘণ্টার মধ্যে\n\n"
        f"👇 <b>টাকা তুলতে নিচে থেকে আপনার পেমেন্ট মেথড সিলেক্ট করুন:</b>"
    )
    await message.answer(msg, reply_markup=kb)


@router.callback_query(F.data.startswith("wselect_"))
async def cb_withdraw_select(callback: types.CallbackQuery):
    method = callback.data.split("_")[1] # 'bkash' or 'nagad'
    telegram_id = callback.from_user.id
    admin = storage.get_admin(telegram_id)
    cpm_info = cpm_engine.get_cycle_info() if cpm_engine else {}
    min_withdrawal = cpm_info.get("min_withdrawal_amount", 50.0)

    if not admin or admin.balance_confirmed < min_withdrawal:
        await callback.answer(f"❌ আপনার পর্যাপ্ত ব্যালেন্স নেই! ন্যূনতম উইথড্র লিমিট: ${min_withdrawal:.2f}", show_alert=True)
        return

    user_withdraw_state[telegram_id] = method
    method_name = "bKash (বিকাশ)" if method == "bkash" else "Nagad (নগদ)"

    await callback.message.edit_text(
        f"📱 <b>{method_name} সিলেক্ট করা হয়েছে!</b>\n\n"
        f"💰 <b>উইথড্র হবে:</b> ${admin.balance_confirmed:.4f}\n\n"
        f"অনুগ্রহ করে আপনার <b>{method_name} একাউন্ট নম্বরটি</b> এই চ্যাটে পাঠিয়ে দিন (যেমন: <code>01712345678</code>):"
    )
    await callback.answer()


@router.message(F.text.regexp(r"^01[3-9]\d{8}$"))
async def handle_phone_number_input(message: types.Message):
    telegram_id = message.from_user.id
    method = user_withdraw_state.get(telegram_id)

    if not method:
        # Just normal number input or start link, ignore
        return

    admin = await ensure_admin(message)
    cpm_info = cpm_engine.get_cycle_info() if cpm_engine else {}
    min_withdrawal = cpm_info.get("min_withdrawal_amount", 50.0)
    payout_hours = cpm_info.get("payout_processing_hours", 24)

    if admin.balance_confirmed < min_withdrawal:
        await message.answer(f"❌ আপনার পর্যাপ্ত ব্যালেন্স নেই। ন্যূনতম উইথড্র: ${min_withdrawal:.2f}")
        user_withdraw_state.pop(telegram_id, None)
        return

    account_number = message.text.strip()
    amount = admin.balance_confirmed

    withdraw_req = WithdrawRequest(
        admin_telegram_id=admin.telegram_id,
        amount=amount,
        method=method,
        account_number=account_number,
        status="pending"
    )
    storage.create_withdraw_request(withdraw_req)
    user_withdraw_state.pop(telegram_id, None)

    method_name = "bKash (বিকাশ)" if method == "bkash" else "Nagad (নগদ)"
    safe_account = html.escape(account_number)

    # Notify Owner on Telegram
    if config and config.OWNER_TELEGRAM_ID:
        try:
            owner_msg = (
                f"🔔 <b>নতুন উইথড্র রিকোয়েস্ট এসেছে!</b>\n\n"
                f"👤 <b>ইউজার Telegram ID:</b> <code>{admin.telegram_id}</code>\n"
                f"💰 <b>পরিমাণ:</b> <b>${amount:.4f}</b>\n"
                f"📱 <b>মেথড:</b> <b>{method_name}</b> (<code>{safe_account}</code>)\n\n"
                f"💻 ওনার ড্যাশবোর্ডে গিয়ে পেমেন্ট এপ্রুভ করুন।"
            )
            await message.bot.send_message(config.OWNER_TELEGRAM_ID, owner_msg)
        except Exception as e:
            logger.error(f"Failed to notify owner: {e}")

    await message.answer(
        f"✅ <b>আপনার উইথড্র রিকোয়েস্ট সফল হয়েছে!</b>\n\n"
        f"💰 <b>পরিমাণ:</b> ${amount:.4f}\n"
        f"📱 <b>মেথড:</b> {method_name} ({safe_account})\n"
        f"⏱️ <b>পেমেন্ট প্রসেসিং সময়:</b> {payout_hours} ঘণ্টার মধ্যে\n\n"
        f"⏳ Owner পেমেন্ট ক্লিয়ার করার পর আপনার একাউন্টে টাকা পৌঁছে যাবে।"
    )


@router.message(F.text == "💻 ড্যাশবোর্ড")
async def btn_panel(message: types.Message):
    await cmd_panel(message)


@router.message(F.text == "❓ সাহায্য")
async def btn_help(message: types.Message):
    await cmd_help(message)


@router.message(Command("newlink"))
async def cmd_newlink(message: types.Message, command: CommandObject):
    """Create a new short link (auto-verified instantly)."""
    admin = await ensure_admin(message)
    target_url = command.args

    if not target_url:
        await message.answer("❌ অনুগ্রহ করে একটি URL দিন। যেমন: <code>/newlink https://example.com</code>\nঅথবা সরাসরি লিংকটি চ্যাটে পেস্ট করুন!")
        return

    await create_and_send_short_link(message, admin, target_url)


# Auto-create short link if user directly sends a URL starting with http:// or https://
@router.message(F.text.startswith("http://") | F.text.startswith("https://"))
async def auto_create_link_from_url(message: types.Message):
    admin = await ensure_admin(message)
    target_url = message.text.strip()
    await create_and_send_short_link(message, admin, target_url)


async def create_and_send_short_link(message: types.Message, admin: Admin, target_url: str):
    if not (target_url.startswith("http://") or target_url.startswith("https://")):
        await message.answer("❌ URL টি সঠিক নয়! (http:// বা https:// দিয়ে শুরু হতে হবে)")
        return

    short_code = ''.join(random.choices(string.ascii_letters + string.digits, k=6))

    link = Link(
        short_code=short_code,
        owner_telegram_id=admin.telegram_id,
        destination_url=target_url,
        verification_status="verified",
    )
    storage.create_link(link)

    short_url = f"https://t.me/{bot_username}?start={short_code}"
    share_url = f"https://t.me/share/url?url={short_url}&text={html.escape('লিংকটি দেখতে নিচের লিংকে ক্লিক করুন:')}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 টেলিগ্রামে শেয়ার করুন", url=share_url)]
    ])

    await message.answer(
        f"✅ <b>আপনার শর্ট লিংক প্রস্তুত! (সরাসরি অ্যাক্টিভ)</b>\n\n"
        f"🔗 <b>কপি করতে টাচ করুন:</b>\n<code>{short_url}</code>\n\n"
        f"💡 লিংকটি যেকোনো চ্যানেল বা গ্রুপে শেয়ার করে ইনকাম শুরু করুন!",
        reply_markup=kb,
        disable_web_page_preview=True
    )


@router.message(Command("mylinks"))
async def cmd_mylinks(message: types.Message):
    """Show all links created by this admin."""
    admin = await ensure_admin(message)
    links = storage.get_links_by_admin(admin.telegram_id)

    if not links:
        await message.answer("📭 আপনি এখনো কোনো লিংক তৈরি করেননি।")
        return

    for link in links:
        short_url = f"https://t.me/{bot_username}?start={link.short_code}"
        share_url = f"https://t.me/share/url?url={short_url}&text={html.escape('লিংকটি দেখতে নিচের লিংকে ক্লিক করুন:')}"
        view_count = storage.count_views_by_link(link.short_code)
        safe_url = html.escape(link.destination_url[:40])

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 শেয়ার করুন", url=share_url)]
        ])

        msg = (
            f"🔹 <b>লিংক কোড:</b> <code>{link.short_code}</code>\n"
            f"   🌐 <b>আসল URL:</b> {safe_url}...\n"
            f"   👁️ <b>ভিউ:</b> {view_count}\n"
            f"   🔗 <b>শর্ট লিংক (কপি করতে টাচ করুন):</b>\n<code>{short_url}</code>"
        )
        await message.answer(msg, reply_markup=kb, disable_web_page_preview=True)


@router.message(Command("mybalance"))
async def cmd_mybalance(message: types.Message):
    """Show admin's balance."""
    admin = await ensure_admin(message)
    cpm_info = cpm_engine.get_cycle_info() if cpm_engine else {}
    current_cpm = cpm_info.get("cpm", 0.50)
    min_withdrawal = cpm_info.get("min_withdrawal_amount", 50.0)
    payout_hours = cpm_info.get("payout_processing_hours", 24)

    response = (
        "💰 <b>আপনার ব্যালেন্স সামারি:</b>\n\n"
        f"✅ <b>কনফার্মড ব্যালেন্স:</b> {admin.balance_confirmed:.4f} $\n"
        f"⏳ <b>পেন্ডিং ব্যালেন্স:</b> {admin.balance_pending:.4f} $\n\n"
        f"📈 <b>বর্তমান সিপিএম রেট:</b> ${current_cpm:.2f} / ১০০০ ভিউ\n"
        f"📌 <b>মিনিমাম উইথড্র:</b> ${min_withdrawal:.2f}\n"
        f"⏱️ <b>পেমেন্ট সময়:</b> {payout_hours} ঘণ্টার মধ্যে"
    )

    if cpm_engine:
        if cpm_info.get("mode") == "scheduled":
            remaining = cpm_info.get("time_remaining_seconds", 0)
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            pending_views = cpm_info.get("pending_views", 0)
            response += (
                f"\n\n📅 <b>পরবর্তী পেআউট:</b> {hours}h {minutes}m পর\n"
                f"👁️ <b>এই সাইকেলে পেন্ডিং ভিউ:</b> {pending_views}"
            )

    await message.answer(response)


@router.message(Command("panel"))
async def cmd_panel(message: types.Message):
    """Open the dashboard Mini App."""
    await ensure_admin(message)
    webapp_url = f"{config.WEBAPP_BASE_URL}/panel"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 ড্যাশবোর্ড ওপেন করুন", web_app=WebAppInfo(url=webapp_url))]
    ])
    await message.answer("📊 আপনার ড্যাশবোর্ড:", reply_markup=kb)


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    """Show help text with all available buttons and commands."""
    help_text = (
        "❓ <b>সাহায্য মেনু</b>\n\n"
        "বটের নিচের বাটনগুলো ব্যবহার করে সবকিছু করতে পারবেন:\n\n"
        "🔗 <b>নতুন লিংক তৈরি:</b> চ্যাটে যেকোনো লিংক পাঠালেই শর্ট লিংক হয়ে যাবে\n"
        "📊 <b>আমার লিংকসমূহ:</b> আপনার সব লিংক ও ভিউ\n"
        "💰 <b>ব্যালেন্স:</b> আপনার উপার্জিত ডলার\n"
        "💸 <b>উইথড্র:</b> বিকাশ/নগদে বাটন চেপে টাকা তুলুন\n"
        "💻 <b>ড্যাশবোর্ড:</b> অ্যাডমিন/ওনার প্যানেল"
    )
    await message.answer(help_text)
