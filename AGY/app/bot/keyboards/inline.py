from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Any


def get_tasks_inline_keyboard(tasks: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    buttons = []
    for t in tasks:
        status_icon = "✅" if t.get("is_completed") else f"💰 +{t.get('reward', 0)}"
        btn_text = f"{t.get('title', 'Task')} [{status_icon}]"
        buttons.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"task_view:{t['task_id']}"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(text="🔄 Refresh List", callback_data="tasks_refresh")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_task_detail_keyboard(task: Dict[str, Any], is_completed: bool) -> InlineKeyboardMarkup:
    buttons = []
    
    # Action button (Visit link or open channel)
    if task.get("target_url"):
        buttons.append([
            InlineKeyboardButton(
                text="🔗 ওপেন করুন (Open Task Link)",
                url=task["target_url"]
            )
        ])
    
    if not is_completed:
        buttons.append([
            InlineKeyboardButton(
                text="✅ ভেরিফাই ও ক্লেইম করুন (Claim Reward)",
                callback_data=f"task_claim:{task['task_id']}"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(text="⬅️ ফিরে যান (Back to Tasks)", callback_data="tasks_back")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_referral_share_keyboard(bot_username: str, referral_link: str) -> InlineKeyboardMarkup:
    share_text = f"🚀 TGSHORT Tasks-এ যোগ দিয়ে ছোট ছোট টাস্ক পূরণ করে কয়েন আর্ন করুন! জয়েন করতে ক্লিক করুন: {referral_link}"
    share_url = f"https://t.me/share/url?url={referral_link}&text={share_text}"
    
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📤 শেয়ার করুন (Share Link)", url=share_url)
            ]
        ]
    )


def get_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ নতুন টাস্ক যোগ করুন", callback_data="admin_task_add"),
                InlineKeyboardButton(text="📋 টাস্ক লিস্ট ও ম্যানেজ", callback_data="admin_task_list")
            ],
            [
                InlineKeyboardButton(text="📊 সামগ্রিক পরিসংখ্যান (Stats)", callback_data="admin_stats"),
                InlineKeyboardButton(text="📢 ব্রডকাস্ট মেসেজ", callback_data="admin_broadcast")
            ]
        ]
    )


def get_admin_task_item_keyboard(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑️ ডিলিট করুন (Delete)", callback_data=f"admin_task_del:{task_id}")
            ],
            [
                InlineKeyboardButton(text="⬅️ ব্যাক (Back)", callback_data="admin_task_list")
            ]
        ]
    )
