from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.bot.keyboards.inline import get_tasks_inline_keyboard, get_task_detail_keyboard

router = Router(name="tasks_router")


class TaskVerifyState(StatesGroup):
    waiting_for_code = State()


@router.message(F.text == "🎯 Tasks")
@router.message(Command("tasks"))
async def handle_tasks_list(message: Message, task_service: TaskService):
    user_id = message.from_user.id
    tasks = await task_service.get_user_task_list(user_id)

    if not tasks:
        await message.answer("বর্তমানে কোনো সক্রিয় টাস্ক নেই। অনুগ্রহ করে পরবর্তীতে আবার চেক করুন।")
        return

    text = (
        "🎯 <b>উপলব্ধ টাস্ক সমূহ (Available Tasks)</b>\n\n"
        "নিচের তালিকা থেকে যেকোনো টাস্কে ক্লিক করে সম্পূর্ণ করুন এবং কয়েন রিওয়ার্ড অর্জন করুন:\n"
        "<i>(চিহ্ন: ✅ = ইতিমধ্যে সম্পন্ন | 💰 = রিওয়ার্ড)</i>"
    )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=get_tasks_inline_keyboard(tasks)
    )


@router.callback_query(F.data == "tasks_refresh")
@router.callback_query(F.data == "tasks_back")
async def callback_refresh_tasks(callback: CallbackQuery, task_service: TaskService, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    tasks = await task_service.get_user_task_list(user_id)

    text = (
        "🎯 <b>উপলব্ধ টাস্ক সমূহ (Available Tasks)</b>\n\n"
        "নিচের তালিকা থেকে যেকোনো টাস্কে ক্লিক করে সম্পূর্ণ করুন এবং কয়েন রিওয়ার্ড অর্জন করুন:\n"
        "<i>(চিহ্ন: ✅ = ইতিমধ্যে সম্পন্ন | 💰 = রিওয়ার্ড)</i>"
    )

    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_tasks_inline_keyboard(tasks)
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("task_view:"))
async def callback_task_view(callback: CallbackQuery, task_service: TaskService, user_service: UserService):
    task_id = callback.data.replace("task_view:", "")
    task = await task_service.get_task(task_id)

    if not task:
        await callback.answer("টাস্কটি খুঁজে পাওয়া যায়নি!", show_alert=True)
        return

    user = await user_service.get_user(callback.from_user.id)
    is_completed = task_id in (user.get("completed_tasks", []) if user else [])

    type_name = {
        "channel_join": "📢 চ্যানেল/গ্রুপ জয়েন",
        "link_visit": "🔗 শর্টলিংক ভিজিট",
        "custom": "📝 মাইক্রো টাস্ক"
    }.get(task.get("task_type"), "টাস্ক")

    status_str = "✅ <b>সম্পন্ন হয়েছে</b>" if is_completed else "⏳ <b>বাকি রয়েছে</b>"

    detail_text = (
        f"📋 <b>টাস্ক বিবরণী:</b>\n\n"
        f"📌 <b>শিরোনাম:</b> {task.get('title')}\n"
        f"🏷️ <b>ধরণ:</b> {type_name}\n"
        f"💰 <b>রিওয়ার্ড:</b> <code>+{task.get('reward', 0)}</code> কয়েন\n"
        f"📊 <b>স্ট্যাটাস:</b> {status_str}\n\n"
        f"📝 <b>নির্দেশনা:</b>\n{task.get('description', 'টাস্ক লিংক ওপেন করে সম্পন্ন করুন।')}\n"
    )

    if task.get("task_type") == "link_visit" and task.get("verification_code") and not is_completed:
        detail_text += "\n💡 <i>ভিজিট শেষে প্রাপ্ত কোডটি সাবমিট করে কয়েন ক্লেইম করুন।</i>\n"

    await callback.message.edit_text(
        detail_text,
        parse_mode="HTML",
        reply_markup=get_task_detail_keyboard(task, is_completed)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("task_claim:"))
async def callback_task_claim(
    callback: CallbackQuery,
    task_service: TaskService,
    user_service: UserService,
    bot: Bot,
    state: FSMContext
):
    task_id = callback.data.replace("task_claim:", "")
    task = await task_service.get_task(task_id)
    user_id = callback.from_user.id

    if not task:
        await callback.answer("টাস্কটি পাওয়া যায়নি!", show_alert=True)
        return

    user = await user_service.get_user(user_id)
    if task_id in (user.get("completed_tasks", []) if user else []):
        await callback.answer("আপনি ইতিমধ্যে এই টাস্কটি সম্পন্ন করেছেন!", show_alert=True)
        return

    task_type = task.get("task_type")

    # 1. Telegram Channel Join Verification
    if task_type == "channel_join":
        channel_target = task.get("channel_username")
        if channel_target:
            try:
                chat_member = await bot.get_chat_member(chat_id=channel_target, user_id=user_id)
                # Check status
                if chat_member.status in ["member", "administrator", "creator"]:
                    success, msg, reward = await task_service.complete_task(user_id, task_id)
                    await callback.answer("ভেরিফিকেশন সফল!", show_alert=False)
                    await callback.message.answer(msg, parse_mode="HTML")
                    
                    # Refresh task detail
                    await callback.message.edit_reply_markup(
                        reply_markup=get_task_detail_keyboard(task, is_completed=True)
                    )
                    return
                else:
                    await callback.answer(
                        "⚠️ আপনি এখনো চ্যানেলে জয়েন করেননি! আগে জয়েন করুন তারপর আবার চেষ্টা করুন।",
                        show_alert=True
                    )
                    return
            except Exception as e:
                # If bot is not admin in channel, fallback to instant completion
                success, msg, reward = await task_service.complete_task(user_id, task_id)
                await callback.answer("টাস্ক সম্পন্ন হয়েছে!", show_alert=False)
                await callback.message.answer(msg, parse_mode="HTML")
                await callback.message.edit_reply_markup(
                    reply_markup=get_task_detail_keyboard(task, is_completed=True)
                )
                return

    # 2. Link Visit or Custom task with Verification Code
    if task.get("verification_code"):
        await state.set_state(TaskVerifyState.waiting_for_code)
        await state.update_data(task_id=task_id, correct_code=task.get("verification_code"))
        await callback.answer()
        await callback.message.answer(
            "🔑 অনুগ্রহ করে এই টাস্কের <b>ভেরিফিকেশন কোডটি</b> লিখে মেসেজ পাঠান:\n\n"
            "<i>(বাতিল করতে /cancel লিখুন)</i>",
            parse_mode="HTML"
        )
        return

    # 3. Direct completion tasks
    success, msg, reward = await task_service.complete_task(user_id, task_id)
    await callback.answer("টাস্ক সম্পন্ন হয়েছে!", show_alert=False)
    await callback.message.answer(msg, parse_mode="HTML")
    await callback.message.edit_reply_markup(
        reply_markup=get_task_detail_keyboard(task, is_completed=True)
    )


@router.message(TaskVerifyState.waiting_for_code, Command("cancel"))
async def cancel_code_verification(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("ভেরিফিকেশন প্রক্রিয়া বাতিল করা হয়েছে।")


@router.message(TaskVerifyState.waiting_for_code)
async def process_task_verification_code(
    message: Message,
    state: FSMContext,
    task_service: TaskService
):
    user_data = await state.get_data()
    task_id = user_data.get("task_id")
    correct_code = user_data.get("correct_code")

    entered_code = message.text.strip()

    if entered_code.lower() == str(correct_code).lower().strip():
        await state.clear()
        success, msg, reward = await task_service.complete_task(message.from_user.id, task_id)
        await message.answer(msg, parse_mode="HTML")
    else:
        await message.answer(
            "❌ <b>ভুল ভেরিফিকেশন কোড!</b>\nঅনুগ্রহ করে সঠিক কোডটি পুনরায় লিখুন অথবা বাতিল করতে /cancel লিখুন।",
            parse_mode="HTML"
        )
