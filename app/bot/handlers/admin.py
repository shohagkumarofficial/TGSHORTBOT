from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from app.config import settings
from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.bot.keyboards.inline import (
    get_admin_dashboard_keyboard,
    get_admin_task_item_keyboard
)

router = Router(name="admin_router")


class AddTaskState(StatesGroup):
    title = State()
    description = State()
    task_type = State()
    target_url = State()
    channel_or_code = State()
    reward = State()


class BroadcastState(StatesGroup):
    message = State()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


@router.message(F.text == "⚙️ Admin Panel")
@router.message(Command("admin"))
async def handle_admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ আপনার এই কমান্ডটি ব্যবহারের অনুমতি নেই।")
        return

    await message.answer(
        "⚙️ <b>TGSHORT Tasks অ্যাডমিন কন্ট্রোল প্যানেল</b>\n\n"
        "নিচের অপশনগুলো থেকে প্রয়োজনীয় কাজ নির্বাচন করুন:",
        parse_mode="HTML",
        reply_markup=get_admin_dashboard_keyboard()
    )


@router.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery, user_service: UserService, task_service: TaskService):
    if not is_admin(callback.from_user.id):
        await callback.answer("অনুমতি নেই!", show_alert=True)
        return

    user_stats = await user_service.get_stats()
    all_tasks = await task_service.get_user_task_list(callback.from_user.id)
    total_tasks = len(all_tasks)

    stats_text = (
        f"📊 <b>সিস্টেম পরিসংখ্যান (System Stats)</b>\n\n"
        f"👥 মোট ব্যবহারকারী: <b>{user_stats.get('total_users', 0)} জন</b>\n"
        f"🎯 সক্রিয় টাস্ক: <b>{total_tasks} টি</b>\n"
        f"💰 মোট বণ্টিত কয়েন: <b>{user_stats.get('total_coins_distributed', 0)} কয়েন</b>\n"
    )

    await callback.message.answer(stats_text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_task_list")
async def callback_admin_task_list(callback: CallbackQuery, task_service: TaskService):
    if not is_admin(callback.from_user.id):
        await callback.answer("অনুমতি নেই!", show_alert=True)
        return

    tasks = await task_service.get_user_task_list(callback.from_user.id)
    if not tasks:
        await callback.message.answer("বর্তমানে কোনো টাস্ক নেই।")
        await callback.answer()
        return

    for t in tasks:
        item_text = (
            f"📌 <b>{t.get('title')}</b>\n"
            f"🆔 <code>{t.get('task_id')}</code>\n"
            f"💰 রিওয়ার্ড: +{t.get('reward')} কয়েন | ধরণ: {t.get('task_type')}\n"
            f"🔗 লিংক: {t.get('target_url')}"
        )
        await callback.message.answer(
            item_text,
            parse_mode="HTML",
            reply_markup=get_admin_task_item_keyboard(t["task_id"])
        )

    await callback.answer()


@router.callback_query(F.data.startswith("admin_task_del:"))
async def callback_admin_task_delete(callback: CallbackQuery, task_service: TaskService):
    if not is_admin(callback.from_user.id):
        await callback.answer("অনুমতি নেই!", show_alert=True)
        return

    task_id = callback.data.replace("admin_task_del:", "")
    deleted = await task_service.delete_task(task_id)

    if deleted:
        await callback.message.edit_text(f"✅ টাস্ক (ID: <code>{task_id}</code>) সফলভাবে ডিলিট করা হয়েছে।", parse_mode="HTML")
    else:
        await callback.answer("টাস্ক ডিলিট করা যায়নি বা পাওয়া যায়নি।", show_alert=True)


# --- Add Task Flow ---
@router.callback_query(F.data == "admin_task_add")
async def callback_admin_task_add_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("অনুমতি নেই!", show_alert=True)
        return

    await state.set_state(AddTaskState.title)
    await callback.message.answer(
        "➕ <b>নতুন টাস্ক যোগ করুন</b>\n\n"
        "ধাপ ১/৫: টাস্কের <b>শিরোনাম (Title)</b> লিখুন:\n"
        "<i>(বাতিল করতে /cancel লিখুন)</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AddTaskState.title, Command("cancel"))
@router.message(AddTaskState.description, Command("cancel"))
@router.message(AddTaskState.task_type, Command("cancel"))
@router.message(AddTaskState.target_url, Command("cancel"))
@router.message(AddTaskState.channel_or_code, Command("cancel"))
@router.message(AddTaskState.reward, Command("cancel"))
@router.message(BroadcastState.message, Command("cancel"))
async def cancel_admin_fsm(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ অ্যাকশন বাতিল করা হয়েছে।")


@router.message(AddTaskState.title)
async def process_task_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddTaskState.description)
    await message.answer("ধাপ ২/৫: টাস্কের <b>সংক্ষিপ্ত বিবরণ (Description)</b> লিখুন:")


@router.message(AddTaskState.description)
async def process_task_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddTaskState.task_type)
    
    type_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📢 Channel Join", callback_data="type:channel_join"),
                InlineKeyboardButton(text="🔗 Link Visit", callback_data="type:link_visit")
            ],
            [
                InlineKeyboardButton(text="📝 Custom / Other", callback_data="type:custom")
            ]
        ]
    )
    await message.answer("ধাপ ৩/৫: টাস্কের <b>ধরণ (Type)</b> নির্বাচন করুন:", reply_markup=type_kb)


@router.callback_query(AddTaskState.task_type, F.data.startswith("type:"))
async def process_task_type(callback: CallbackQuery, state: FSMContext):
    t_type = callback.data.replace("type:", "")
    await state.update_data(task_type=t_type)
    await state.set_state(AddTaskState.target_url)
    await callback.message.answer(
        "ধাপ ৪/৫: টাস্কের <b>টার্গেট URL বা লিংক</b> দিন:\n(যেমন: <code>https://t.me/your_channel</code> বা শর্টলিংক)",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AddTaskState.target_url)
async def process_task_url(message: Message, state: FSMContext):
    await state.update_data(target_url=message.text.strip())
    user_data = await state.get_data()
    t_type = user_data.get("task_type")

    await state.set_state(AddTaskState.channel_or_code)
    if t_type == "channel_join":
        await message.answer(
            "ধাপ ৫ (ক): চ্যানেলের <b>ইউজারনেম</b> দিন (যেমন: <code>@mychannel</code>):\n(না থাকলে 'none' লিখুন)",
            parse_mode="HTML"
        )
    elif t_type == "link_visit":
        await message.answer(
            "ধাপ ৫ (খ): ব্যবহারকারীকে পূরণ করতে হবে এমন <b>ভেরিফিকেশন সিক্রেট কোড</b> দিন:\n(কোড ছাড়া অটো-ক্লেইম হলে 'none' লিখুন)"
        )
    else:
        await message.answer("ধাপ ৫ (গ): কোনো ভেরিফিকেশন কোড থাকলে দিন (না থাকলে 'none' লিখুন):")


@router.message(AddTaskState.channel_or_code)
async def process_task_extra(message: Message, state: FSMContext):
    val = message.text.strip()
    user_data = await state.get_data()
    t_type = user_data.get("task_type")

    channel_username = None
    verification_code = None

    if val.lower() != "none":
        if t_type == "channel_join":
            channel_username = val
        else:
            verification_code = val

    await state.update_data(channel_username=channel_username, verification_code=verification_code)
    await state.set_state(AddTaskState.reward)
    await message.answer("শেষ ধাপ: এই টাস্ক সম্পন্ন করলে ইউজার কত <b>কয়েন রিওয়ার্ড</b> পাবে? (সংখ্যায় লিখুন, যেমন: 50)")


@router.message(AddTaskState.reward)
async def process_task_reward(message: Message, state: FSMContext, task_service: TaskService):
    if not message.text.isdigit():
        await message.answer("⚠️ অনুগ্রহ করে শুধুমাত্র পূর্ণসংখ্যা লিখুন (যেমন: 50, 100):")
        return

    reward = int(message.text)
    data = await state.get_data()
    await state.clear()

    new_task = await task_service.create_task(
        title=data.get("title"),
        description=data.get("description"),
        task_type=data.get("task_type"),
        reward=reward,
        target_url=data.get("target_url"),
        channel_username=data.get("channel_username"),
        verification_code=data.get("verification_code")
    )

    await message.answer(
        f"✅ <b>টাস্ক সফলভাবে তৈরি করা হয়েছে!</b>\n\n"
        f"📌 <b>Title:</b> {new_task['title']}\n"
        f"💰 <b>Reward:</b> {new_task['reward']} কয়েন\n"
        f"🆔 <b>ID:</b> <code>{new_task['task_id']}</code>",
        parse_mode="HTML"
    )


# --- Broadcast Flow ---
@router.callback_query(F.data == "admin_broadcast")
async def callback_admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("অনুমতি নেই!", show_alert=True)
        return

    await state.set_state(BroadcastState.message)
    await callback.message.answer(
        "📢 <b>সকল ব্যবহারকারীকে ব্রডকাস্ট মেসেজ পাঠান</b>\n\n"
        "যে মেসেজটি পাঠাতে চান তা লিখে সেন্ড করুন:\n"
        "<i>(বাতিল করতে /cancel লিখুন)</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(BroadcastState.message)
async def process_broadcast_message(
    message: Message,
    state: FSMContext,
    user_service: UserService,
    bot: Bot
):
    await state.clear()
    all_users = await user_service.storage.get_all_users()
    total_recipients = len(all_users)

    status_msg = await message.answer(f"⏳ ব্রডকাস্ট পাঠানো শুরু হচ্ছে ({total_recipients} জন ইউজার)...")
    success_count = 0
    fail_count = 0

    for user_id_str in all_users.keys():
        try:
            await bot.send_message(
                chat_id=int(user_id_str),
                text=message.text,
                parse_mode="HTML"
            )
            success_count += 1
        except Exception:
            fail_count += 1

    await status_msg.edit_text(
        f"✅ <b>ব্রডকাস্ট সম্পন্ন!</b>\n\n"
        f"সফল: {success_count} জন\n"
        f"ব্যর্থ: {fail_count} জন",
        parse_mode="HTML"
    )
