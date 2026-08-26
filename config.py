import os
from dotenv import load_dotenv

# Load .env if present (for local development)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
OWNER_TELEGRAM_ID_RAW = os.getenv("OWNER_TELEGRAM_ID", "0").strip()
try:
    OWNER_TELEGRAM_ID = int(OWNER_TELEGRAM_ID_RAW)
except ValueError:
    OWNER_TELEGRAM_ID = 0

WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "").strip().rstrip("/")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
ADSGRAM_BLOCK_ID = os.getenv("ADSGRAM_BLOCK_ID", "").strip()
MONETAG_ZONE_ID = os.getenv("MONETAG_ZONE_ID", "").strip()

PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
DATABASE_PATH = os.getenv("DATABASE_PATH", "game_bot.db")

# Default Game Configuration Constants
DEFAULT_GAMES = [
    {"id": "snake", "name": "🐍 Snake Classic", "enabled": True},
    {"id": "2048", "name": "🔢 2048 Puzzle", "enabled": True},
    {"id": "flappy", "name": "🕊️ Flappy Bird", "enabled": True},
    {"id": "tictactoe", "name": "❌ Tic Tac Toe (AI)", "enabled": True},
    {"id": "memory", "name": "🧠 Memory Match", "enabled": True},
    {"id": "whack", "name": "🔨 Whack-a-Mole", "enabled": True}
]
