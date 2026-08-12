"""Environment configuration for TGSHORTBOT.

All runtime settings come from environment variables (12-factor). Render
provides PORT automatically; the rest are set in the Render dashboard or
a local .env file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(key: str, default: str | None = None, required: bool = False) -> str:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val or ""


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    # Telegram
    bot_token: str
    owner_telegram_id: int
    webhook_url: str  # full URL e.g. https://tgshortbot.onrender.com/webhook

    # Adsgram
    adsgram_block_id: str

    # Hosting
    port: int  # Render sets this
    webapp_base_url: str  # public base URL of the service

    # Storage
    store_path: str

    # Misc
    log_level: str

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            bot_token=_env("BOT_TOKEN", required=True),
            owner_telegram_id=_env_int("OWNER_TELEGRAM_ID", 0),
            webhook_url=_env("WEBHOOK_URL", ""),
            adsgram_block_id=_env("ADSGRAM_BLOCK_ID", ""),
            port=_env_int("PORT", 10000),
            webapp_base_url=_env("WEBAPP_BASE_URL", ""),
            store_path=_env("STORE_PATH", "data/store.json"),
            log_level=_env("LOG_LEVEL", "INFO"),
        )


settings = Settings.load()
