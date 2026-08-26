from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.filters import CommandStart, Command
import config
import database

router = Router()

def get_main_keyboard() -> InlineKeyboardMarkup:
    web_app_url = config.WEBAPP_BASE_URL or "https://t.me"
    buttons = [
        [
            InlineKeyboardButton(
                text="🎮 Play Games Now!",
                web_app=WebAppInfo(url=web_app_url)
            )
        ],
        [
            InlineKeyboardButton(text="📊 My Profile & Stats", callback_data="user_profile"),
            InlineKeyboardButton(text="ℹ️ Rules & How to Play", callback_data="user_rules")
        ],
        [
            InlineKeyboardButton(text="🏆 Leaderboard", callback_data="user_leaderboard")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    db_user = await database.get_or_create_user(
        telegram_id=user.id,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        username=user.username or ""
    )

    welcome_text = (
        f"👋 <b>Welcome, {user.first_name}!</b>\n\n"
        f"🕹️ <b>Telegram Arcade Game Hub</b>-এ আপনাকে স্বাগতম!\n\n"
        f"❤️ <b>Current Lives:</b> {db_user['lives']}/{db_user['max_lives']}\n"
        f"🎮 <b>Available Games:</b> Snake, 2048, Flappy Bird, Tic Tac Toe, Memory Match, Whack-a-Mole!\n\n"
        f"💡 <i>Game Rules:</i>\n"
        f"• প্রতিটা খেলায় হারলে বা খেললে ১টি লাইফ খরচ হয়।\n"
        f"• লাইফ শেষ হলে Rewarded Ad দেখে সাথে সাথে +১ ❤️ ফ্রি লাইফ নিতে পারবেন!\n"
        f"• অথবা নির্দিষ্ট সময় পর অটোমেটিক লাইফ রিফিল হবে।\n\n"
        f"👇 নিচে <b>Play Games Now!</b> বাটনে ট্যাপ করে খেলা শুরু করুন!"
    )

    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📖 <b>How to Play & Game System Guide:</b>\n\n"
        "1️⃣ <b>Mini App Launch:</b> 'Play Games Now!' বাটনে ট্যাপ করে সরাসরি গেম হাব ওপেন করুন।\n"
        "2️⃣ <b>Life System (❤️):</b> নতুন ইউজাররা ৩টি লাইফ দিয়ে শুরু করে। গেম ওভার হলে ১টি লাইফ কমে।\n"
        "3️⃣ <b>Refill Lives (📺):</b> লাইফ ০ হলে গেমের ভেতরে 'Watch Ad' অপশনে ক্লিক করে অ্যাড দেখলে সাথে সাথে ১টি লাইফ যুক্ত হবে।\n"
        "4️⃣ <b>Auto-Regen (⏳):</b> প্রতি ৩০ মিনিটে ১টি লাইফ স্বয়ংক্রিয়ভাবে রিফিল হয় (সর্বোচ্চ ৩টি পর্যন্ত)।\n"
        "5️⃣ <b>Leaderboard (🏆):</b> সর্বোচ্চ স্কোর গড়ে লিডারবোর্ডের শীর্ষে পৌঁছান!\n\n"
        "👮‍♂️ <i>প্রয়োজনে কোনো সমস্যার সম্মুখীন হলে অ্যাডমিনের সাথে যোগাযোগ করুন।</i>"
    )
    await message.answer(help_text, reply_markup=get_main_keyboard())

@router.message(Command("play"))
async def cmd_play(message: Message):
    await cmd_start(message)

@router.callback_query(F.data == "user_profile")
async def cb_user_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await database.get_or_create_user(user_id, callback.from_user.first_name, callback.from_user.last_name, callback.from_user.username)
    high_scores = await database.get_user_high_scores(user_id)

    scores_text = "\n".join([f"• <b>{game.upper()}:</b> {score}" for game, score in high_scores.items()]) or "<i>No games played yet!</i>"

    regen_info = f"{user['seconds_until_regen'] // 60}m {user['seconds_until_regen'] % 60}s" if user['lives'] < user['max_lives'] else "Full ❤️"

    text = (
        f"👤 <b>Player Profile:</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
        f"❤️ <b>Current Lives:</b> {user['lives']} / {user['max_lives']}\n"
        f"⏳ <b>Next Free Life in:</b> {regen_info}\n\n"
        f"🏆 <b>Your High Scores:</b>\n{scores_text}\n\n"
        f"🕹️ <i>Keep playing to increase your rank!</i>"
    )
    await callback.message.edit_text(text, reply_markup=get_main_keyboard())
    await callback.answer()

@router.callback_query(F.data == "user_rules")
async def cb_user_rules(callback: CallbackQuery):
    rules_text = (
        "📜 <b>Game Rules & Monetization Policy:</b>\n\n"
        "• প্রতিটি ইউজারের সর্বোচ্চ ৩টি লাইফ থাকে।\n"
        "• লাইফ শেষ হলে Rewarded Ad দেখে অতিরিক্ত লাইফ অর্জন করা যাবে।\n"
        "• প্রতি ৩০ সেকেন্ডে সর্বোচ্চ ১টি অ্যাড দেখে লাইফ ক্লেইম করা যাবে (Anti-spam cooldown)।\n"
        "• ফেয়ার-প্লে নিশ্চিত করতে সব রিওয়ার্ড ও স্কোর সার্ভার সাইড ভেরিফাইড।"
    )
    await callback.message.edit_text(rules_text, reply_markup=get_main_keyboard())
    await callback.answer()

@router.callback_query(F.data == "user_leaderboard")
async def cb_user_leaderboard(callback: CallbackQuery):
    leaderboard = await database.get_leaderboard("all", limit=10)
    if not leaderboard:
        lb_text = "🏆 <b>Leaderboard:</b>\n\n<i>No scores recorded yet. Be the first!</i>"
    else:
        lb_text = "🏆 <b>Top Players (Overall High Scores):</b>\n━━━━━━━━━━━━━━━━━━\n"
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for row in leaderboard:
            rank_icon = medals[row["rank"] - 1] if row["rank"] <= len(medals) else f"{row['rank']}."
            lb_text += f"{rank_icon} <b>{row['name']}</b>: <code>{row['score']} pts</code> ({row['games_played']} games)\n"

    await callback.message.edit_text(lb_text, reply_markup=get_main_keyboard())
    await callback.answer()
