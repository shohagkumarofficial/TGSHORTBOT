import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from aiogram.types import Update

import config
import database
from api.routes import router as api_router
from bot.bot_instance import get_bot, dp
from bot.handlers import router as bot_handlers_router
from bot.admin import router as admin_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Wire bot routers
dp.include_router(bot_handlers_router)
dp.include_router(admin_router)

async def setup_webhook():
    if not config.BOT_TOKEN or not config.WEBHOOK_URL:
        logger.warning("BOT_TOKEN or WEBHOOK_URL not set; skipping webhook setup.")
        return {"status": "skipped", "message": "BOT_TOKEN or WEBHOOK_URL missing"}

    bot = get_bot()
    base_url = config.WEBHOOK_URL.rstrip("/")
    if base_url.endswith("/webhook"):
        webhook_endpoint = base_url
    else:
        webhook_endpoint = f"{base_url}/webhook"

    try:
        logger.info(f"Setting Telegram Webhook to: {webhook_endpoint}")
        await bot.set_webhook(
            url=webhook_endpoint,
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"]
        )
        webhook_info = await bot.get_webhook_info()
        logger.info(f"Webhook active. URL: {webhook_info.url}, Pending updates: {webhook_info.pending_update_count}")
        return {
            "status": "success",
            "webhook_url": webhook_endpoint,
            "pending_updates": webhook_info.pending_update_count,
            "last_error_message": webhook_info.last_error_message or "None"
        }
    except Exception as e:
        logger.error(f"Failed to configure webhook: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize Database
    logger.info("Initializing SQLite database...")
    await database.init_db()
    logger.info("Database initialized successfully.")

    # 2. Configure Webhook
    await setup_webhook()

    yield

    # Teardown
    if config.BOT_TOKEN:
        try:
            bot = get_bot()
            await bot.session.close()
        except Exception:
            pass

app = FastAPI(title="Telegram Game Bot & Mini App", lifespan=lifespan)

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Router
app.include_router(api_router)

# Webhook endpoint (with /webhook and fallback alias)
@app.post("/webhook")
@app.post("/webhook/webhook")
async def telegram_webhook(request: Request):
    if not config.BOT_TOKEN:
        return JSONResponse({"status": "error", "message": "BOT_TOKEN not configured"}, status_code=400)
    
    try:
        data = await request.json()
        bot = get_bot()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot=bot, update=update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error processing Telegram update: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}

# Manual Webhook trigger endpoint
@app.get("/set-webhook")
async def trigger_set_webhook():
    result = await setup_webhook()
    return result

# Webhook info check endpoint
@app.get("/webhook-info")
async def get_webhook_status():
    if not config.BOT_TOKEN:
        return {"error": "BOT_TOKEN not set"}
    try:
        bot = get_bot()
        info = await bot.get_webhook_info()
        return {
            "url": info.url,
            "has_custom_certificate": info.has_custom_certificate,
            "pending_update_count": info.pending_update_count,
            "last_error_date": info.last_error_date,
            "last_error_message": info.last_error_message,
            "max_connections": info.max_connections,
            "allowed_updates": info.allowed_updates
        }
    except Exception as e:
        return {"error": str(e)}

# Serve Static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def serve_home():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Telegram Mini App Game Bot API is running!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=config.HOST, port=config.PORT, reload=True)
