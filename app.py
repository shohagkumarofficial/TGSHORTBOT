"""FastAPI app for TGSHORTBOT — webhook receiver, short-link redirect
entrypoint, and the Mini App API.

Run locally with:
    uvicorn app:app --reload

Deployed on Render with:
    uvicorn app:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import asyncio
import logging
import random
import string
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram.types import Update
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import cpm_engine
from bot import (
    build_bot_and_dispatcher,
    notify_admin_of_withdrawal_resolution,
    notify_owner_of_withdrawal,
    register_handlers,
    set_bot_commands,
)
from config import get_settings
from models import Admin, AdminStatus, CountedStatus, CPMMode, Role, WithdrawMethod, WithdrawStatus
from storage import Storage
from telegram_auth import InitDataError, validate_init_data
from validators import bd_mobile_validation_error, normalize_bd_mobile_number

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

settings = get_settings()
storage = Storage(settings.DATA_FILE)
bot, dp = build_bot_and_dispatcher(settings.BOT_TOKEN)
register_handlers(dp, storage, settings)

_cpm_watcher_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await storage.load()

    try:
        await bot.set_webhook(
            url=settings.WEBHOOK_URL,
            secret_token=settings.WEBHOOK_SECRET,
            drop_pending_updates=False,
        )
        logger.info("Webhook set to %s", settings.WEBHOOK_URL)
    except Exception:
        logger.exception("Could not set webhook on startup — set it manually with scripts/set_webhook.py")

    try:
        await set_bot_commands(bot)
    except Exception:
        logger.exception("Could not set bot command menu on startup")

    global _cpm_watcher_task
    _cpm_watcher_task = asyncio.create_task(
        cpm_engine.run_cpm_cycle_watcher(storage, settings.CPM_CHECK_INTERVAL_SECONDS)
    )
    logger.info("TGSHORTBOT backend started")

    yield

    if _cpm_watcher_task:
        _cpm_watcher_task.cancel()
    await bot.session.close()


app = FastAPI(title="TGSHORTBOT", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="webapp"), name="webapp-static")


# ---------------------------------------------------------------------------
# Auth dependencies — every Mini App call is validated against Telegram's
# initData signature server-side (never trust a client-supplied Telegram ID).
# ---------------------------------------------------------------------------

async def _extract_user(x_telegram_init_data: Optional[str]) -> dict:
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="missing X-Telegram-Init-Data header")
    try:
        result = validate_init_data(x_telegram_init_data, settings.BOT_TOKEN)
    except InitDataError as e:
        raise HTTPException(status_code=401, detail=f"invalid init data: {e}")
    user = result.get("user")
    if not user or "id" not in user:
        raise HTTPException(status_code=401, detail="init data missing user")
    return user


async def require_admin(
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data")
) -> Admin:
    user = await _extract_user(x_telegram_init_data)
    admin = await storage.get_or_create_admin(user["id"], user.get("username"), settings.OWNER_TELEGRAM_ID)
    if admin.status == AdminStatus.BANNED:
        raise HTTPException(status_code=403, detail="account suspended")
    return admin


async def require_owner(admin: Admin = Depends(require_admin)) -> Admin:
    if admin.role != Role.OWNER:
        raise HTTPException(status_code=403, detail="owner only")
    return admin


# ---------------------------------------------------------------------------
# Health & webhook
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Keeps Render's free-tier service awake (NFR, Section 6)."""
    return {"ok": True}


@app.get("/")
async def root():
    """The bare domain is the canonical URL registered with BotFather and
    with Adsgram (both `/panel` and `/r/{code}` already live under this
    same origin, so this is purely about having one stable, memorable
    root URL rather than a path — it doesn't change what anyone can
    access, since role is still decided server-side by Telegram ID, not
    by which URL was opened).
    """
    return RedirectResponse(url="/panel")


@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
):
    if x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="bad secret token")
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Short-link entrypoint — serves the ad-lock Mini App page (Section 4.2)
# ---------------------------------------------------------------------------

@app.get("/r/{short_code}", response_class=HTMLResponse)
async def redirect_entry(short_code: str):
    link = await storage.get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="link not found")
    cs = await storage.get_cpm_setting()
    with open("webapp/viewer.html", "r", encoding="utf-8") as f:
        html = f.read()
    html = (
        html.replace("__SHORT_CODE__", short_code)
        .replace("__ADSGRAM_BLOCK_ID__", settings.ADSGRAM_BLOCK_ID)
        .replace("__AD_VIEW_DELAY_SECONDS__", str(cs.ad_view_delay_seconds))
    )
    return HTMLResponse(html)


@app.get("/panel", response_class=HTMLResponse)
async def panel_page():
    with open("webapp/panel.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


# ---------------------------------------------------------------------------
# Viewer API
# ---------------------------------------------------------------------------

@app.post("/api/log-view")
async def log_view(
    payload: dict,
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
):
    user = await _extract_user(x_telegram_init_data)
    short_code = payload.get("short_code")
    if not short_code:
        raise HTTPException(status_code=400, detail="short_code required")

    link = await storage.get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="link not found")

    viewer_id = user["id"]
    view = await storage.create_view(short_code, viewer_id)
    if view is None:
        # Dedupe rule: only the first completed view per viewer per link counts.
        return {"ok": True, "already_counted": True}

    await cpm_engine.credit_new_view(storage, view, link)
    return {"ok": True, "already_counted": False}


@app.get("/api/link/{short_code}")
async def get_link_destination(
    short_code: str,
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
):
    # Only called by viewer.html *after* the view has been logged.
    await _extract_user(x_telegram_init_data)
    link = await storage.get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="link not found")
    return {"destination_url": link.destination_url}


# ---------------------------------------------------------------------------
# Admin: my profile
# ---------------------------------------------------------------------------

@app.get("/api/me")
async def me(admin: Admin = Depends(require_admin)):
    return admin.model_dump()


@app.get("/api/traffic-sources")
async def list_traffic_sources(admin: Admin = Depends(require_admin)):
    return {"traffic_sources": [s.model_dump() for s in admin.traffic_sources]}


@app.post("/api/traffic-sources")
async def add_traffic_source(payload: dict, admin: Admin = Depends(require_admin)):
    """Adds one more traffic source; an Admin can hold several at once
    and add/update/remove them at any time (no longer a single slot).
    """
    platform = (payload.get("platform") or "").strip()
    url = (payload.get("url") or "").strip()
    if not platform:
        raise HTTPException(status_code=400, detail="platform required")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must be a valid http(s) link")
    source = await storage.add_traffic_source(admin.telegram_id, platform, url)
    await storage.append_history(
        "traffic_source_change",
        {"telegram_id": admin.telegram_id, "action": "add", "platform": platform, "url": url},
    )
    return source.model_dump()


@app.put("/api/traffic-sources/{source_id}")
async def edit_traffic_source(source_id: str, payload: dict, admin: Admin = Depends(require_admin)):
    platform = payload.get("platform")
    url = payload.get("url")
    if platform is not None:
        platform = platform.strip()
        if not platform:
            raise HTTPException(status_code=400, detail="platform cannot be empty")
    if url is not None:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="url must be a valid http(s) link")
    updated = await storage.update_traffic_source(admin.telegram_id, source_id, platform=platform, url=url)
    if not updated:
        raise HTTPException(status_code=404, detail="traffic source not found")
    await storage.append_history(
        "traffic_source_change",
        {"telegram_id": admin.telegram_id, "action": "update", "source_id": source_id, "platform": platform, "url": url},
    )
    return updated.model_dump()


@app.delete("/api/traffic-sources/{source_id}")
async def remove_traffic_source(source_id: str, admin: Admin = Depends(require_admin)):
    ok = await storage.delete_traffic_source(admin.telegram_id, source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="traffic source not found")
    await storage.append_history(
        "traffic_source_change",
        {"telegram_id": admin.telegram_id, "action": "delete", "source_id": source_id},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin: links
# ---------------------------------------------------------------------------

def _gen_short_code(length: int = 7) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choices(alphabet, k=length))


def _short_url_for(code: str) -> str:
    return f"https://t.me/{settings.BOT_USERNAME}?start={code}"


@app.post("/api/links")
async def create_link(payload: dict, admin: Admin = Depends(require_admin)):
    if not admin.traffic_sources:
        raise HTTPException(
            status_code=400,
            detail="Add at least one Traffic Source before creating links (POST /api/traffic-sources)",
        )
    destination_url = (payload.get("destination_url") or "").strip()
    if not destination_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="destination_url must be a valid http(s) URL")

    code = _gen_short_code()
    while await storage.get_link(code):
        code = _gen_short_code()
    link = await storage.create_link(code, admin.telegram_id, destination_url)
    return {"short_code": link.short_code, "short_url": _short_url_for(link.short_code)}


@app.get("/api/links")
async def my_links(admin: Admin = Depends(require_admin)):
    links = await storage.list_links_by_owner(admin.telegram_id)
    out = []
    for l in links:
        views = await storage.list_views_by_short_code(l.short_code)
        out.append(
            {
                **l.model_dump(),
                "short_url": _short_url_for(l.short_code),
                "view_count": len(views),
                "confirmed_views": len([v for v in views if v.counted_status == CountedStatus.CONFIRMED]),
                "pending_views": len([v for v in views if v.counted_status == CountedStatus.PENDING_PAYOUT]),
            }
        )
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return {"links": out}


# ---------------------------------------------------------------------------
# CPM
# ---------------------------------------------------------------------------

@app.get("/api/cpm")
async def get_cpm(admin: Admin = Depends(require_admin)):
    cs = await storage.get_cpm_setting()
    data = cs.model_dump()
    if cs.mode == CPMMode.SCHEDULED:
        started = datetime.fromisoformat(cs.cycle_started_at)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        deadline = started + timedelta(hours=cs.cycle_duration_hours)
        data["seconds_to_payout"] = max(0, int((deadline - datetime.now(timezone.utc)).total_seconds()))
        if admin.role != Role.OWNER:
            # Sub-admins see the countdown and pending-view count, but not
            # a pre-calculated rate, since it isn't final until payout (Section 4.5).
            data.pop("current_cpm", None)
    return data


@app.post("/api/admin/cpm")
async def admin_update_cpm(payload: dict, owner: Admin = Depends(require_owner)):
    mode_enum = None
    if payload.get("mode") is not None:
        try:
            mode_enum = CPMMode(payload["mode"])
        except ValueError:
            raise HTTPException(status_code=400, detail="mode must be 'realtime' or 'scheduled'")

    current_cpm = payload.get("current_cpm")
    if current_cpm is not None:
        current_cpm = float(current_cpm)
        if current_cpm < 0:
            raise HTTPException(status_code=400, detail="current_cpm must be >= 0")

    cycle_duration_hours = payload.get("cycle_duration_hours")
    if cycle_duration_hours is not None:
        cycle_duration_hours = float(cycle_duration_hours)
        if cycle_duration_hours <= 0:
            raise HTTPException(status_code=400, detail="cycle_duration_hours must be > 0")

    ad_view_delay_seconds = payload.get("ad_view_delay_seconds")
    if ad_view_delay_seconds is not None:
        ad_view_delay_seconds = float(ad_view_delay_seconds)
        if ad_view_delay_seconds < 0:
            raise HTTPException(status_code=400, detail="ad_view_delay_seconds must be >= 0")

    min_withdraw_amount = payload.get("min_withdraw_amount")
    if min_withdraw_amount is not None:
        min_withdraw_amount = float(min_withdraw_amount)
        if min_withdraw_amount < 0:
            raise HTTPException(status_code=400, detail="min_withdraw_amount must be >= 0")

    max_daily_views_per_admin = payload.get("max_daily_views_per_admin")
    if max_daily_views_per_admin is not None:
        try:
            max_daily_views_per_admin = int(max_daily_views_per_admin)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="max_daily_views_per_admin must be a whole number")
        if max_daily_views_per_admin < 0:
            raise HTTPException(status_code=400, detail="max_daily_views_per_admin must be >= 0")

    cs = await storage.update_cpm_setting(
        mode=mode_enum,
        current_cpm=current_cpm,
        cycle_duration_hours=cycle_duration_hours,
        ad_view_delay_seconds=ad_view_delay_seconds,
        min_withdraw_amount=min_withdraw_amount,
        max_daily_views_per_admin=max_daily_views_per_admin,
        updated_by=owner.telegram_id,
    )
    return cs.model_dump()


# ---------------------------------------------------------------------------
# Withdrawals
# ---------------------------------------------------------------------------

@app.post("/api/withdraw")
async def request_withdrawal(payload: dict, admin: Admin = Depends(require_admin)):
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="amount must be a number")
    method = payload.get("method")
    account_number_raw = (payload.get("account_number") or "").strip()

    if method not in ("bkash", "nagad"):
        raise HTTPException(status_code=400, detail="method must be 'bkash' or 'nagad'")
    validation_error = bd_mobile_validation_error(account_number_raw)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)
    account_number = normalize_bd_mobile_number(account_number_raw)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    if amount > admin.balance_confirmed:
        raise HTTPException(status_code=400, detail="amount exceeds confirmed balance")

    cs = await storage.get_cpm_setting()
    if amount < cs.min_withdraw_amount:
        raise HTTPException(
            status_code=400,
            detail=f"amount is below the minimum withdrawal amount ({cs.min_withdraw_amount:.2f})",
        )

    req = await storage.create_withdrawal(admin.telegram_id, amount, WithdrawMethod(method), account_number)
    await notify_owner_of_withdrawal(bot, settings, admin, req)
    return req.model_dump()


@app.get("/api/withdrawals/mine")
async def my_withdrawals(admin: Admin = Depends(require_admin)):
    all_w = await storage.list_withdrawals()
    mine = sorted(
        (w.model_dump() for w in all_w if w.admin_telegram_id == admin.telegram_id),
        key=lambda w: w["created_at"],
        reverse=True,
    )
    return {"withdrawals": mine}


@app.get("/api/admin/withdrawals")
async def admin_pending_withdrawals(owner: Admin = Depends(require_owner)):
    pending = await storage.list_withdrawals(status=WithdrawStatus.PENDING)
    pending.sort(key=lambda w: w.created_at)
    out = []
    for w in pending:
        requester = await storage.get_admin(w.admin_telegram_id)
        d = w.model_dump()
        d["admin_username"] = requester.username if requester else None
        d["traffic_sources"] = [s.model_dump() for s in requester.traffic_sources] if requester else []
        out.append(d)
    return {"withdrawals": out}


@app.post("/api/admin/withdrawals/{request_id}/resolve")
async def admin_resolve_withdrawal(request_id: str, payload: dict, owner: Admin = Depends(require_owner)):
    decision = payload.get("decision")
    if decision not in ("paid", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'paid' or 'rejected'")
    reason = payload.get("reason")
    status_enum = WithdrawStatus.PAID if decision == "paid" else WithdrawStatus.REJECTED
    req = await storage.resolve_withdrawal(request_id, status_enum, reason)
    if not req:
        raise HTTPException(status_code=404, detail="withdrawal not found or already resolved")
    requester = await storage.get_admin(req.admin_telegram_id)
    if requester:
        await notify_admin_of_withdrawal_resolution(bot, settings, requester, req)
    return req.model_dump()


# ---------------------------------------------------------------------------
# Owner: admins list, ban/unban, platform stats
# ---------------------------------------------------------------------------

@app.get("/api/admin/admins")
async def list_all_admins(owner: Admin = Depends(require_owner)):
    admins = await storage.list_admins()
    admins.sort(key=lambda a: a.created_at)
    return {"admins": [a.model_dump() for a in admins]}


@app.get("/api/admin/admins/{telegram_id}")
async def admin_detail(telegram_id: int, owner: Admin = Depends(require_owner)):
    stats = await storage.admin_stats(telegram_id)
    if not stats:
        raise HTTPException(status_code=404, detail="admin not found")
    stats["balance_adjustments"] = await storage.list_balance_adjustments(telegram_id)
    return stats


@app.post("/api/admin/admins/{telegram_id}/balance")
async def edit_admin_balance(telegram_id: int, payload: dict, owner: Admin = Depends(require_owner)):
    """Manually corrects an Admin's confirmed balance. Requires the
    literal string "CONFIRM" in `confirm_text` — this mirrors the
    two-step confirmation the panel UI walks the Owner through, enforced
    again here so the safeguard can't be skipped by calling the API
    directly. The change is always logged (see storage.set_admin_balance)
    and the affected Admin is *not* notified — this is a private
    Owner-side correction tool, not a withdrawal action.
    """
    try:
        new_balance = float(payload.get("new_balance"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="new_balance must be a number")
    if new_balance < 0:
        raise HTTPException(status_code=400, detail="new_balance cannot be negative")
    if payload.get("confirm_text") != "CONFIRM":
        raise HTTPException(status_code=400, detail='type CONFIRM to apply this balance change')

    reason = (payload.get("reason") or "").strip() or None
    admin = await storage.set_admin_balance(telegram_id, new_balance, reason, owner.telegram_id)
    if not admin:
        raise HTTPException(status_code=404, detail="admin not found")
    return admin.model_dump()


@app.post("/api/admin/admins/{telegram_id}/status")
async def set_admin_status(telegram_id: int, payload: dict, owner: Admin = Depends(require_owner)):
    status = payload.get("status")
    if status not in ("active", "banned"):
        raise HTTPException(status_code=400, detail="status must be 'active' or 'banned'")
    if telegram_id == owner.telegram_id:
        raise HTTPException(status_code=400, detail="cannot change your own status")
    admin = await storage.set_admin_status(telegram_id, AdminStatus(status))
    if not admin:
        raise HTTPException(status_code=404, detail="admin not found")
    return admin.model_dump()


@app.get("/api/admin/stats")
async def platform_stats(owner: Admin = Depends(require_owner)):
    return await storage.platform_stats()
