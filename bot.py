import logging
import random
import string
from datetime import datetime, timezone

from aiogram import Router, types, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from models import Admin, Link, WithdrawRequest

logger = logging.getLogger(__name__)
router = Router()

# These will be set by app.py on startup
storage = None
cpm_engine = None
config = None
bot_username = None


def setup(storage_ref, cpm_engine_ref, config_ref, bot_uname):
    """Initialize module-level references from app.py."""
    global storage, cpm_engine, config, bot_username
    storage = storage_ref
    cpm_engine = cpm_engine_ref
    config = config_ref
    bot_username = bot_uname


async def ensure_admin(message: types.Message) -> Admin:
    """Auto-registers a Telegram user as admin if they don't exist in storage.
    Returns the Admin object."""
    telegram_id = message.from_user.id
    admin = storage.get_admin(telegram_id)
    if not admin:
        admin = Admin(
            telegram_id=telegram_id,
            username=message.from_user.username,
            full_name=message.from_user.full_name or "Unknown",
            role="owner" if telegram_id == config.OWNER_TELEGRAM_ID else "admin",
        )
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
    await ensure_admin(message)
    welcome_text = (
        "👋 স্বাগতম! আমি আপনার টেলিগ্রাম লিংক শটনার বট।\n\n"
        "আমার মাধ্যমে আপনি খুব সহজেই লিংক তৈরি করে আয় করতে পারেন।\n\n"
        "উপলব্ধ কমান্ডসমূহ:\n"
        "🔗 /newlink [url] - নতুন শর্ট লিংক তৈরি করুন\n"
        "✅ /proof [code] [proof_url] - প্রুফ সাবমিট করুন\n"
        "📊 /mylinks - আপনার লিংকসমূহ দেখুন\n"
        "💰 /mybalance - আপনার ব্যালেন্স চেক করুন\n"
        "💸 /withdraw [method] [account] - টাকা উত্তোলন করুন\n"
        "💻 /panel - ড্যাশবোর্ড ওপেন করুন\n"
        "❓ /help - সাহায্য"
    )
    await message.answer(welcome_text)


@router.message(Command("newlink"))
async def cmd_newlink(message: types.Message, command: CommandObject):
    """Create a new short link."""
    admin = await ensure_admin(message)
    target_url = command.args

    if not target_url:
        await message.answer("❌ অনুগ্রহ করে একটি URL দিন। ব্যবহারবিধি: /newlink [url]")
        return

    if not (target_url.startswith("http://") or target_url.startswith("https://")):
        await message.answer("❌ URL টি সঠিক নয়! (http:// বা https:// দিয়ে শুরু হতে হবে)")
        return

    short_code = ''.join(random.choices(string.ascii_letters + string.digits, k=6))

    link = Link(
        short_code=short_code,
        owner_telegram_id=admin.telegram_id,
        destination_url=target_url,
    )
    storage.create_link(link)

    short_url = f"https://t.me/{bot_username}?start={short_code}"
    await message.answer(
        f"✅ আপনার শর্ট লিংক সফলভাবে তৈরি হয়েছে!\n\n"
        f"🔗 লিংক: {short_url}\n\n"
        f"⚠️ অনুগ্রহ করে /proof {short_code} [proof_url] কমান্ড ব্যবহার করে প্রুফ জমা দিন।"
    )


@router.message(Command("proof"))
async def cmd_proof(message: types.Message, command: CommandObject):
    """Submit a proof URL for a link."""
    admin = await ensure_admin(message)
    args = command.args

    if not args:
        await message.answer("❌ ব্যবহারবিধি: /proof [short_code] [proof_url]")
        return

    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ ব্যবহারবিধি: /proof [short_code] [proof_url]")
        return

    short_code, proof_url = parts

    link = storage.get_link(short_code)
    if not link:
        await message.answer("❌ লিংকটি পাওয়া যায়নি!")
        return

    if link.owner_telegram_id != admin.telegram_id:
        await message.answer("❌ আপনি এই লিংকের মালিক নন!")
        return

    if not (proof_url.startswith("http://") or proof_url.startswith("https://")):
        await message.answer("❌ প্রুফ URL সঠিক নয়! (http:// বা https:// দিয়ে শুরু হতে হবে)")
        return

    storage.update_link_proof(short_code, proof_url)

    await message.answer("✅ প্রুফ URL সফলভাবে যুক্ত করা হয়েছে। Owner ভেরিফাই করার পর আপনার লিংক সক্রিয় হবে।")


@router.message(Command("mylinks"))
async def cmd_mylinks(message: types.Message):
    """Show all links created by this admin."""
    admin = await ensure_admin(message)
    links = storage.get_links_by_admin(admin.telegram_id)

    if not links:
        await message.answer("📭 আপনি এখনো কোনো লিংক তৈরি করেননি।")
        return

    response = "📊 আপনার লিংকসমূহ:\n\n"
    for link in links:
        status_emoji = {"verified": "✅", "pending": "⏳", "rejected": "❌"}.get(
            link.verification_status, "❓"
        )
        view_count = storage.count_views_by_link(link.short_code)
        response += (
            f"🔹 কোড: <code>{link.short_code}</code>\n"
            f"   🌐 URL: {link.destination_url[:50]}...\n"
            f"   📋 স্ট্যাটাস: {status_emoji} {link.verification_status}\n"
            f"   👁️ ভিউ: {view_count}\n"
            f"   📎 প্রুফ: {'✅ আছে' if link.proof_url else '❌ নেই'}\n\n"
        )

    await message.answer(response)


@router.message(Command("mybalance"))
async def cmd_mybalance(message: types.Message):
    """Show admin's balance."""
    admin = await ensure_admin(message)

    response = (
        "💰 আপনার ব্যালেন্স:\n\n"
        f"✅ নিশ্চিত ব্যালেন্স: {admin.balance_confirmed:.4f} $\n"
        f"⏳ পেন্ডিং ব্যালেন্স: {admin.balance_pending:.4f} $\n"
    )

    # Show cycle info if scheduled mode
    if cpm_engine:
        cycle_info = cpm_engine.get_cycle_info()
        if cycle_info and cycle_info.get("mode") == "scheduled":
            remaining = cycle_info.get("time_remaining_seconds", 0)
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            pending_views = cycle_info.get("pending_view_count", 0)
            response += (
                f"\n📅 পরবর্তী পেআউট: {hours}h {minutes}m পর\n"
                f"👁️ এই সাইকেলে পেন্ডিং ভিউ: {pending_views}"
            )

    await message.answer(response)


@router.message(Command("withdraw"))
async def cmd_withdraw(message: types.Message, command: CommandObject):
    """Request a withdrawal."""
    admin = await ensure_admin(message)
    args = command.args

    if not args:
        await message.answer(
            "❌ ব্যবহারবিধি: /withdraw [method] [account_number]\n"
            "উদাহরণ: /withdraw bkash 01712345678"
        )
        return

    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❌ ব্যবহারবিধি: /withdraw [method] [account_number]\n"
            "উদাহরণ: /withdraw bkash 01712345678"
        )
        return

    method, account_number = parts
    method = method.lower().strip()

    if method not in ("bkash", "nagad"):
        await message.answer("❌ মেথড শুধু bkash বা nagad হতে পারে!")
        return

    min_withdrawal = config.MIN_WITHDRAWAL_AMOUNT if config else 50.0

    if admin.balance_confirmed < min_withdrawal:
        await message.answer(
            f"❌ আপনার পর্যাপ্ত ব্যালেন্স নেই।\n"
            f"💰 বর্তমান ব্যালেন্স: {admin.balance_confirmed:.4f} $\n"
            f"📌 ন্যূনতম উত্তোলন: {min_withdrawal} $"
        )
        return

    amount = admin.balance_confirmed

    withdraw_req = WithdrawRequest(
        admin_telegram_id=admin.telegram_id,
        amount=amount,
        method=method,
        account_number=account_number,
    )
    storage.create_withdraw_request(withdraw_req)

    await message.answer(
        f"✅ আপনার উত্তোলনের অনুরোধ সফলভাবে গ্রহণ করা হয়েছে!\n\n"
        f"💰 পরিমাণ: {amount:.4f} $\n"
        f"📱 মেথড: {method}\n"
        f"📞 অ্যাকাউন্ট: {account_number}\n\n"
        f"⏳ Owner অনুমোদনের পর আপনার অ্যাকাউন্টে পাঠানো হবে।"
    )


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
    """Show help text with all available commands."""
    help_text = (
        "❓ সাহায্য মেনু\n\n"
        "🔗 /newlink [url] - নতুন লিংক তৈরি করুন\n"
        "✅ /proof [code] [proof_url] - ভেরিফিকেশনের জন্য প্রুফ দিন\n"
        "📊 /mylinks - আপনার সব লিংক দেখুন\n"
        "💰 /mybalance - ব্যালেন্স দেখুন\n"
        "💸 /withdraw [method] [account] - ব্যালেন্স উইথড্র করুন\n"
        "💻 /panel - ড্যাশবোর্ড ওপেন করুন\n\n"
        "যেকোনো সমস্যার জন্য Owner-এর সাথে যোগাযোগ করুন।"
    )
    await message.answer(help_text)
