import asyncio
import hashlib
import hmac
import json
import logging
import time
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, unquote
from typing import Dict, Any, Optional
from uuid import UUID

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Update
from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from storage import Storage
from models import Admin, Link, View, CPMSetting, WithdrawRequest, CPMAuditLog
from cpm_engine import CPMEngine, start_cpm_background_task
import bot as bot_module

logger = logging.getLogger(__name__)

# Initialize core components
storage = Storage()
cpm_engine = CPMEngine(storage)
bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
background_tasks = set()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up FastAPI application")
    
    # 1. Setup bot_module & router
    try:
        bot_info = await bot.get_me()
        bot_module.setup(storage, cpm_engine, settings, bot_info.username)
        dp.include_router(bot_module.router)
    except Exception as e:
        logger.error(f"Error initializing bot info or router: {e}")

    # 2. Set webhook URL with secret token
    webhook_url = settings.WEBHOOK_URL or f"{settings.WEBAPP_BASE_URL}/webhook"
    if webhook_url.startswith("http"):
        try:
            await bot.set_webhook(
                url=webhook_url,
                secret_token=settings.WEBHOOK_SECRET if settings.WEBHOOK_SECRET else None,
                drop_pending_updates=False
            )
            logger.info(f"Webhook set to {webhook_url}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
    else:
        logger.warning(f"WEBHOOK_URL or WEBAPP_BASE_URL not configured properly: {webhook_url}")
    
    # 3. Start CPM background task
    task = asyncio.create_task(start_cpm_background_task(cpm_engine))
    background_tasks.add(task)
    
    # 4. Initialize CPM setting
    storage.init_cpm_setting(settings.OWNER_TELEGRAM_ID)
    
    yield
    
    # Shutdown:
    logger.info("Shutting down FastAPI application")
    for task in background_tasks:
        task.cancel()
    
    # DO NOT call delete_webhook on shutdown so Telegram keeps webhook registered
    try:
        await bot.session.close()
    except Exception as e:
        logger.error(f"Error closing bot session: {e}")

app = FastAPI(lifespan=lifespan)

# Telegram initData Validation
def validate_telegram_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="Missing initData")
        
    parsed_data = parse_qs(init_data)
    
    if "hash" not in parsed_data:
        raise HTTPException(status_code=401, detail="Missing hash in initData")
        
    received_hash = parsed_data.pop("hash")[0]
    
    # Sort remaining params alphabetically
    data_check_string = "\n".join(
        f"{key}={unquote(parsed_data[key][0])}" 
        for key in sorted(parsed_data.keys())
    )
    
    secret_key = hmac.new(
        key=b"WebAppData", 
        msg=settings.BOT_TOKEN.encode("utf-8"), 
        digestmod=hashlib.sha256
    ).digest()
    
    calculated_hash = hmac.new(
        key=secret_key, 
        msg=data_check_string.encode("utf-8"), 
        digestmod=hashlib.sha256
    ).hexdigest()
    
    if calculated_hash != received_hash:
        raise HTTPException(status_code=401, detail="Invalid initData hash")
        
    auth_date = int(parsed_data.get("auth_date", [0])[0])
    if time.time() - auth_date > 86400: # 24 hours
        raise HTTPException(status_code=401, detail="initData expired")
        
    user_data = json.loads(unquote(parsed_data.get("user", ["{}"])[0]))
    return user_data

async def get_telegram_user(request: Request) -> dict:
    """FastAPI dependency that extracts and validates Telegram user from initData."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("tma "):
        init_data = auth_header[4:]
    else:
        init_data = request.query_params.get("tgWebAppData")
        
    if not init_data:
        try:
            body = await request.json()
            init_data = body.get("init_data")
        except:
            pass
            
    return validate_telegram_init_data(init_data)

async def require_owner(user: dict = Depends(get_telegram_user)):
    if user.get("id") != settings.OWNER_TELEGRAM_ID:
        raise HTTPException(status_code=403, detail="Forbidden: Owner access required")
    return user

# Models for request bodies
class LogViewRequest(BaseModel):
    short_code: str
    init_data: str

class CreateLinkRequest(BaseModel):
    destination_url: str

class UpdateCPMRequest(BaseModel):
    mode: Optional[str] = None
    current_cpm: Optional[float] = None
    cycle_duration_hours: Optional[int] = None

class CreateWithdrawalRequest(BaseModel):
    amount: float
    method: str
    account_number: str

# Routes
@app.get("/")
async def root():
    return RedirectResponse(url="/panel")

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}

@app.post("/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)):
    if settings.WEBHOOK_SECRET and x_telegram_bot_api_secret_token:
        if x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
            logger.warning(f"Secret token mismatch on /webhook. Received: {x_telegram_bot_api_secret_token}")
            raise HTTPException(status_code=401, detail="Invalid secret token")
            
    try:
        update_data = await request.json()
        update = Update(**update_data)
        await dp.feed_update(bot, update)
    except Exception as e:
        logger.error(f"Error processing Telegram update: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

    return {"status": "ok"}

@app.get("/r/{short_code}", response_class=HTMLResponse)
async def viewer_page(short_code: str):
    link = storage.get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
        
    try:
        with open("webapp/viewer.html", "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Viewer template not found")
        
    html = html.replace("{{SHORT_CODE}}", short_code)
    html = html.replace("{{ADSGRAM_BLOCK_ID}}", settings.ADSGRAM_BLOCK_ID)
    html = html.replace("{{API_BASE_URL}}", settings.WEBAPP_BASE_URL)
    
    return HTMLResponse(content=html)

@app.get("/panel", response_class=HTMLResponse)
async def panel_page():
    try:
        with open("webapp/panel.html", "r", encoding="utf-8") as f:
            html = f.read()
        html = html.replace("{{API_BASE_URL}}", settings.WEBAPP_BASE_URL)
        return HTMLResponse(content=html)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Panel template not found")

# === Mini App API Routes ===

@app.post("/api/log-view")
async def log_view(req: LogViewRequest, request: Request):
    try:
        user_data = validate_telegram_init_data(req.init_data)
        viewer_id = user_data.get("id")
        if not viewer_id:
            raise HTTPException(status_code=401, detail="Invalid user data")
            
        link = storage.get_link(req.short_code)
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
            
        if storage.is_duplicate_view(req.short_code, viewer_id):
            return {"success": True, "destination_url": link.destination_url, "paid": False}
            
        view = View(
            short_code=req.short_code,
            viewer_telegram_id=viewer_id,
            counted_status="unverified"
        )
        storage.log_view(view)
        earned = cpm_engine.process_view(view, link)
        return {"success": True, "destination_url": link.destination_url, "paid": earned > 0}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error logging view: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/link/{short_code}")
async def get_link_destination(short_code: str):
    link = storage.get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"destination_url": link.destination_url}

@app.post("/api/links")
async def create_link(req: CreateLinkRequest, user: dict = Depends(get_telegram_user)):
    admin_id = user["id"]
    admin = storage.get_admin(admin_id)
    if not admin or admin.status == "banned":
        raise HTTPException(status_code=403, detail="Not an active admin")
        
    short_code = hashlib.md5(f"{admin_id}_{time.time()}".encode()).hexdigest()[:6]
    
    link = Link(
        short_code=short_code,
        owner_telegram_id=admin_id,
        destination_url=req.destination_url,
        verification_status="pending"
    )
    storage.create_link(link)
    
    return {"short_code": short_code, "verification_status": "pending"}

@app.patch("/api/links/{short_code}/proof")
async def update_proof(short_code: str, request: Request, user: dict = Depends(get_telegram_user)):
    admin_id = user["id"]
    link = storage.get_link(short_code)
    if not link or link.owner_telegram_id != admin_id:
        raise HTTPException(status_code=404, detail="Link not found or unauthorized")
        
    body = await request.json()
    proof_url = body.get("proof_url")
    if proof_url:
        storage.update_link_proof(short_code, proof_url)
    return {"success": True}

@app.get("/api/my/stats")
async def my_stats(user: dict = Depends(get_telegram_user)):
    admin_id = user["id"]
    admin = storage.get_admin(admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
        
    links = storage.get_links_by_admin(admin_id)
    withdrawals = storage.get_withdrawals_by_admin(admin_id)
    
    total_views = sum(storage.count_views_by_link(l.short_code) for l in links)
    cycle_info = cpm_engine.get_cycle_info()
    
    return {
        "role": admin.role,
        "balance_confirmed": admin.balance_confirmed,
        "balance_pending": admin.balance_pending,
        "total_views": total_views,
        "links": [l.model_dump() for l in links],
        "withdrawals": [w.model_dump() for w in withdrawals],
        "cycle_info": cycle_info
    }

@app.get("/api/admin/links")
async def admin_list_links(user: dict = Depends(require_owner)):
    links = storage.get_pending_links()
    return [l.model_dump() for l in links]

@app.post("/api/admin/links/{short_code}/verify")
async def admin_verify_link(short_code: str, request: Request, user: dict = Depends(require_owner)):
    body = await request.json()
    decision = body.get("decision")
    
    if decision == "verified":
        cpm_engine.on_link_verified(short_code)
    elif decision == "rejected":
        cpm_engine.on_link_rejected(short_code)
    else:
        raise HTTPException(status_code=400, detail="Invalid decision")
        
    return {"success": True}

@app.get("/api/cpm")
async def get_cpm():
    return cpm_engine.get_cycle_info()

@app.post("/api/admin/cpm")
async def admin_update_cpm(req: UpdateCPMRequest, user: dict = Depends(require_owner)):
    owner_id = user["id"]
    if req.current_cpm is not None:
        cpm_engine.change_cpm_rate(req.current_cpm, owner_id)
    if req.mode is not None:
        duration = req.cycle_duration_hours or 24
        cpm_engine.change_mode(req.mode, owner_id, duration)
        
    return cpm_engine.get_cycle_info()

@app.post("/api/withdraw")
async def create_withdrawal(req: CreateWithdrawalRequest, user: dict = Depends(get_telegram_user)):
    admin_id = user["id"]
    admin = storage.get_admin(admin_id)
    if not admin or admin.status == "banned":
        raise HTTPException(status_code=403, detail="Forbidden")
        
    if admin.balance_confirmed < req.amount or req.amount < settings.MIN_WITHDRAWAL_AMOUNT:
        raise HTTPException(status_code=400, detail="Invalid amount or below minimum")
        
    withdraw_req = WithdrawRequest(
        admin_telegram_id=admin_id,
        amount=req.amount,
        method=req.method,
        account_number=req.account_number
    )
    storage.create_withdraw_request(withdraw_req)
    return withdraw_req.model_dump()

@app.get("/api/admin/withdrawals")
async def admin_list_withdrawals(user: dict = Depends(require_owner)):
    withdrawals = storage.get_pending_withdrawals()
    return [w.model_dump() for w in withdrawals]

@app.post("/api/admin/withdrawals/{request_id}/resolve")
async def admin_resolve_withdrawal(request_id: str, request: Request, user: dict = Depends(require_owner)):
    body = await request.json()
    decision = body.get("decision")
    reason = body.get("reason")
    
    try:
        req_uuid = UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request_id UUID")
        
    if decision == "paid":
        pending_reqs = storage.get_pending_withdrawals()
        target_req = next((r for r in pending_reqs if str(r.request_id) == request_id), None)
        if target_req:
            storage.debit_admin_balance(target_req.admin_telegram_id, target_req.amount)
        storage.resolve_withdrawal(req_uuid, "paid")
    elif decision == "rejected":
        storage.resolve_withdrawal(req_uuid, "rejected", reason)
    else:
        raise HTTPException(status_code=400, detail="Invalid decision")
        
    return {"success": True}

@app.get("/api/admin/admins")
async def admin_list_admins(user: dict = Depends(require_owner)):
    admins = storage.get_all_admins()
    return [a.model_dump() for a in admins]

@app.post("/api/admin/admins/{telegram_id}/ban")
async def admin_ban_toggle(telegram_id: int, request: Request, user: dict = Depends(require_owner)):
    body = await request.json()
    action = body.get("action")
    
    if action == "ban":
        storage.ban_admin(telegram_id)
    elif action == "unban":
        storage.unban_admin(telegram_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid action")
        
    return {"success": True}

@app.get("/api/admin/stats")
async def admin_platform_stats(user: dict = Depends(require_owner)):
    links = storage.get_all_links()
    admins = storage.get_all_admins()
    pending_withdrawals = storage.get_pending_withdrawals()
    
    total_views = sum(storage.count_views_by_link(l.short_code) for l in links)
    total_pending_liability = sum(a.balance_confirmed + a.balance_pending for a in admins)
    
    return {
        "total_admins": len(admins),
        "total_links": len(links),
        "total_views": total_views,
        "pending_withdrawals": len(pending_withdrawals),
        "total_pending_liability": total_pending_liability
    }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
