from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from app.services.user_service import UserService
from app.services.task_service import TaskService
from datetime import datetime

router = Router(name="profile_router")


@router.message(F.text == "👤 Profile & Balance")
@router.message(Command("profile"))
@router.message(Command("balance"))
async def handle_profile(message: Message, user_service: UserService, task_service: TaskService):
    user_id = message.from_user.id
    user = await user_service.get_user(user_id)
    if not user:
        await message.answer("ব্যবহারকারীর প্রোফাইল পাওয়া যায়নি। অনুগ্রহ করে /start চাপুন।")
        return

    joined_date = "N/A"
    if user.get("joined_at"):
        try:
            dt = datetime.fromisoformat(user["joined_at"])
            joined_date = dt.strftime("%d %b %Y, %I:%M %p")
        except Exception:
            joined_date = user["joined_at"]

    completed_count = len(user.get("completed_tasks", []))
    all_tasks = await task_service.get_user_task_list(user_id)
    total_available_tasks = len(all_tasks)

    profile_text = (
        f"👤 <b>ব্যবহারকারীর প্রোফাইল ও ব্যালেন্স</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"👤 <b>নাম:</b> {user.get('first_name', 'N/A')}\n"
        f"📅 <b>যোগদানের তারিখ:</b> {joined_date}\n\n"
        f"💰 <b>বর্তমান কয়েন ব্যালেন্স:</b> <code>{user.get('balance', 0)}</code> কয়েন\n"
        f"📈 <b>সর্বমোট অর্জিত কয়েন:</b> <code>{user.get('total_earned', 0)}</code> কয়েন\n"
        f"👥 <b>মোট সফল রেফারেল:</b> {user.get('referrals_count', 0)} জন\n"
        f"✅ <b>সম্পন্ন করা টাস্ক:</b> {completed_count}/{total_available_tasks} টি\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    await message.answer(profile_text, parse_mode="HTML")


@router.message(F.text == "🎁 Daily Bonus")
@router.message(Command("bonus"))
async def handle_daily_bonus(message: Message, user_service: UserService):
    user_id = message.from_user.id
    success, reply_msg, coins = await user_service.claim_daily_bonus(user_id)
    
    await message.answer(reply_msg, parse_mode="HTML")
