"""Environment configuration for TGSHORTBOT.

Settings are only read (and validated) the first time get_settings() is
called, never at import time — this lets modules import `config` freely
(e.g. for tooling, tests) without requiring every env var to be present.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    BOT_TOKEN: str
    BOT_USERNAME: str
    WEBHOOK_URL: str
    WEBHOOK_SECRET: str
    ADSGRAM_BLOCK_ID: str
    OWNER_TELEGRAM_ID: int
    PORT: int
    WEBAPP_BASE_URL: str
    DATA_FILE: str
    CPM_CHECK_INTERVAL_SECONDS: int


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Copy .env.example to .env (or set it in Render's dashboard) and fill it in."
        )
    return val


@lru_cache
def get_settings() -> Settings:
    return Settings(
        BOT_TOKEN=_require("BOT_TOKEN"),
        BOT_USERNAME=_require("BOT_USERNAME").lstrip("@"),
        WEBHOOK_URL=_require("WEBHOOK_URL"),
        WEBHOOK_SECRET=os.environ.get("WEBHOOK_SECRET", "tgshortbot-secret"),
        ADSGRAM_BLOCK_ID=_require("ADSGRAM_BLOCK_ID"),
        OWNER_TELEGRAM_ID=int(_require("OWNER_TELEGRAM_ID")),
        PORT=int(os.environ.get("PORT", "8000")),
        WEBAPP_BASE_URL=_require("WEBAPP_BASE_URL").rstrip("/"),
        DATA_FILE=os.environ.get("DATA_FILE", "data/store.json"),
        CPM_CHECK_INTERVAL_SECONDS=int(os.environ.get("CPM_CHECK_INTERVAL_SECONDS", "60")),
    )
