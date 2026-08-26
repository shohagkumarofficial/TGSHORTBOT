import asyncio
import os
import time
import unittest
from fastapi.testclient import TestClient

db_filename = f"test_game_bot_{int(time.time())}.db"
os.environ["DATABASE_PATH"] = db_filename
os.environ["BOT_TOKEN"] = "1234567890:TEST_TOKEN_XYZ"
os.environ["OWNER_TELEGRAM_ID"] = "5991854507"

import config
config.DATABASE_PATH = db_filename
config.BOT_TOKEN = "1234567890:TEST_TOKEN_XYZ"
config.OWNER_TELEGRAM_ID = 5991854507

import database
from app import app

class TestGameBotEnhanced(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        asyncio.run(database.init_db())
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists(db_filename):
                os.remove(db_filename)
        except Exception:
            pass

    def test_01_database_settings_and_multi_ads(self):
        async def run():
            settings = await database.get_all_settings()
            self.assertIn("default_lives", settings)
            self.assertEqual(settings["default_lives"], "3")
            self.assertEqual(settings["max_free_lives"], "3")
            self.assertEqual(settings["adsgram_enabled"], "1")
            self.assertEqual(settings["monetag_enabled"], "1")

            # Toggle Gigapub and Adsterra
            await database.set_setting("gigapub_enabled", "1")
            await database.set_setting("adsterra_enabled", "1")
            s2 = await database.get_all_settings()
            self.assertEqual(s2["gigapub_enabled"], "1")
            self.assertEqual(s2["adsterra_enabled"], "1")
        asyncio.run(run())

    def test_02_unlimited_stacked_lives(self):
        async def run():
            user = await database.get_or_create_user(5001, "Shohag", "", "shohag_tg")
            self.assertEqual(user["lives"], 3)
            self.assertEqual(user["max_free_lives"], 3)

            # Watching 3 rewarded ads should stack lives to 6 (beyond 3!)
            await database.add_life(5001, 1)
            await database.add_life(5001, 1)
            await database.add_life(5001, 1)

            u2 = await database.get_or_create_user(5001)
            self.assertEqual(u2["lives"], 6)
            self.assertEqual(u2["seconds_until_regen"], 0) # No auto-regen when boosted above free cap

            # Deduct life
            success, remaining = await database.deduct_life(5001)
            self.assertTrue(success)
            self.assertEqual(remaining, 5)
        asyncio.run(run())

    def test_03_database_backup_and_restore(self):
        async def run():
            # Export raw SQLite bytes
            raw_bytes = await database.export_database_bytes()
            self.assertTrue(len(raw_bytes) > 0)
            self.assertTrue(raw_bytes.startswith(b"SQLite format 3"))

            # Test Restore
            success, msg = await database.restore_database_from_bytes(raw_bytes)
            self.assertTrue(success, msg)

            # Test invalid payload rejection
            bad_success, _ = await database.restore_database_from_bytes(b"invalid data")
            self.assertFalse(bad_success)
        asyncio.run(run())

    def test_04_9_games_api_and_static_serving(self):
        # Check all 9 games in user info
        res = self.client.get("/api/user/info?dev_user_id=5001")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["games"]), 9)

        game_ids = [g["id"] for g in data["games"]]
        expected = ["snake", "2048", "flappy", "tictactoe", "memory", "whack", "space", "racer", "breakout"]
        for g_id in expected:
            self.assertIn(g_id, game_ids)

        # Check static serving for newly added games
        res_space = self.client.get("/static/games/space/index.html")
        self.assertEqual(res_space.status_code, 200)

        res_racer = self.client.get("/static/games/racer/index.html")
        self.assertEqual(res_racer.status_code, 200)

        res_breakout = self.client.get("/static/games/breakout/index.html")
        self.assertEqual(res_breakout.status_code, 200)

if __name__ == "__main__":
    unittest.main()
