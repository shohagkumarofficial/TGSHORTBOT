"""
Local testing runner for TGSHORT Tasks.
Runs in polling mode directly without needing a public webhook URL.
"""
import asyncio
import logging
from app.config import settings
from app.storage.json_storage import JSONStorage
from app.bot.setup import create_bot_and_dispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("TGSHORT_Local")


async def main():
    if settings.BOT_TOKEN == "DEFAULT_TOKEN" or not settings.BOT_TOKEN:
        logger.error("❌ BOT_TOKEN is not set in .env file! Please set your Telegram bot token first.")
        return

    logger.info("Initializing Storage...")
    storage = JSONStorage(settings.DATA_FILE_PATH)
    await storage.init()

    bot, dp, user_service, task_service = create_bot_and_dispatcher(storage)
    await task_service.init_default_tasks_if_empty()

    logger.info("Deleting any existing webhook...")
    await bot.delete_webhook(drop_pending_updates=True)

    bot_user = await bot.get_me()
    logger.info(f"🚀 Bot @{bot_user.username} is running in Polling mode...")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
