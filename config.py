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
    OWNER_TELEGRAM_ID: int
    PORT: int
    WEBAPP_BASE_URL: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    CPM_CHECK_INTERVAL_SECONDS: int
    MINI_APP_SHORT_NAME: str


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
        OWNER_TELEGRAM_ID=int(_require("OWNER_TELEGRAM_ID")),
        PORT=int(os.environ.get("PORT", "8000")),
        WEBAPP_BASE_URL=_require("WEBAPP_BASE_URL").rstrip("/"),
        # Supabase Project URL (e.g. https://xxxx.supabase.co) and the
        # SECRET / service_role API key — never the anon/publishable one,
        # since this backend needs to bypass Row Level Security to read
        # and write every Admin's data. See Settings -> API Keys in the
        # Supabase dashboard.
        SUPABASE_URL=_require("SUPABASE_URL"),
        SUPABASE_KEY=_require("SUPABASE_KEY"),
        CPM_CHECK_INTERVAL_SECONDS=int(os.environ.get("CPM_CHECK_INTERVAL_SECONDS", "60")),
        # Optional. Only set this once you've run /newapp in @BotFather and
        # attached a Mini App to this bot with a short name (e.g. "unlock"),
        # pointed at {WEBAPP_BASE_URL}/r. When set, shared short links use
        # Telegram's "direct link Mini App" format
        # (t.me/<bot>/<short_name>?startapp=<code>), which opens the ad-lock
        # page immediately — no chat, no extra button tap. Left blank, the
        # bot falls back to the original t.me/<bot>?start=<code> flow (opens
        # the chat first with a "চালিয়ে যান" button). See README.md.
        MINI_APP_SHORT_NAME=os.environ.get("MINI_APP_SHORT_NAME", "").strip().lstrip("@"),
    )
