import os
import secrets
from dataclasses import dataclass, field

@dataclass
class Settings:
    """Settings class to manage environment variables with sensible defaults."""
    BOT_TOKEN: str
    OWNER_TELEGRAM_ID: int
    WEBHOOK_URL: str = ""
    ADSGRAM_BLOCK_ID: str = ""
    PORT: int = 10000
    WEBAPP_BASE_URL: str = ""
    WEBHOOK_SECRET: str = field(default_factory=lambda: secrets.token_hex(16))
    MIN_WITHDRAWAL_AMOUNT: float = 50.0

    @classmethod
    def load(cls) -> "Settings":
        bot_token = os.environ.get("BOT_TOKEN")
        if not bot_token:
            raise ValueError("BOT_TOKEN is required in environment variables. (BOT_TOKEN এনভায়রনমেন্ট ভ্যারিয়েবলে দেওয়া আবশ্যক)")
        
        owner_id_str = os.environ.get("OWNER_TELEGRAM_ID")
        if not owner_id_str:
            raise ValueError("OWNER_TELEGRAM_ID is required in environment variables. (OWNER_TELEGRAM_ID এনভায়রনমেন্ট ভ্যারিয়েবলে দেওয়া আবশ্যক)")
        
        return cls(
            BOT_TOKEN=bot_token,
            OWNER_TELEGRAM_ID=int(owner_id_str),
            WEBHOOK_URL=os.environ.get("WEBHOOK_URL", ""),
            ADSGRAM_BLOCK_ID=os.environ.get("ADSGRAM_BLOCK_ID", ""),
            PORT=int(os.environ.get("PORT", "10000")),
            WEBAPP_BASE_URL=os.environ.get("WEBAPP_BASE_URL", ""),
            MIN_WITHDRAWAL_AMOUNT=float(os.environ.get("MIN_WITHDRAWAL_AMOUNT", "50.0"))
        )

# Validate and load settings on import
settings = Settings.load()
