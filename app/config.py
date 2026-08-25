import os
from typing import List

# Try loading from .env file if python-dotenv is available, else fallback to os.environ
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class Settings:
    def __init__(self):
        self.BOT_TOKEN: str = os.getenv("BOT_TOKEN", "DEFAULT_TOKEN")
        self.PORT: int = int(os.getenv("PORT", "8000"))
        self.HOST: str = os.getenv("HOST", "0.0.0.0")
        self.WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
        self.WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "tgshort_secret")
        
        # Reward Settings
        self.DAILY_BONUS_COINS: int = int(os.getenv("DAILY_BONUS_COINS", "50"))
        self.REFERRAL_BONUS_COINS: int = int(os.getenv("REFERRAL_BONUS_COINS", "100"))
        self.REFEREE_BONUS_COINS: int = int(os.getenv("REFEREE_BONUS_COINS", "25"))
        
        # Storage Settings
        self.DATA_FILE_PATH: str = os.getenv("DATA_FILE_PATH", "data.json")

    @property
    def admin_ids(self) -> List[int]:
        raw = os.getenv("ADMIN_IDS", "")
        ids = []
        for item in raw.split(","):
            item = item.strip()
            if item.isdigit():
                ids.append(int(item))
        return ids


settings = Settings()
