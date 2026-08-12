"""aiogram 3.x Telegram bot — webhook mode (PRD §3, §4).

Commands:
  /start [code]      — auto-register admin; if code present, open Mini App viewer
  /newlink <url>     — create short link
  /mybalance         — show confirmed + pending balance
  /myproof <code>    — set/print the proof URL for a link
  /withdraw <amt> <bkash|nagad> <number>  — request withdrawal
  /mylinks           — list own links
  /panel             — open the admin panel Mini App
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

import storage
from config import settings
from cpm_engine import close_cycle_if_due

log = logging.getLogger(__name__)
router = Router()
bot = Bot(token=settings.bot_token)


def _webapp_url(path: str = "") -> str:
    base = settings.webapp_base_url.rstrip("/")
    return f"{base}{path}"


def _mini_app_button(text: str, path: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, web_app=WebAppInfo(url=_webapp_url(path)))]
    ])


def _is_valid_url(url: str) -> bool:
    try:
        u = urlparse(url)
        return u.scheme in ("http", "https") and bool(u.netloc)
    except Exception:
        return False


def _main_keyboard(telegram_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="➕ New Link"), KeyboardButton(text="💰 My Balance")],
        [KeyboardButton(text="🔗 My Links"), KeyboardButton(text="🏧 Withdraw")],
    ]
    if telegram_id == settings.owner_telegram_id:
        rows.append([KeyboardButton(text="🛠 Owner Panel")])
    rows.append([KeyboardButton(text="📊 Panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# --------------------------------------------------------------------------
# /start  — also handles deep-link viewer entry
# --------------------------------------------------------------------------

@router.message(CommandStart(deep_link=True))
async def start_with_code(message: Message, command: CommandObject) -> None:
    code = (command.args or "").strip()
    user = message.from_user
    if not user:
        return
    await storage.get_or_create_admin(user.id, user.username or "")
    await close_cycle_if_due()

    if code:
        link = storage.get_link(code)
        if not link:
            await message.answer("❌ That short link is invalid.")
            return
        # Open the viewer Mini App pre-loaded with this code
        await message.answer(
            "👋 Tap the button below to continue — 3 short ads, then your link.",
            reply_markup=_mini_app_button(f"▶️ Open (link {code})", f"/r/{code}"),
        )
        return

    await message.answer(
        f"👋 Welcome to TGSHORTBOT, {user.first_name or 'friend'}!\n\n"
        "Shorten links and earn when viewers watch 3 rewarded ads.",
        reply_markup=_main_keyboard(user.id),
    )


@router.message(CommandStart())
async def start_plain(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    await storage.get_or_create_admin(user.id, user.username or "")
    await close_cycle_if_due()
    await message.answer(
        f"👋 Welcome to TGSHORTBOT, {user.first_name or 'friend'}!\n\n"
        "Shorten links and earn when viewers watch 3 rewarded ads.",
        reply_markup=_main_keyboard(user.id),
    )


# --------------------------------------------------------------------------
# /newlink
# --------------------------------------------------------------------------

@router.message(Command("newlink"))
async def cmd_newlink(message: Message, command: CommandObject) -> None:
    user = message.from_user
    if not user:
        return
    await storage.get_or_create_admin(user.id, user.username or "")
    url = (command.args or "").strip()
    if not _is_valid_url(url):
        await message.answer(
            "Usage: `/newlink https://example.com`\n"
            "URL must start with http:// or https://",
            parse_mode="Markdown",
        )
        return
    link = await storage.create_link(user.id, url)
    short = f"https://t.me/{(await bot.get_me()).username}?start={link.short_code}"
    await message.answer(
        f"✅ Link created!\n\n"
        f"Short: `{short}`\n"
        f"Code: `{link.short_code}`\n\n"
        f"Next: share it, then send me the proof URL "
        f"(channel/post link) with:\n"
        f"`/myproof {link.short_code} <your-proof-url>`",
        parse_mode="Markdown",
    )


@router.message(F.text == "➕ New Link")
async def kb_newlink(message: Message) -> None:
    await message.answer("Send me: `/newlink https://your-long-url.com`", parse_mode="Markdown")


# --------------------------------------------------------------------------
# /mybalance
# --------------------------------------------------------------------------

@router.message(Command("mybalance"))
@router.message(F.text == "💰 My Balance")
async def cmd_mybalance(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    admin = await storage.get_or_create_admin(user.id, user.username or "")
    cpm = storage.get_cpm()
    note = ""
    if cpm.mode.value == "scheduled":
        from datetime import datetime, timedelta
        ends = cpm.cycle_started_at + timedelta(hours=cpm.cycle_duration_hours)
        remaining = ends - datetime.utcnow()
        hrs = max(0, int(remaining.total_seconds() // 3600))
        mins = max(0, int((remaining.total_seconds() % 3600) // 60))
        note = f"\n⏱ Next payout in ~{hrs}h {mins}m"
    await message.answer(
        f"💰 *Your balance*\n\n"
        f"Confirmed: `{admin.balance_confirmed:.2f}` BDT\n"
        f"Pending:   `{admin.balance_pending:.2f}` BDT"
        f"{note}",
        parse_mode="Markdown",
    )


# --------------------------------------------------------------------------
# /mylinks
# --------------------------------------------------------------------------

@router.message(Command("mylinks"))
@router.message(F.text == "🔗 My Links")
async def cmd_mylinks(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    links = storage.list_links(owner_telegram_id=user.id)
    if not links:
        await message.answer("You have no links yet. Send `/newlink <url>` to create one.")
        return
    lines = ["*Your links*\n"]
    for l in links[-20:]:
        views = storage.list_views_for_link(l.short_code)
        n_views = len(views)
        lines.append(
            f"`{l.short_code}` → {l.destination_url}\n"
            f"   views: {n_views} · status: {l.verification_status.value}"
            f"{' · proof: ' + l.proof_url if l.proof_url else ''}"
        )
    await message.answer("\n\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)


# --------------------------------------------------------------------------
# /myproof
# --------------------------------------------------------------------------

@router.message(Command("myproof"))
async def cmd_myproof(message: Message, command: CommandObject) -> None:
    user = message.from_user
    if not user:
        return
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) != 2 or not _is_valid_url(parts[1]):
        await message.answer("Usage: `/myproof <short_code> <proof_url>`", parse_mode="Markdown")
        return
    code, proof = parts
    link = storage.get_link(code)
    if not link or link.owner_telegram_id != user.id:
        await message.answer("Link not found or not yours.")
        return
    await storage.set_link_proof(code, proof)
    await message.answer(f"✅ Proof URL saved for `{code}`. Awaiting Owner verification.", parse_mode="Markdown")


# --------------------------------------------------------------------------
# /withdraw
# --------------------------------------------------------------------------

@router.message(Command("withdraw"))
@router.message(F.text == "🏧 Withdraw")
async def cmd_withdraw(message: Message, command: CommandObject) -> None:
    user = message.from_user
    if not user:
        return
    admin = await storage.get_or_create_admin(user.id, user.username or "")
    if admin.balance_confirmed <= 0:
        await message.answer("Your confirmed balance is 0 BDT. Nothing to withdraw yet.")
        return
    args = (command.args or "").split()
    if len(args) == 3:
        try:
            amount = float(args[0])
        except ValueError:
            amount = -1
        method, account = args[1], args[2]
        if amount <= 0 or method not in ("bkash", "nagad") or not account:
            await message.answer(
                "Usage: `/withdraw <amount> <bkash|nagad> <account_number>`",
                parse_mode="Markdown",
            )
            return
        if amount > admin.balance_confirmed:
            await message.answer(
                f"❌ Amount exceeds confirmed balance ({admin.balance_confirmed:.2f} BDT).",
                parse_mode="Markdown",
            )
            return
        w = await storage.create_withdraw(user.id, amount, method, account)
        await message.answer(
            f"✅ Withdrawal request `{w.request_id}` created for {amount:.2f} BDT via {method}.\n"
            "Owner will pay and mark it paid shortly.",
            parse_mode="Markdown",
        )
    else:
        # Open the Mini App withdrawal form
        await message.answer(
            "Tap below to submit a withdrawal request:",
            reply_markup=_mini_app_button("🏧 Withdraw", "/panel?tab=withdraw"),
        )


# --------------------------------------------------------------------------
# panel / owner shortcuts
# --------------------------------------------------------------------------

@router.message(F.text.in_({"📊 Panel", "🛠 Owner Panel"}))
async def kb_panel(message: Message) -> None:
    await message.answer(
        "Open your dashboard:",
        reply_markup=_mini_app_button("📊 Open Panel", "/panel"),
    )


# --------------------------------------------------------------------------
# dispatcher factory
# --------------------------------------------------------------------------

def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp
