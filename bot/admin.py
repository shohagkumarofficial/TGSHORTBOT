import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import config
import database

router = Router()

class AdminStates(StatesGroup):
    waiting_for_adsgram_id = State()
    waiting_for_monetag_id = State()
    waiting_for_cooldown = State()
    waiting_for_broadcast = State()

def is_admin(user_id: int) -> bool:
    if config.OWNER_TELEGRAM_ID == 0:
        return True
    return user_id == config.OWNER_TELEGRAM_ID

def get_admin_main_kb() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="⚙️ Ad Settings", callback_data="admin_ads"),
            InlineKeyboardButton(text="🎮 Game Manager", callback_data="admin_games")
        ],
        [
            InlineKeyboardButton(text="❤️ Life Settings", callback_data="admin_life"),
            InlineKeyboardButton(text="📊 Statistics", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton(text="📢 Broadcast Message", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ <i>Access denied. This command is restricted to bot administrators.</i>")
        return

    await state.clear()
    text = (
        "👑 <b>Game Bot Admin Control Panel</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Welcome to the master control panel. Choose a management category below:"
    )
    await message.answer(text, reply_markup=get_admin_main_kb())

@router.callback_query(F.data == "admin_main")
async def cb_admin_main(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied", show_alert=True)
        return
    await state.clear()
    text = (
        "👑 <b>Game Bot Admin Control Panel</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Welcome to the master control panel. Choose a management category below:"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_main_kb())
    await callback.answer()

# --- 1. Ad Settings ---

async def get_ad_settings_kb() -> InlineKeyboardMarkup:
    settings = await database.get_all_settings()
    active_net = settings.get("active_ad_network", "both")
    
    ag_check = "✅ " if active_net in ["adsgram", "both"] else ""
    mo_check = "✅ " if active_net in ["monetag", "both"] else ""
    both_check = "✅ " if active_net == "both" else ""

    buttons = [
        [
            InlineKeyboardButton(text=f"Network: Adsgram {ag_check}", callback_data="set_ad_net_adsgram"),
            InlineKeyboardButton(text=f"Monetag {mo_check}", callback_data="set_ad_net_monetag")
        ],
        [
            InlineKeyboardButton(text=f"Network: Both (Round-Robin) {both_check}", callback_data="set_ad_net_both")
        ],
        [
            InlineKeyboardButton(text="✏️ Edit Adsgram Block ID", callback_data="edit_adsgram_id"),
            InlineKeyboardButton(text="✏️ Edit Monetag Zone ID", callback_data="edit_monetag_id")
        ],
        [
            InlineKeyboardButton(text="⏱️ Edit Ad Cooldown", callback_data="edit_ad_cooldown")
        ],
        [
            InlineKeyboardButton(text="🔙 Back to Admin Menu", callback_data="admin_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.callback_query(F.data == "admin_ads")
async def cb_admin_ads(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    settings = await database.get_all_settings()
    text = (
        "⚙️ <b>Ad Network Configuration</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Active Network:</b> <code>{settings.get('active_ad_network', 'both').upper()}</code>\n"
        f"• <b>Adsgram Block ID:</b> <code>{settings.get('adsgram_block_id', 'Not set')}</code>\n"
        f"• <b>Monetag Zone ID:</b> <code>{settings.get('monetag_zone_id', 'Not set')}</code>\n"
        f"• <b>Ad Cooldown:</b> <code>{settings.get('ad_cooldown_seconds', '20')} seconds</code>\n\n"
        "Select an option below to update settings:"
    )
    await callback.message.edit_text(text, reply_markup=await get_ad_settings_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("set_ad_net_"))
async def cb_set_ad_net(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    net = callback.data.replace("set_ad_net_", "")
    await database.set_setting("active_ad_network", net)
    await callback.answer(f"Active ad network updated to: {net.upper()}")
    await cb_admin_ads(callback)

@router.callback_query(F.data == "edit_adsgram_id")
async def cb_edit_adsgram_id(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_adsgram_id)
    await callback.message.answer(
        "📝 Please reply with the new <b>Adsgram Block ID</b> (e.g. <code>int-4166</code>):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_ads")]])
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_adsgram_id)
async def msg_adsgram_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    new_id = message.text.strip()
    await database.set_setting("adsgram_block_id", new_id)
    await state.clear()
    await message.answer(f"✅ Adsgram Block ID updated to: <code>{new_id}</code>", reply_markup=get_admin_main_kb())

@router.callback_query(F.data == "edit_monetag_id")
async def cb_edit_monetag_id(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_monetag_id)
    await callback.message.answer(
        "📝 Please reply with the new <b>Monetag Zone ID</b>:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_ads")]])
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_monetag_id)
async def msg_monetag_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    new_id = message.text.strip()
    await database.set_setting("monetag_zone_id", new_id)
    await state.clear()
    await message.answer(f"✅ Monetag Zone ID updated to: <code>{new_id}</code>", reply_markup=get_admin_main_kb())

@router.callback_query(F.data == "edit_ad_cooldown")
async def cb_edit_cooldown(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_cooldown)
    await callback.message.answer(
        "⏱️ Please enter the ad cooldown period in seconds (e.g. <code>20</code>):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_ads")]])
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_cooldown)
async def msg_cooldown(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        sec = int(message.text.strip())
        await database.set_setting("ad_cooldown_seconds", str(sec))
        await state.clear()
        await message.answer(f"✅ Ad cooldown updated to: <code>{sec}s</code>", reply_markup=get_admin_main_kb())
    except ValueError:
        await message.answer("⚠️ Please enter a valid integer number.")

# --- 2. Game Manager ---

async def get_game_manager_kb() -> InlineKeyboardMarkup:
    settings = await database.get_all_settings()
    buttons = []
    for g in config.DEFAULT_GAMES:
        key = f"game_{g['id']}"
        is_on = settings.get(key, "1") == "1"
        status_icon = "🟢 ON" if is_on else "🔴 OFF"
        action = "disable" if is_on else "enable"
        buttons.append([
            InlineKeyboardButton(
                text=f"{g['name']} : {status_icon} (Tap to Toggle)",
                callback_data=f"toggle_game_{g['id']}_{action}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Back to Admin Menu", callback_data="admin_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.callback_query(F.data == "admin_games")
async def cb_admin_games(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    text = (
        "🎮 <b>Game Management</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap any game to instantly toggle it ON or OFF for players:"
    )
    await callback.message.edit_text(text, reply_markup=await get_game_manager_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("toggle_game_"))
async def cb_toggle_game(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split("_")
    game_id = parts[2]
    action = parts[3]
    new_val = "1" if action == "enable" else "0"
    await database.set_setting(f"game_{game_id}", new_val)
    await callback.answer(f"Game {game_id} is now {'ENABLED' if new_val == '1' else 'DISABLED'}")
    await callback.message.edit_reply_markup(reply_markup=await get_game_manager_kb())

# --- 3. Life Settings ---

async def get_life_settings_kb() -> InlineKeyboardMarkup:
    settings = await database.get_all_settings()
    def_lives = settings.get("default_lives", "3")
    max_l = settings.get("max_lives", "3")
    regen_m = settings.get("regen_interval_minutes", "30")
    deduct_mode = settings.get("life_deduct_mode", "on_loss")

    buttons = [
        [
            InlineKeyboardButton(text="Default Lives:", callback_data="noop"),
            InlineKeyboardButton(text=f"{'🔘' if def_lives == '1' else '⚪'} 1", callback_data="set_def_lives_1"),
            InlineKeyboardButton(text=f"{'🔘' if def_lives == '3' else '⚪'} 3", callback_data="set_def_lives_3"),
            InlineKeyboardButton(text=f"{'🔘' if def_lives == '5' else '⚪'} 5", callback_data="set_def_lives_5"),
        ],
        [
            InlineKeyboardButton(text="Max Lives:", callback_data="noop"),
            InlineKeyboardButton(text=f"{'🔘' if max_l == '3' else '⚪'} 3", callback_data="set_max_lives_3"),
            InlineKeyboardButton(text=f"{'🔘' if max_l == '5' else '⚪'} 5", callback_data="set_max_lives_5"),
            InlineKeyboardButton(text=f"{'🔘' if max_l == '10' else '⚪'} 10", callback_data="set_max_lives_10"),
        ],
        [
            InlineKeyboardButton(text="Regen Time:", callback_data="noop"),
            InlineKeyboardButton(text=f"{'🔘' if regen_m == '15' else '⚪'} 15m", callback_data="set_regen_15"),
            InlineKeyboardButton(text=f"{'🔘' if regen_m == '30' else '⚪'} 30m", callback_data="set_regen_30"),
            InlineKeyboardButton(text=f"{'🔘' if regen_m == '60' else '⚪'} 60m", callback_data="set_regen_60"),
        ],
        [
            InlineKeyboardButton(
                text=f"Deduct Mode: {'💥 On Game Over (Loss)' if deduct_mode == 'on_loss' else '🎮 On Game Start'}",
                callback_data="toggle_deduct_mode"
            )
        ],
        [
            InlineKeyboardButton(text="🔙 Back to Admin Menu", callback_data="admin_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.callback_query(F.data == "admin_life")
async def cb_admin_life(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    settings = await database.get_all_settings()
    text = (
        "❤️ <b>Life & Energy System Settings</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Default Starting Lives:</b> {settings.get('default_lives', '3')} ❤️\n"
        f"• <b>Max Lives Cap:</b> {settings.get('max_lives', '3')} ❤️\n"
        f"• <b>Auto-Regen Interval:</b> Every {settings.get('regen_interval_minutes', '30')} minutes\n"
        f"• <b>Life Deduct Rule:</b> {settings.get('life_deduct_mode', 'on_loss').upper()}\n\n"
        "Tap buttons below to modify settings:"
    )
    await callback.message.edit_text(text, reply_markup=await get_life_settings_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("set_def_lives_"))
async def cb_set_def_lives(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    val = callback.data.replace("set_def_lives_", "")
    await database.set_setting("default_lives", val)
    await callback.answer(f"Default lives set to {val}")
    await cb_admin_life(callback)

@router.callback_query(F.data.startswith("set_max_lives_"))
async def cb_set_max_lives(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    val = callback.data.replace("set_max_lives_", "")
    await database.set_setting("max_lives", val)
    await callback.answer(f"Max lives set to {val}")
    await cb_admin_life(callback)

@router.callback_query(F.data.startswith("set_regen_"))
async def cb_set_regen(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    val = callback.data.replace("set_regen_", "")
    await database.set_setting("regen_interval_minutes", val)
    await callback.answer(f"Regen interval set to {val} minutes")
    await cb_admin_life(callback)

@router.callback_query(F.data == "toggle_deduct_mode")
async def cb_toggle_deduct_mode(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    settings = await database.get_all_settings()
    current = settings.get("life_deduct_mode", "on_loss")
    new_mode = "on_start" if current == "on_loss" else "on_loss"
    await database.set_setting("life_deduct_mode", new_mode)
    await callback.answer(f"Life deduct mode changed to: {new_mode}")
    await cb_admin_life(callback)

# --- 4. Statistics Dashboard ---

@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    stats = await database.get_admin_stats()

    game_text = ""
    for gid, data in stats["game_stats"].items():
        game_text += f"  • <b>{gid.upper()}:</b> {data['plays']} plays (Record: <code>{data['top_score']}</code>)\n"
    if not game_text:
        game_text = "  <i>No games played yet.</i>\n"

    ad_text = ""
    for net, count in stats["ad_stats"].items():
        ad_text += f"  • <b>{net.capitalize()}:</b> {count} views\n"
    if not ad_text:
        ad_text = "  <i>No ad views recorded yet.</i>\n"

    text = (
        "📊 <b>Bot & Mini App Analytics Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Total Registered Players:</b> <code>{stats['total_users']}</code>\n"
        f"🔥 <b>Daily Active Users (24h):</b> <code>{stats['dau']}</code>\n\n"
        f"🕹️ <b>Total Game Sessions:</b> <code>{stats['total_games']}</code>\n"
        f"{game_text}\n"
        f"📺 <b>Total Rewarded Ad Impressions:</b> <code>{stats['total_ads']}</code>\n"
        f"{ad_text}"
    )

    buttons = [[InlineKeyboardButton(text="🔙 Back to Admin Menu", callback_data="admin_main")]]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

# --- 5. Broadcast Engine ---

@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_broadcast)
    await callback.message.answer(
        "📢 <b>Broadcast Announcement</b>\n\n"
        "Please send the message text you want to broadcast to all registered users.\n"
        "HTML formatting is supported (<b>bold</b>, <i>italic</i>, links, etc.):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_main")]])
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_broadcast)
async def msg_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = message.text or message.caption or ""
    if not text:
        await message.answer("⚠️ Message cannot be empty. Please send some text.")
        return

    await state.clear()
    status_msg = await message.answer("⏳ Fetching user list and starting broadcast...")
    user_ids = await database.get_all_user_ids()
    
    total = len(user_ids)
    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            await message.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)  # Telegram rate-limiting friendly
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ <b>Broadcast Completed!</b>\n\n"
        f"👥 Total Target Users: {total}\n"
        f"📤 Successfully Sent: {sent}\n"
        f"❌ Failed / Blocked: {failed}",
        reply_markup=get_admin_main_kb()
    )

@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()
