import os
import aiosqlite
import datetime
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional, Tuple
import config

@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode = WAL;")
        await db.execute("PRAGMA synchronous = NORMAL;")
        yield db

async def init_db():
    async with get_db() as db:
        # 1. Users Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                lives INTEGER DEFAULT 3,
                last_regen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Game Sessions Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS game_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                game_id TEXT NOT NULL,
                score INTEGER DEFAULT 0,
                result TEXT DEFAULT 'completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. Ad Views Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ad_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                network TEXT NOT NULL,
                reward_claimed BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 4. Settings Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()

        # Seed initial settings
        default_settings = {
            "default_lives": "3",
            "max_free_lives": "3",            # Cap for free auto-regen
            "regen_interval_minutes": "30",
            "life_deduct_mode": "on_loss",      # 'on_loss' or 'on_start'
            "ad_selection_mode": "round_robin", # 'single' or 'round_robin'
            "selected_ad_network": "adsgram",   # used when mode == 'single'
            
            # Ad Networks Individual Switches & Keys
            "adsgram_enabled": "1",
            "adsgram_block_id": config.ADSGRAM_BLOCK_ID or "int-4166",
            "monetag_enabled": "1",
            "monetag_zone_id": config.MONETAG_ZONE_ID or "",
            "gigapub_enabled": "1" if config.GIGAPUB_PROJECT_ID else "0",
            "gigapub_project_id": config.GIGAPUB_PROJECT_ID or "",
            "adsterra_enabled": "1" if config.ADSTERRA_KEY else "0",
            "adsterra_key": config.ADSTERRA_KEY or "",
            "ad_cooldown_seconds": "20",
            
            # 9 Games Switches
            "game_snake": "1",
            "game_2048": "1",
            "game_flappy": "1",
            "game_tictactoe": "1",
            "game_memory": "1",
            "game_whack": "1",
            "game_space": "1",
            "game_racer": "1",
            "game_breakout": "1"
        }

        for key, val in default_settings.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, str(val))
            )
        await db.commit()

# --- Settings Repository ---

async def get_setting(key: str, default: str = "") -> str:
    async with get_db() as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else default

async def set_setting(key: str, value: str):
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO settings (key, value, updated_at) 
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (key, str(value))
        )
        await db.commit()

async def get_all_settings() -> Dict[str, str]:
    async with get_db() as db:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}

# --- User & Life Engine Repository ---

def parse_iso_datetime(dt_str: Optional[str]) -> datetime.datetime:
    if not dt_str:
        return datetime.datetime.now(datetime.timezone.utc)
    try:
        if "T" in dt_str:
            return datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc)

async def calculate_life_regen(user_row: aiosqlite.Row, max_free_lives: int, interval_minutes: int) -> Tuple[int, int, datetime.datetime]:
    """
    Calculates regenerated lives.
    Rule: Auto-regen ONLY fills up to max_free_lives (default: 3).
    If user has >= max_free_lives (e.g. 5, 10 lives from watching ads), timer is stopped (0 seconds).
    """
    current_lives = int(user_row["lives"])
    last_regen_at = parse_iso_datetime(user_row["last_regen_at"])
    now = datetime.datetime.now(datetime.timezone.utc)
    
    if interval_minutes <= 0 or current_lives >= max_free_lives:
        return current_lives, 0, now

    interval_seconds = interval_minutes * 60
    elapsed_seconds = max(0, int((now - last_regen_at).total_seconds()))
    gained_lives = elapsed_seconds // interval_seconds

    if gained_lives > 0:
        updated_lives = min(max_free_lives, current_lives + gained_lives)
        if updated_lives >= max_free_lives:
            new_last_regen = now
            seconds_until_next = 0
        else:
            new_last_regen = last_regen_at + datetime.timedelta(seconds=gained_lives * interval_seconds)
            remaining_seconds = interval_seconds - (elapsed_seconds % interval_seconds)
            seconds_until_next = max(0, remaining_seconds)
        
        async with get_db() as db:
            await db.execute(
                "UPDATE users SET lives = ?, last_regen_at = ? WHERE telegram_id = ?",
                (updated_lives, new_last_regen.strftime("%Y-%m-%d %H:%M:%S"), user_row["telegram_id"])
            )
            await db.commit()
        return updated_lives, seconds_until_next, new_last_regen
    else:
        seconds_until_next = max(0, interval_seconds - elapsed_seconds)
        return current_lives, seconds_until_next, last_regen_at

async def get_or_create_user(telegram_id: int, first_name: str = "", last_name: str = "", username: str = "") -> Dict[str, Any]:
    settings = await get_all_settings()
    default_lives = int(settings.get("default_lives", "3"))
    max_free_lives = int(settings.get("max_free_lives", "3"))
    regen_interval = int(settings.get("regen_interval_minutes", "30"))

    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = await cursor.fetchone()

        if not user:
            await db.execute(
                """
                INSERT INTO users (telegram_id, first_name, last_name, username, lives, last_regen_at, created_at, last_active_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (telegram_id, first_name, last_name, username, default_lives, now_str, now_str, now_str)
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = await cursor.fetchone()
        else:
            await db.execute(
                """
                UPDATE users SET first_name = ?, last_name = ?, username = ?, last_active_at = ?
                WHERE telegram_id = ?
                """,
                (first_name or user["first_name"], last_name or user["last_name"], username or user["username"], now_str, telegram_id)
            )
            await db.commit()

    lives, seconds_until_regen, last_regen_at = await calculate_life_regen(user, max_free_lives, regen_interval)

    return {
        "telegram_id": user["telegram_id"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "username": user["username"],
        "lives": lives,
        "max_free_lives": max_free_lives,
        "seconds_until_regen": seconds_until_regen,
        "regen_interval_minutes": regen_interval,
        "created_at": user["created_at"]
    }

async def deduct_life(telegram_id: int) -> Tuple[bool, int]:
    settings = await get_all_settings()
    max_free_lives = int(settings.get("max_free_lives", "3"))
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    async with get_db() as db:
        cursor = await db.execute("SELECT lives, last_regen_at FROM users WHERE telegram_id = ?", (telegram_id,))
        user = await cursor.fetchone()
        if not user or user["lives"] <= 0:
            return False, 0 if not user else user["lives"]

        current_lives = user["lives"]
        new_lives = current_lives - 1

        # If dropping below max_free_lives, start countdown clock from now
        if current_lives == max_free_lives:
            await db.execute(
                "UPDATE users SET lives = ?, last_regen_at = ? WHERE telegram_id = ?",
                (new_lives, now_str, telegram_id)
            )
        else:
            await db.execute(
                "UPDATE users SET lives = ? WHERE telegram_id = ?",
                (new_lives, telegram_id)
            )
        await db.commit()
        return True, new_lives

async def add_life(telegram_id: int, count: int = 1) -> Tuple[bool, int]:
    """
    Adds lives from watching Rewarded Ads.
    Rule: Ads grant UNLIMITED stacked lives (no cap of 3)!
    """
    async with get_db() as db:
        cursor = await db.execute("SELECT lives FROM users WHERE telegram_id = ?", (telegram_id,))
        user = await cursor.fetchone()
        if not user:
            return False, 0

        current_lives = user["lives"]
        new_lives = current_lives + count

        await db.execute(
            "UPDATE users SET lives = ? WHERE telegram_id = ?",
            (new_lives, telegram_id)
        )
        await db.commit()
        return True, new_lives

# --- Ad Verification & Anti-Spam ---

async def can_claim_ad_reward(telegram_id: int) -> Tuple[bool, str, int]:
    settings = await get_all_settings()
    cooldown = int(settings.get("ad_cooldown_seconds", "20"))

    async with get_db() as db:
        u_cursor = await db.execute("SELECT lives FROM users WHERE telegram_id = ?", (telegram_id,))
        user = await u_cursor.fetchone()
        if not user:
            return False, "User not found", 0

        cursor = await db.execute(
            "SELECT created_at FROM ad_views WHERE telegram_id = ? ORDER BY id DESC LIMIT 1",
            (telegram_id,)
        )
        last_ad = await cursor.fetchone()
        if last_ad:
            last_time = parse_iso_datetime(last_ad["created_at"])
            now = datetime.datetime.now(datetime.timezone.utc)
            elapsed = int((now - last_time).total_seconds())
            if elapsed < cooldown:
                remaining = cooldown - elapsed
                return False, f"Please wait {remaining}s before claiming another ad", remaining

    return True, "OK", 0

async def record_ad_view(telegram_id: int, network: str) -> bool:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO ad_views (telegram_id, network, reward_claimed) VALUES (?, ?, 1)",
            (telegram_id, network)
        )
        await db.commit()
    return True

# --- Game Sessions & Leaderboards ---

async def record_game_session(telegram_id: int, game_id: str, score: int, result: str = "completed"):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO game_sessions (telegram_id, game_id, score, result) VALUES (?, ?, ?, ?)",
            (telegram_id, game_id, score, result)
        )
        await db.commit()

async def get_leaderboard(game_id: Optional[str] = None, limit: int = 15) -> List[Dict[str, Any]]:
    async with get_db() as db:
        if game_id and game_id != "all":
            query = """
                SELECT u.telegram_id, u.first_name, u.username, MAX(g.score) as high_score, COUNT(g.id) as games_played
                FROM game_sessions g
                JOIN users u ON g.telegram_id = u.telegram_id
                WHERE g.game_id = ?
                GROUP BY g.telegram_id
                ORDER BY high_score DESC
                LIMIT ?
            """
            cursor = await db.execute(query, (game_id, limit))
        else:
            query = """
                SELECT u.telegram_id, u.first_name, u.username, SUM(g.score) as high_score, COUNT(g.id) as games_played
                FROM game_sessions g
                JOIN users u ON g.telegram_id = u.telegram_id
                GROUP BY g.telegram_id
                ORDER BY high_score DESC
                LIMIT ?
            """
            cursor = await db.execute(query, (limit,))

        rows = await cursor.fetchall()
        leaderboard = []
        for i, row in enumerate(rows, 1):
            name = row["first_name"] or (f"@{row['username']}" if row["username"] else f"Player {row['telegram_id']}")
            leaderboard.append({
                "rank": i,
                "telegram_id": row["telegram_id"],
                "name": name,
                "score": row["high_score"],
                "games_played": row["games_played"]
            })
        return leaderboard

async def get_user_high_scores(telegram_id: int) -> Dict[str, int]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT game_id, MAX(score) as high_score FROM game_sessions WHERE telegram_id = ? GROUP BY game_id",
            (telegram_id,)
        )
        rows = await cursor.fetchall()
        return {row["game_id"]: row["high_score"] for row in rows}

# --- Admin Statistics, Broadcast & Backup/Restore ---

async def get_admin_stats() -> Dict[str, Any]:
    async with get_db() as db:
        c1 = await db.execute("SELECT COUNT(*) as count FROM users")
        total_users = (await c1.fetchone())["count"]

        today_iso = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        c2 = await db.execute("SELECT COUNT(*) as count FROM users WHERE last_active_at >= ?", (today_iso,))
        dau = (await c2.fetchone())["count"]

        c3 = await db.execute("SELECT COUNT(*) as count FROM game_sessions")
        total_games = (await c3.fetchone())["count"]

        c4 = await db.execute("SELECT game_id, COUNT(*) as count, MAX(score) as top_score FROM game_sessions GROUP BY game_id")
        game_stats = {row["game_id"]: {"plays": row["count"], "top_score": row["top_score"]} for row in await c4.fetchall()}

        c5 = await db.execute("SELECT network, COUNT(*) as count FROM ad_views GROUP BY network")
        ad_stats = {row["network"]: row["count"] for row in await c5.fetchall()}
        total_ads = sum(ad_stats.values())

        return {
            "total_users": total_users,
            "dau": dau,
            "total_games": total_games,
            "game_stats": game_stats,
            "ad_stats": ad_stats,
            "total_ads": total_ads
        }

async def get_all_user_ids() -> List[int]:
    async with get_db() as db:
        cursor = await db.execute("SELECT telegram_id FROM users")
        rows = await cursor.fetchall()
        return [row["telegram_id"] for row in rows]

# --- Database Backup & Restore Engine ---

async def export_database_bytes() -> bytes:
    """
    Safely reads SQLite database file for Telegram export.
    """
    # Flush SQLite WAL to disk
    async with get_db() as db:
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    if os.path.exists(config.DATABASE_PATH):
        with open(config.DATABASE_PATH, "rb") as f:
            return f.read()
    return b""

async def restore_database_from_bytes(data: bytes) -> Tuple[bool, str]:
    """
    Safely restores database file from uploaded backup bytes.
    """
    if not data or len(data) < 100:
        return False, "File is empty or corrupted."

    # Verify SQLite header
    if not data.startswith(b"SQLite format 3"):
        return False, "Invalid SQLite database file format."

    temp_path = f"{config.DATABASE_PATH}.restore_temp"
    try:
        with open(temp_path, "wb") as f:
            f.write(data)

        # Test integrity
        test_conn = await aiosqlite.connect(temp_path)
        cursor = await test_conn.execute("PRAGMA integrity_check;")
        row = await cursor.fetchone()
        await test_conn.close()

        if not row or row[0] != "ok":
            if os.path.exists(temp_path): os.remove(temp_path)
            return False, f"Integrity check failed: {row[0] if row else 'unknown'}"

        # Replace main database
        if os.path.exists(config.DATABASE_PATH):
            try:
                os.remove(config.DATABASE_PATH)
            except Exception:
                pass

        # Also remove old WAL/SHM
        for ext in ["-wal", "-shm"]:
            wal_file = f"{config.DATABASE_PATH}{ext}"
            if os.path.exists(wal_file):
                try: os.remove(wal_file)
                except Exception: pass

        os.replace(temp_path, config.DATABASE_PATH)
        return True, "Database restored successfully."
    except Exception as e:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except Exception: pass
        return False, str(e)
