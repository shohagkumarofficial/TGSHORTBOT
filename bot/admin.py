import asyncio
import datetime
import io
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import config
import database

router = Router()

class AdminStates(StatesGroup):
    waiting_for_adsgram_id = State()
    waiting_for_monetag_id = State()
    waiting_for_gigapub_id = State()
    waiting_for_adsterra_key = State()
    waiting_for_cooldown = State()
    waiting_for_broadcast = State()
    waiting_for_backup_file = State()

def is_admin(user_id: int) -> bool:
    if config.OWNER_TELEGRAM_ID == 0:
        return True
    return user_id == config.OWNER_TELEGRAM_ID

def get_admin_main_kb() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="⚙️ Ad Networks Manager", callback_data="admin_ads"),
            InlineKeyboardButton(text="🎮 Game Manager (9 Games)", callback_data="admin_games")
        ],
        [
            InlineKeyboardButton(text="❤️ Life Settings", callback_data="admin_life"),
            InlineKeyboardButton(text="📊 Live Analytics", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton(text="💾 Backup & Restore Database", callback_data="admin_backup")
        ],
        [
            InlineKeyboardButton(text="📢 Broadcast Announcement", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer(
            f"⛔ <b>Access denied.</b>\n\n"
            f"Your Telegram ID: <code>{message.from_user.id}</code>\n"
            f"Configured Admin ID: <code>{config.OWNER_TELEGRAM_ID}</code>"
        )
        return

    await state.clear()
    text = (
        "👑 <b>Master Admin Control Panel</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select a control category below to configure ads, games, lives, or backup data:"
    )
    await message.answer(text, reply_markup=get_admin_main_kb())

@router.callback_query(F.data == "admin_main")
async def cb_admin_main(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    text = (
        "👑 <b>Master Admin Control Panel</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select a control category below to configure ads, games, lives, or backup data:"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_main_kb())
    await callback.answer()

# --- 1. Multi-Ad Networks Manager ---

async def get_ad_settings_kb() -> InlineKeyboardMarkup:
    settings = await database.get_all_settings()
    mode = settings.get("ad_selection_mode", "round_robin")
    selected_net = settings.get("selected_ad_network", "adsgram")

    ag_on = settings.get("adsgram_enabled", "1") == "1"
    mo_on = settings.get("monetag_enabled", "1") == "1"
    gp_on = settings.get("gigapub_enabled", "0") == "1"
    as_on = settings.get("adsterra_enabled", "0") == "1"

    buttons = [
        [
            InlineKeyboardButton(text=f"Adsgram: {'🟢 ON' if ag_on else '🔴 OFF'}", callback_data=f"toggle_ad_net_adsgram_{'off' if ag_on else 'on'}"),
            InlineKeyboardButton(text="✏️ Edit ID", callback_data="edit_adsgram_id")
        ],
        [
            InlineKeyboardButton(text=f"Monetag: {'🟢 ON' if mo_on else '🔴 OFF'}", callback_data=f"toggle_ad_net_monetag_{'off' if mo_on else 'on'}"),
            InlineKeyboardButton(text="✏️ Edit ID", callback_data="edit_monetag_id")
        ],
        [
            InlineKeyboardButton(text=f"Gigapub: {'🟢 ON' if gp_on else '🔴 OFF'}", callback_data=f"toggle_ad_net_gigapub_{'off' if gp_on else 'on'}"),
            InlineKeyboardButton(text="✏️ Edit ID", callback_data="edit_gigapub_id")
        ],
        [
            InlineKeyboardButton(text=f"Adsterra: {'🟢 ON' if as_on else '🔴 OFF'}", callback_data=f"toggle_ad_net_adsterra_{'off' if as_on else 'on'}"),
            InlineKeyboardButton(text="✏️ Edit Key", callback_data="edit_adsterra_key")
        ],
        [
            InlineKeyboardButton(
                text=f"Mode: {'🔄 Round-Robin (All ON)' if mode == 'round_robin' else f'🎯 Single ({selected_net.upper()})'}",
                callback_data="toggle_ad_mode"
            )
        ],
        [
            InlineKeyboardButton(text="🎯 Select Active Network", callback_data="admin_select_single_ad")
        ],
        [
            InlineKeyboardButton(text="⏱️ Edit Cooldown", callback_data="edit_ad_cooldown"),
            InlineKeyboardButton(text="🔙 Back to Menu", callback_data="admin_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.callback_query(F.data == "admin_ads")
async def cb_admin_ads(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    settings = await database.get_all_settings()
    text = (
        "⚙️ <b>Ad Network Configuration & Switches</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Active Mode:</b> <code>{settings.get('ad_selection_mode', 'round_robin').upper()}</code>\n"
        f"• <b>Single Target:</b> <code>{settings.get('selected_ad_network', 'adsgram').upper()}</code>\n"
        f"• <b>Adsgram Block ID:</b> <code>{settings.get('adsgram_block_id', 'Not set')}</code>\n"
        f"• <b>Monetag Zone ID:</b> <code>{settings.get('monetag_zone_id', 'Not set')}</code>\n"
        f"• <b>Gigapub Project ID:</b> <code>{settings.get('gigapub_project_id', 'Not set')}</code>\n"
        f"• <b>Adsterra Key/Tag:</b> <code>{settings.get('adsterra_key', 'Not set')}</code>\n"
        f"• <b>Ad Cooldown:</b> <code>{settings.get('ad_cooldown_seconds', '20')}s</code>\n\n"
        "Toggle individual ad networks ON/OFF or edit IDs below:"
    )
    await callback.message.edit_text(text, reply_markup=await get_ad_settings_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("toggle_ad_net_"))
async def cb_toggle_ad_net(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    parts = callback.data.split("_")
    net = parts[3]
    action = parts[4]
    new_val = "1" if action == "on" else "0"
    await database.set_setting(f"{net}_enabled", new_val)
    await callback.answer(f"{net.upper()} is now {'ON' if new_val == '1' else 'OFF'}")
    await cb_admin_ads(callback)

@router.callback_query(F.data == "toggle_ad_mode")
async def cb_toggle_ad_mode(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    settings = await database.get_all_settings()
    current = settings.get("ad_selection_mode", "round_robin")
    new_mode = "single" if current == "round_robin" else "round_robin"
    await database.set_setting("ad_selection_mode", new_mode)
    await callback.answer(f"Ad mode switched to: {new_mode.upper()}")
    await cb_admin_ads(callback)

@router.callback_query(F.data == "admin_select_single_ad")
async def cb_admin_select_single_ad(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    buttons = [
        [
            InlineKeyboardButton(text="🎯 Adsgram Only", callback_data="set_single_net_adsgram"),
            InlineKeyboardButton(text="🎯 Monetag Only", callback_data="set_single_net_monetag")
        ],
        [
            InlineKeyboardButton(text="🎯 Gigapub Only", callback_data="set_single_net_gigapub"),
            InlineKeyboardButton(text="🎯 Adsterra Only", callback_data="set_single_net_adsterra")
        ],
        [
            InlineKeyboardButton(text="🔙 Back to Ad Settings", callback_data="admin_ads")
        ]
    ]
    await callback.message.edit_text("🎯 <b>Select which ad network to force for all users:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data.startswith("set_single_net_"))
async def cb_set_single_net(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    net = callback.data.replace("set_single_net_", "")
    await database.set_setting("selected_ad_network", net)
    await database.set_setting("ad_selection_mode", "single")
    await callback.answer(f"Single target network set to: {net.upper()}")
    await cb_admin_ads(callback)

@router.callback_query(F.data == "edit_adsgram_id")
async def cb_edit_adsgram_id(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_adsgram_id)
    await callback.message.answer("📝 Reply with new <b>Adsgram Block ID</b>:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_ads")]]))
    await callback.answer()

@router.message(AdminStates.waiting_for_adsgram_id)
async def msg_adsgram_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    new_id = message.text.strip()
    await database.set_setting("adsgram_block_id", new_id)
    await state.clear()
    await message.answer(f"✅ Adsgram Block ID updated to: <code>{new_id}</code>", reply_markup=get_admin_main_kb())

@router.callback_query(F.data == "edit_monetag_id")
async def cb_edit_monetag_id(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_monetag_id)
    await callback.message.answer("📝 Reply with new <b>Monetag Zone ID</b>:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_ads")]]))
    await callback.answer()

@router.message(AdminStates.waiting_for_monetag_id)
async def msg_monetag_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    new_id = message.text.strip()
    await database.set_setting("monetag_zone_id", new_id)
    await state.clear()
    await message.answer(f"✅ Monetag Zone ID updated to: <code>{new_id}</code>", reply_markup=get_admin_main_kb())

@router.callback_query(F.data == "edit_gigapub_id")
async def cb_edit_gigapub_id(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_gigapub_id)
    await callback.message.answer("📝 Reply with new <b>Gigapub Project ID</b>:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_ads")]]))
    await callback.answer()

@router.message(AdminStates.waiting_for_gigapub_id)
async def msg_gigapub_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    new_id = message.text.strip()
    await database.set_setting("gigapub_project_id", new_id)
    await state.clear()
    await message.answer(f"✅ Gigapub Project ID updated to: <code>{new_id}</code>", reply_markup=get_admin_main_kb())

@router.callback_query(F.data == "edit_adsterra_key")
async def cb_edit_adsterra_key(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_adsterra_key)
    await callback.message.answer("📝 Reply with new <b>Adsterra Key/Tag</b>:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_ads")]]))
    await callback.answer()

@router.message(AdminStates.waiting_for_adsterra_key)
async def msg_adsterra_key(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    new_id = message.text.strip()
    await database.set_setting("adsterra_key", new_id)
    await state.clear()
    await message.answer(f"✅ Adsterra Key updated to: <code>{new_id}</code>", reply_markup=get_admin_main_kb())

@router.callback_query(F.data == "edit_ad_cooldown")
async def cb_edit_cooldown(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_cooldown)
    await callback.message.answer("⏱️ Enter cooldown period in seconds (e.g. <code>20</code>):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_ads")]]))
    await callback.answer()

@router.message(AdminStates.waiting_for_cooldown)
async def msg_cooldown(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    try:
        sec = int(message.text.strip())
        await database.set_setting("ad_cooldown_seconds", str(sec))
        await state.clear()
        await message.answer(f"✅ Ad cooldown updated to: <code>{sec}s</code>", reply_markup=get_admin_main_kb())
    except ValueError:
        await message.answer("⚠️ Please enter a valid number.")

# --- 2. Game Manager (9 Games) ---

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
    if not is_admin(callback.from_user.id): return
    text = (
        "🎮 <b>Game Management (9 Available Games)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap any game to toggle it ON or OFF instantly for all players:"
    )
    await callback.message.edit_text(text, reply_markup=await get_game_manager_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("toggle_game_"))
async def cb_toggle_game(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
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
    max_free = settings.get("max_free_lives", "3")
    regen_m = settings.get("regen_interval_minutes", "30")
    deduct_mode = settings.get("life_deduct_mode", "on_loss")

    buttons = [
        [
            InlineKeyboardButton(text="Free Starting:", callback_data="noop"),
            InlineKeyboardButton(text=f"{'🔘' if def_lives == '1' else '⚪'} 1", callback_data="set_def_lives_1"),
            InlineKeyboardButton(text=f"{'🔘' if def_lives == '3' else '⚪'} 3", callback_data="set_def_lives_3"),
            InlineKeyboardButton(text=f"{'🔘' if def_lives == '5' else '⚪'} 5", callback_data="set_def_lives_5"),
        ],
        [
            InlineKeyboardButton(text="Free Regen Cap:", callback_data="noop"),
            InlineKeyboardButton(text=f"{'🔘' if max_free == '3' else '⚪'} 3", callback_data="set_max_free_3"),
            InlineKeyboardButton(text=f"{'🔘' if max_free == '5' else '⚪'} 5", callback_data="set_max_free_5"),
        ],
        [
            InlineKeyboardButton(text="Regen Interval:", callback_data="noop"),
            InlineKeyboardButton(text=f"{'🔘' if regen_m == '15' else '⚪'} 15m", callback_data="set_regen_15"),
            InlineKeyboardButton(text=f"{'🔘' if regen_m == '30' else '⚪'} 30m", callback_data="set_regen_30"),
            InlineKeyboardButton(text=f"{'🔘' if regen_m == '60' else '⚪'} 60m", callback_data="set_regen_60"),
        ],
        [
            InlineKeyboardButton(
                text=f"Deduct Rule: {'💥 On Game Over (Loss)' if deduct_mode == 'on_loss' else '🎮 On Game Start'}",
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
    if not is_admin(callback.from_user.id): return
    settings = await database.get_all_settings()
    text = (
        "❤️ <b>Life & Energy System Settings</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Free Starting Lives:</b> {settings.get('default_lives', '3')} ❤️\n"
        f"• <b>Free Auto-Regen Cap:</b> {settings.get('max_free_lives', '3')} ❤️\n"
        f"• <b>Rewarded Ad Lives:</b> <b>UNLIMITED (No Cap)</b> 🚀\n"
        f"• <b>Auto-Regen Interval:</b> Every {settings.get('regen_interval_minutes', '30')} minutes\n"
        f"• <b>Life Deduct Rule:</b> {settings.get('life_deduct_mode', 'on_loss').upper()}\n\n"
        "Tap buttons below to modify:"
    )
    await callback.message.edit_text(text, reply_markup=await get_life_settings_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("set_def_lives_"))
async def cb_set_def_lives(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    val = callback.data.replace("set_def_lives_", "")
    await database.set_setting("default_lives", val)
    await callback.answer(f"Default lives set to {val}")
    await cb_admin_life(callback)

@router.callback_query(F.data.startswith("set_max_free_"))
async def cb_set_max_free(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    val = callback.data.replace("set_max_free_", "")
    await database.set_setting("max_free_lives", val)
    await callback.answer(f"Free regen cap set to {val}")
    await cb_admin_life(callback)

@router.callback_query(F.data.startswith("set_regen_"))
async def cb_set_regen(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    val = callback.data.replace("set_regen_", "")
    await database.set_setting("regen_interval_minutes", val)
    await callback.answer(f"Regen interval set to {val}m")
    await cb_admin_life(callback)

@router.callback_query(F.data == "toggle_deduct_mode")
async def cb_toggle_deduct_mode(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    settings = await database.get_all_settings()
    current = settings.get("life_deduct_mode", "on_loss")
    new_mode = "on_start" if current == "on_loss" else "on_loss"
    await database.set_setting("life_deduct_mode", new_mode)
    await callback.answer(f"Deduct mode: {new_mode}")
    await cb_admin_life(callback)

# --- 4. Database Backup & Restore Engine ---

@router.callback_query(F.data == "admin_backup")
async def cb_admin_backup(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    text = (
        "💾 <b>Database Backup & Restore Center</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Render free tier disks may reset on restart. Use this backup engine to safeguard your data:\n\n"
        "📥 <b>Download Backup:</b> Sends current <code>.db</code> file to this chat.\n"
        "📤 <b>Restore Backup:</b> Upload a previously downloaded <code>.db</code> file to restore all users, scores, and settings."
    )
    buttons = [
        [
            InlineKeyboardButton(text="📥 Download Backup (.db file)", callback_data="do_backup_export")
        ],
        [
            InlineKeyboardButton(text="📤 Restore Backup (.db file)", callback_data="do_backup_restore_prompt")
        ],
        [
            InlineKeyboardButton(text="🔙 Back to Admin Menu", callback_data="admin_main")
        ]
    ]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data == "do_backup_export")
async def cb_do_backup_export(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    await callback.answer("Generating backup snapshot...")
    
    db_bytes = await database.export_database_bytes()
    if not db_bytes:
        await callback.message.answer("❌ Error: Database file is empty or not found.")
        return

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"game_bot_backup_{timestamp}.db"
    
    input_file = BufferedInputFile(file=db_bytes, filename=file_name)
    await callback.message.answer_document(
        document=input_file,
        caption=f"✅ <b>Database Backup Snapshot</b>\n📅 {timestamp}\n📦 Size: {len(db_bytes) / 1024:.1f} KB\n\n<i>Keep this file safe. You can restore it anytime by clicking 'Restore Backup'.</i>"
    )

@router.callback_query(F.data == "do_backup_restore_prompt")
async def cb_do_backup_restore_prompt(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_backup_file)
    await callback.message.answer(
        "📤 <b>Restore Database Backup</b>\n\n"
        "Please send the <code>.db</code> backup file as a Telegram Document to this chat.\n\n"
        "⚠️ <i>Warning: This will replace the current database with the uploaded backup.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_backup")]])
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_backup_file, F.document)
async def msg_restore_db(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    doc = message.document
    if not doc.file_name.endswith(".db"):
        await message.answer("⚠️ Please upload a valid <code>.db</code> SQLite backup file.")
        return

    status_msg = await message.answer("⏳ Downloading and validating backup file...")
    file_io = io.BytesIO()
    await message.bot.download(doc, destination=file_io)
    data = file_io.getvalue()

    success, msg = await database.restore_database_from_bytes(data)
    await state.clear()

    if success:
        await status_msg.edit_text(
            f"🎉 <b>Restore Completed!</b>\n\n"
            f"Database successfully restored from <code>{doc.file_name}</code>.\n"
            f"All players, high scores, and settings are active!",
            reply_markup=get_admin_main_kb()
        )
    else:
        await status_msg.edit_text(f"❌ <b>Restore Failed:</b> {msg}", reply_markup=get_admin_main_kb())

# --- 5. Analytics Dashboard ---

@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    stats = await database.get_admin_stats()

    game_text = ""
    for gid, data in stats["game_stats"].items():
        game_text += f"  • <b>{gid.upper()}:</b> {data['plays']} plays (Top: <code>{data['top_score']}</code>)\n"
    if not game_text:
        game_text = "  <i>No games played yet.</i>\n"

    ad_text = ""
    for net, count in stats["ad_stats"].items():
        ad_text += f"  • <b>{net.capitalize()}:</b> {count} views\n"
    if not ad_text:
        ad_text = "  <i>No ad views recorded yet.</i>\n"

    text = (
        "📊 <b>Game Hub Analytics Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Total Players:</b> <code>{stats['total_users']}</code>\n"
        f"🔥 <b>Daily Active Users (24h):</b> <code>{stats['dau']}</code>\n\n"
        f"🕹️ <b>Total Game Sessions:</b> <code>{stats['total_games']}</code>\n"
        f"{game_text}\n"
        f"📺 <b>Total Rewarded Ad Views:</b> <code>{stats['total_ads']}</code>\n"
        f"{ad_text}"
    )

    buttons = [[InlineKeyboardButton(text="🔙 Back to Admin Menu", callback_data="admin_main")]]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

# --- 6. Broadcast Engine ---

@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_broadcast)
    await callback.message.answer(
        "📢 <b>Broadcast Announcement</b>\n\n"
        "Send message text to broadcast to all players (HTML formatted):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_main")]])
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_broadcast)
async def msg_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    text = message.text or message.caption or ""
    if not text:
        await message.answer("⚠️ Message cannot be empty.")
        return

    await state.clear()
    status_msg = await message.answer("⏳ Sending broadcast to all players...")
    user_ids = await database.get_all_user_ids()
    
    total = len(user_ids)
    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            await message.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ <b>Broadcast Completed!</b>\n\n"
        f"👥 Total: {total} | 📤 Sent: {sent} | ❌ Failed: {failed}",
        reply_markup=get_admin_main_kb()
    )

@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()
