from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from app.config import settings
from app.services.user_service import UserService
from app.bot.keyboards.reply import get_main_menu
from app.bot.keyboards.inline import get_referral_share_keyboard

router = Router(name="start_router")


@router.message(CommandStart())
async def cmd_start(message: Message, user_service: UserService):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "বন্ধু"
    
    # Extract referral code from /start argument
    args = message.text.split(maxsplit=1)
    referrer_id = None
    if len(args) > 1:
        ref_arg = args[1].strip()
        if ref_arg.startswith("ref_"):
            ref_arg = ref_arg.replace("ref_", "")
        if ref_arg.isdigit():
            referrer_id = int(ref_arg)

    user, is_new = await user_service.get_or_create_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        referrer_id=referrer_id
    )

    welcome_text = (
        f"👋 <b>স্বাগতম, {user_name}!</b>\n\n"
        f"<b>TGSHORT Tasks</b> এ আপনাকে স্বাগতম! এখানে আপনি সহজ ও ছোট ছোট কিছু টাস্ক পূরণ করে "
        f"কয়েন অর্জন করতে পারবেন।\n\n"
        f"💰 <b>আপনার বর্তমান ব্যালেন্স:</b> <code>{user.get('balance', 0)}</code> কয়েন\n"
    )

    if is_new and referrer_id:
        welcome_text += f"\n🎁 আপনি রেফারেল লিংকের মাধ্যমে জয়েন করায় <b>+{settings.REFEREE_BONUS_COINS} কয়েন</b> বোনাস পেয়েছেন!\n"

    welcome_text += "\nশুরু করতে নিচের মেনু বাটন ব্যবহার করুন 👇"

    await message.answer(
        welcome_text,
        parse_mode="HTML",
        reply_markup=get_main_menu(user_id, settings.admin_ids)
    )


@router.message(F.text == "👥 Refer & Earn")
async def handle_referral(message: Message, user_service: UserService):
    bot_info = await message.bot.get_me()
    user_id = message.from_user.id
    user = await user_service.get_user(user_id)
    
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    ref_count = user.get("referrals_count", 0) if user else 0

    text = (
        f"👥 <b>রেফারেল প্রোগ্রাম (Refer & Earn)</b>\n\n"
        f"আপনার বন্ধুদের ইনভাইট করুন এবং প্রতিটি ভ্যালিড রেফারেলে পান <b>+{settings.REFERRAL_BONUS_COINS} কয়েন</b>!\n"
        f"আপনার বন্ধুও জয়েন করলেই পাবে <b>+{settings.REFEREE_BONUS_COINS} কয়েন</b> ওয়েলকাম বোনাস।\n\n"
        f"📊 <b>আপনার মোট রেফারেল:</b> {ref_count} জন\n\n"
        f"🔗 <b>আপনার ইউনিক রেফারেল লিংক:</b>\n"
        f"<code>{ref_link}</code>\n"
    )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=get_referral_share_keyboard(bot_info.username, ref_link)
    )


@router.message(F.text == "🏆 Leaderboard")
async def handle_leaderboard(message: Message, user_service: UserService):
    top_users = await user_service.get_top_users(limit=10)
    
    text = "🏆 <b>সেরা ১০ জন লিডারবোর্ড (Top Earners)</b>\n\n"
    if not top_users:
        text += "এখনও কোনো লিডারবোর্ড ডাটা নেই।"
    else:
        for idx, u in enumerate(top_users, start=1):
            name = u.get("first_name") or f"User_{u.get('user_id')}"
            balance = u.get("balance", 0)
            medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
            text += f"{medal} <b>{name}</b> — <code>{balance}</code> কয়েন\n"

    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "ℹ️ Help & FAQ")
@router.message(Command("help"))
async def handle_help(message: Message):
    help_text = (
        f"ℹ️ <b>TGSHORT Tasks সহায়তা ও নির্দেশিকা</b>\n\n"
        f"<b>১. কয়েন কিভাবে আয় করবেন?</b>\n"
        f"• 🎯 <b>Tasks:</b> বিভিন্ন চ্যানেল জয়েন বা শর্টলিংক ভিজিট টাস্ক পূরণ করে।\n"
        f"• 🎁 <b>Daily Bonus:</b> প্রতিদিন একবার ফ্রি বোনাস ক্লেইম করে।\n"
        f"• 👥 <b>Refer & Earn:</b> বন্ধুদের রেফারেল লিংকের মাধ্যমে জয়েন করিয়ে।\n\n"
        f"<b>২. ব্যালেন্স কিভাবে দেখবেন?</b>\n"
        f"• 👤 <b>Profile & Balance</b> বাটনে চাপ দিয়ে আপনার বর্তমান ও মোট অর্জিত কয়েন দেখতে পারেন।\n\n"
        f"কোনো সমস্যা হলে অ্যাডমিনদের সাথে যোগাযোগ করুন।"
    )
    await message.answer(help_text, parse_mode="HTML")
