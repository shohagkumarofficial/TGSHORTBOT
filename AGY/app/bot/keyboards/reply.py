from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from typing import List


def get_main_menu(user_id: int, admin_ids: List[int]) -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="🎯 Tasks"),
            KeyboardButton(text="🎁 Daily Bonus")
        ],
        [
            KeyboardButton(text="👤 Profile & Balance"),
            KeyboardButton(text="👥 Refer & Earn")
        ],
        [
            KeyboardButton(text="🏆 Leaderboard"),
            KeyboardButton(text="ℹ️ Help & FAQ")
        ]
    ]

    # Add Admin Panel button if user is an admin
    if user_id in admin_ids:
        keyboard.append([KeyboardButton(text="⚙️ Admin Panel")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        persistent=True
    )
