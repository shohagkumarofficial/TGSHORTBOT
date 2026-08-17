"""Manual helper for the Telegram webhook.

The app already sets its webhook automatically on startup (see app.py's
lifespan handler), so you normally won't need this — but it's handy for
debugging, or for setting the webhook without a full deploy.

Usage (run from the project root):
    python -m scripts.set_webhook set
    python -m scripts.set_webhook delete
    python -m scripts.set_webhook info
"""
from __future__ import annotations

import asyncio
import sys

from aiogram import Bot

from config import get_settings


async def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "set"
    settings = get_settings()
    bot = Bot(token=settings.BOT_TOKEN)
    try:
        if action == "delete":
            await bot.delete_webhook(drop_pending_updates=False)
            print("Webhook deleted.")
        elif action == "info":
            info = await bot.get_webhook_info()
            print(info.model_dump_json(indent=2))
        else:
            await bot.set_webhook(url=settings.WEBHOOK_URL, secret_token=settings.WEBHOOK_SECRET)
            info = await bot.get_webhook_info()
            print(f"Webhook set to: {info.url}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
