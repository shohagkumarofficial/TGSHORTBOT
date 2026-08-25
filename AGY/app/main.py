import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from aiogram.types import Update

from app.config import settings
from app.storage.json_storage import JSONStorage
from app.bot.setup import create_bot_and_dispatcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("TGSHORT_Tasks")

# Global instances
storage = JSONStorage(settings.DATA_FILE_PATH)
bot, dp, user_service, task_service = create_bot_and_dispatcher(storage)
polling_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global polling_task
    logger.info("Starting TGSHORT Tasks application...")
    
    # Initialize storage & default tasks
    await storage.init()
    await task_service.init_default_tasks_if_empty()

    # Webhook or Polling mode setup
    if settings.WEBHOOK_URL and settings.WEBHOOK_URL.strip():
        webhook_endpoint = f"{settings.WEBHOOK_URL.rstrip('/')}/webhook"
        logger.info(f"Configuring Telegram Webhook at: {webhook_endpoint}")
        try:
            await bot.set_webhook(
                url=webhook_endpoint,
                secret_token=settings.WEBHOOK_SECRET if settings.WEBHOOK_SECRET else None,
                drop_pending_updates=True
            )
            logger.info("Webhook successfully registered with Telegram!")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
    else:
        logger.info("No WEBHOOK_URL configured. Starting bot in background Polling mode for local testing...")
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            polling_task = asyncio.create_task(dp.start_polling(bot))
        except Exception as e:
            logger.error(f"Failed to start polling: {e}")

    yield

    # Shutdown logic
    logger.info("Shutting down TGSHORT Tasks application...")
    if polling_task and not polling_task.done():
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

    if settings.WEBHOOK_URL:
        try:
            await bot.delete_webhook()
        except Exception:
            pass

    await bot.session.close()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="TGSHORT Tasks API & Bot Service",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
@app.get("/health")
async def health_check():
    """Health check endpoint for Render service uptime monitoring."""
    stats = await user_service.get_stats()
    return {
        "status": "healthy",
        "service": "TGSHORT Tasks Bot",
        "version": "1.0.0",
        "total_users": stats.get("total_users", 0),
        "total_coins": stats.get("total_coins_distributed", 0)
    }


@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    """Telegram webhook endpoint."""
    if settings.WEBHOOK_SECRET and x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
        logger.warning("Unauthorized webhook request with invalid secret token.")
        raise HTTPException(status_code=403, detail="Invalid secret token")

    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
        return JSONResponse(content={"ok": True})
    except Exception as e:
        logger.error(f"Error handling webhook update: {e}")
        return JSONResponse(content={"ok": False, "error": str(e)}, status_code=500)
