"""FastAPI app — webhook receiver, redirect, Mini App API (PRD §9.4).

This single process serves:
  - Telegram bot webhook  (POST /webhook)
  - Health-check         (GET  /health) — keeps Render free tier awake
  - Viewer entry point   (GET  /r/{short_code}) — serves viewer.html
  - Mini App API         (POST /api/...)
  - Static Mini App files (GET  /panel, /static/...)

All Mini App API routes validate Telegram `initData` server-side per
the security note in PRD §9.4.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiogram import types
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

import storage
from bot import bot, build_dispatcher
from config import settings
from cpm_engine import close_cycle_if_due, cycle_tick_loop

dispatcher = build_dispatcher()

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("tgshortbot.app")


# --------------------------------------------------------------------------
# initData validation (Telegram Mini App)
# --------------------------------------------------------------------------

def _validate_init_data(init_data: str, max_age_seconds: int = 3600) -> dict:
    """Verify Telegram WebApp initData signature & freshness.

    Returns parsed fields dict on success, raises HTTPException otherwise.
    """
    if not init_data:
        raise HTTPException(status_code=401, detail="missing initData")
    params = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
    hash_received = params.pop("hash", None)
    if not hash_received:
        raise HTTPException(status_code=401, detail="missing hash")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, hash_received):
        raise HTTPException(status_code=401, detail="bad initData signature")

    # freshness check
    auth_date = int(params.get("auth_date", "0"))
    if abs(int(datetime.utcnow().timestamp()) - auth_date) > max_age_seconds:
        raise HTTPException(status_code=401, detail="initData expired")
    return params


def _user_id_from_init_data(params: dict) -> int:
    raw = params.get("user", "{}")
    try:
        u = json.loads(raw)
        return int(u.get("id", 0))
    except Exception:
        raise HTTPException(status_code=401, detail="bad initData user")


def _is_owner(telegram_id: int) -> bool:
    return telegram_id == settings.owner_telegram_id


# --------------------------------------------------------------------------
# Mini App request bodies
# --------------------------------------------------------------------------

class CreateLinkBody(BaseModel):
    init_data: str
    destination_url: str


class ProofBody(BaseModel):
    init_data: str
    proof_url: str


class LogViewBody(BaseModel):
    init_data: str
    short_code: str
    viewer_telegram_id: int


class WithdrawBody(BaseModel):
    init_data: str
    amount: float
    method: str
    account_number: str


class VerifyLinkBody(BaseModel):
    init_data: str
    decision: str  # "verified" | "rejected"


class CPMBody(BaseModel):
    init_data: str
    mode: str
    current_cpm: float
    cycle_duration_hours: int


class ResolveWithdrawBody(BaseModel):
    init_data: str
    decision: str  # "paid" | "rejected"


# --------------------------------------------------------------------------
# lifespan — webhook registration + cycle tick loop
# --------------------------------------------------------------------------

WEBHOOK_PATH = "/webhook"

dispatcher = build_dispatcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # register webhook with Telegram on startup
    if settings.webhook_url:
        try:
            await bot.set_webhook(settings.webhook_url, drop_pending_updates=True)
            log.info("Webhook set: %s", settings.webhook_url)
        except Exception as e:
            log.warning("set_webhook failed: %s", e)
    import asyncio
    tick_task = asyncio.create_task(cycle_tick_loop())
    try:
        yield
    finally:
        tick_task.cancel()
        try:
            await tick_task
        except Exception:
            pass
        await bot.session.close()


app = FastAPI(title="TGSHORTBOT", lifespan=lifespan)


# --------------------------------------------------------------------------
# static + health
# --------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "webapp"


@app.get("/health")
async def health() -> dict:
    # cheap self-ping — also nudges any due CPM cycle
    await close_cycle_if_due()
    return {"ok": True, "ts": datetime.utcnow().isoformat()}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> dict:
    update = types.Update.model_validate(await request.json())
    await dispatcher.feed_update(bot, update)
    return {"ok": True}


# --------------------------------------------------------------------------
# viewer entry point — serves the HTML Mini App pre-loaded with the code
# --------------------------------------------------------------------------

@app.get("/r/{short_code}")
async def entry(short_code: str) -> Response:
    link = storage.get_link(short_code)
    if not link:
        return HTMLResponse("<h1>Link not found</h1>", status_code=404)
    html_path = STATIC_DIR / "viewer.html"
    if not html_path.exists():
        return HTMLResponse("<h1>viewer.html missing</h1>", status_code=500)
    html = html_path.read_text(encoding="utf-8")
    # Inject runtime config (block id + short code)
    inject = (
        f"<script>window.__TG_SHORT_CODE = {json.dumps(short_code)};"
        f"window.__ADSGRAM_BLOCK_ID = {json.dumps(settings.adsgram_block_id)};</script>"
    )
    html = html.replace("</head>", f"{inject}</head>", 1)
    return HTMLResponse(html)


# --------------------------------------------------------------------------
# static panel
# --------------------------------------------------------------------------

@app.get("/panel")
async def panel() -> Response:
    return FileResponse(STATIC_DIR / "panel.html")


# --------------------------------------------------------------------------
# API: viewer flow
# --------------------------------------------------------------------------

@app.post("/api/log-view")
async def api_log_view(body: LogViewBody) -> dict:
    params = _validate_init_data(body.init_data)
    requester = _user_id_from_init_data(params)
    # The viewer who loaded the Mini App must be the one logging the view.
    if requester != body.viewer_telegram_id:
        raise HTTPException(status_code=403, detail="user mismatch")

    link = storage.get_link(body.short_code)
    if not link:
        raise HTTPException(status_code=404, detail="unknown link")
    if await storage.has_viewer_seen(body.short_code, body.viewer_telegram_id):
        # dedupe — still return destination so UX doesn't break,
        # but no new view row, no earnings credit
        return {"ok": True, "duplicate": True, "destination_url": link.destination_url}

    await storage.record_view(body.short_code, body.viewer_telegram_id)
    return {"ok": True, "destination_url": link.destination_url}


@app.get("/api/link/{short_code}")
async def api_link(short_code: str, init_data: str) -> dict:
    params = _validate_init_data(init_data)
    _ = _user_id_from_init_data(params)  # auth only
    link = storage.get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="unknown link")
    return {"destination_url": link.destination_url}


# --------------------------------------------------------------------------
# API: admin — links
# --------------------------------------------------------------------------

@app.post("/api/links")
async def api_create_link(body: CreateLinkBody) -> dict:
    params = _validate_init_data(body.init_data)
    uid = _user_id_from_init_data(params)
    admin = await storage.get_or_create_admin(uid)
    if admin.status.value == "banned":
        raise HTTPException(status_code=403, detail="banned")
    link = await storage.create_link(uid, body.destination_url)
    return {"short_code": link.short_code}


@app.patch("/api/links/{short_code}/proof")
async def api_set_proof(short_code: str, body: ProofBody) -> dict:
    params = _validate_init_data(body.init_data)
    uid = _user_id_from_init_data(params)
    link = storage.get_link(short_code)
    if not link or link.owner_telegram_id != uid:
        raise HTTPException(status_code=403, detail="not your link")
    link = await storage.set_link_proof(short_code, body.proof_url)
    return {"ok": True, "verification_status": link.verification_status.value}


@app.get("/api/my/links")
async def api_my_links(init_data: str) -> dict:
    params = _validate_init_data(init_data)
    uid = _user_id_from_init_data(params)
    links = storage.list_links(owner_telegram_id=uid)
    return {
        "links": [
            {
                "short_code": l.short_code,
                "destination_url": l.destination_url,
                "proof_url": l.proof_url,
                "verification_status": l.verification_status.value,
                "views": len(storage.list_views_for_link(l.short_code)),
                "created_at": l.created_at.isoformat(),
            }
            for l in links
        ]
    }


@app.get("/api/me")
async def api_me(init_data: str) -> dict:
    params = _validate_init_data(init_data)
    uid = _user_id_from_init_data(params)
    admin = await storage.get_or_create_admin(uid)
    return {
        "telegram_id": admin.telegram_id,
        "username": admin.username,
        "role": admin.role.value,
        "balance_confirmed": admin.balance_confirmed,
        "balance_pending": admin.balance_pending,
        "is_owner": _is_owner(uid),
    }


# --------------------------------------------------------------------------
# API: CPM
# --------------------------------------------------------------------------

@app.get("/api/cpm")
async def api_get_cpm(init_data: str) -> dict:
    _ = _validate_init_data(init_data)
    cpm = storage.get_cpm()
    return {
        "mode": cpm.mode.value,
        "current_cpm": cpm.current_cpm,
        "cycle_duration_hours": cpm.cycle_duration_hours,
        "cycle_started_at": cpm.cycle_started_at.isoformat(),
        "cycle_id": cpm.cycle_id,
    }


@app.post("/api/admin/cpm")
async def api_set_cpm(body: CPMBody) -> dict:
    params = _validate_init_data(body.init_data)
    uid = _user_id_from_init_data(params)
    if not _is_owner(uid):
        raise HTTPException(status_code=403, detail="owner only")
    if body.mode not in ("realtime", "scheduled"):
        raise HTTPException(status_code=400, detail="bad mode")
    if body.current_cpm < 0 or body.cycle_duration_hours <= 0:
        raise HTTPException(status_code=400, detail="bad value")
    cpm = await storage.update_cpm(body.mode, body.current_cpm, body.cycle_duration_hours, uid)
    return {"ok": True, "cpm": cpm.model_dump(mode="json")}


# --------------------------------------------------------------------------
# API: withdrawals
# --------------------------------------------------------------------------

@app.post("/api/withdraw")
async def api_withdraw(body: WithdrawBody) -> dict:
    params = _validate_init_data(body.init_data)
    uid = _user_id_from_init_data(params)
    admin = await storage.get_or_create_admin(uid)
    if body.method not in ("bkash", "nagad"):
        raise HTTPException(status_code=400, detail="bad method")
    if body.amount <= 0 or body.amount > admin.balance_confirmed:
        raise HTTPException(status_code=400, detail="bad amount")
    w = await storage.create_withdraw(uid, body.amount, body.method, body.account_number)
    return {"ok": True, "request_id": w.request_id}


@app.get("/api/my/withdrawals")
async def api_my_withdrawals(init_data: str) -> dict:
    params = _validate_init_data(init_data)
    uid = _user_id_from_init_data(params)
    ws = [w for w in storage.list_withdrawals() if w.admin_telegram_id == uid]
    return {"withdrawals": [w.model_dump(mode="json") for w in ws]}


# --------------------------------------------------------------------------
# API: owner
# --------------------------------------------------------------------------

@app.get("/api/admin/links")
async def api_admin_links(init_data: str) -> dict:
    params = _validate_init_data(init_data)
    uid = _user_id_from_init_data(params)
    if not _is_owner(uid):
        raise HTTPException(status_code=403, detail="owner only")
    pending = storage.list_pending_proof_links()
    all_links = storage.list_links()
    return {
        "pending": [
            {
                "short_code": l.short_code,
                "owner_telegram_id": l.owner_telegram_id,
                "destination_url": l.destination_url,
                "proof_url": l.proof_url,
                "views": len(storage.list_views_for_link(l.short_code)),
                "created_at": l.created_at.isoformat(),
            }
            for l in pending
        ],
        "all": [
            {
                "short_code": l.short_code,
                "owner_telegram_id": l.owner_telegram_id,
                "destination_url": l.destination_url,
                "verification_status": l.verification_status.value,
                "views": len(storage.list_views_for_link(l.short_code)),
            }
            for l in all_links
        ],
    }


@app.post("/api/admin/links/{short_code}/verify")
async def api_verify_link(short_code: str, body: VerifyLinkBody) -> dict:
    params = _validate_init_data(body.init_data)
    uid = _user_id_from_init_data(params)
    if not _is_owner(uid):
        raise HTTPException(status_code=403, detail="owner only")
    if body.decision not in ("verified", "rejected"):
        raise HTTPException(status_code=400, detail="bad decision")
    from models import VerificationStatus
    status = VerificationStatus(body.decision)
    link = await storage.set_link_verification(short_code, status)
    if not link:
        raise HTTPException(status_code=404, detail="unknown link")
    return {"ok": True, "verification_status": link.verification_status.value}


@app.get("/api/admin/withdrawals")
async def api_admin_withdrawals(init_data: str) -> dict:
    params = _validate_init_data(init_data)
    uid = _user_id_from_init_data(params)
    if not _is_owner(uid):
        raise HTTPException(status_code=403, detail="owner only")
    from models import WithdrawStatus
    ws = storage.list_withdrawals(status=WithdrawStatus.PENDING)
    return {"withdrawals": [w.model_dump(mode="json") for w in ws]}


@app.post("/api/admin/withdrawals/{request_id}/resolve")
async def api_resolve_withdraw(request_id: str, body: ResolveWithdrawBody) -> dict:
    params = _validate_init_data(body.init_data)
    uid = _user_id_from_init_data(params)
    if not _is_owner(uid):
        raise HTTPException(status_code=403, detail="owner only")
    if body.decision not in ("paid", "rejected"):
        raise HTTPException(status_code=400, detail="bad decision")
    w = await storage.resolve_withdraw(request_id, body.decision)
    if not w:
        raise HTTPException(status_code=400, detail="cannot resolve")
    return {"ok": True, "status": w.status.value}


@app.get("/api/admin/admins")
async def api_admin_admins(init_data: str) -> dict:
    params = _validate_init_data(init_data)
    uid = _user_id_from_init_data(params)
    if not _is_owner(uid):
        raise HTTPException(status_code=403, detail="owner only")
    admins = storage.list_admins()
    return {
        "admins": [
            {
                "telegram_id": a.telegram_id,
                "username": a.username,
                "role": a.role.value,
                "balance_confirmed": a.balance_confirmed,
                "balance_pending": a.balance_pending,
                "status": a.status.value,
            }
            for a in admins
        ]
    }
