import asyncio
import os
import time
import unittest
from fastapi.testclient import TestClient

db_filename = f"test_game_bot_{int(time.time())}.db"
os.environ["DATABASE_PATH"] = db_filename
os.environ["BOT_TOKEN"] = "1234567890:TEST_TOKEN_XYZ"
os.environ["OWNER_TELEGRAM_ID"] = "987654321"

import config
config.DATABASE_PATH = db_filename
config.BOT_TOKEN = "1234567890:TEST_TOKEN_XYZ"
config.OWNER_TELEGRAM_ID = 987654321

import database
from app import app

class TestGameBot(unittest.TestCase):
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

    def test_01_database_settings(self):
        async def run():
            settings = await database.get_all_settings()
            self.assertIn("default_lives", settings)
            self.assertEqual(settings["default_lives"], "3")
            self.assertEqual(settings["max_lives"], "3")
            self.assertEqual(settings["life_deduct_mode"], "on_loss")

            await database.set_setting("test_key", "test_val")
            val = await database.get_setting("test_key")
            self.assertEqual(val, "test_val")
        asyncio.run(run())

    def test_02_user_and_life_engine(self):
        async def run():
            user = await database.get_or_create_user(1001, "Alice", "Wonder", "alice_w")
            self.assertEqual(user["telegram_id"], 1001)
            self.assertEqual(user["lives"], 3)
            self.assertEqual(user["max_lives"], 3)

            # Deduct life
            success, remaining = await database.deduct_life(1001)
            self.assertTrue(success)
            self.assertEqual(remaining, 2)

            # Deduct again
            success, remaining = await database.deduct_life(1001)
            self.assertTrue(success)
            self.assertEqual(remaining, 1)

            # Add life back
            success, new_lives = await database.add_life(1001, 1)
            self.assertTrue(success)
            self.assertEqual(new_lives, 2)
        asyncio.run(run())

    def test_03_ad_view_and_cooldown(self):
        async def run():
            user = await database.get_or_create_user(1002, "Bob", "", "bob_tg")
            # User has 3 lives (max), cannot claim
            can_claim, reason, _ = await database.can_claim_ad_reward(1002)
            self.assertFalse(can_claim)

            # Deduct life so Bob has 2 lives
            await database.deduct_life(1002)
            can_claim, reason, _ = await database.can_claim_ad_reward(1002)
            self.assertTrue(can_claim)

            # Record ad view
            await database.record_ad_view(1002, "adsgram")
            await database.add_life(1002, 1)

            # Deduct life again, but immediate cooldown is active
            await database.deduct_life(1002)
            can_claim, reason, remaining_cooldown = await database.can_claim_ad_reward(1002)
            self.assertFalse(can_claim)
            self.assertGreater(remaining_cooldown, 0)
        asyncio.run(run())

    def test_04_game_session_and_leaderboard(self):
        async def run():
            await database.record_game_session(1001, "snake", 150, "completed")
            await database.record_game_session(1002, "snake", 280, "completed")
            lb = await database.get_leaderboard("snake")
            self.assertGreaterEqual(len(lb), 2)
            self.assertEqual(lb[0]["telegram_id"], 1002)
            self.assertEqual(lb[0]["score"], 280)
        asyncio.run(run())

    def test_05_admin_stats(self):
        async def run():
            stats = await database.get_admin_stats()
            self.assertGreaterEqual(stats["total_users"], 2)
            self.assertIn("total_games", stats)
            self.assertIn("total_ads", stats)
        asyncio.run(run())

    def test_06_fastapi_endpoints(self):
        # Health check
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

        # Static Home
        res_home = self.client.get("/")
        self.assertEqual(res_home.status_code, 200)
        self.assertIn("Telegram Arcade Game Hub", res_home.text)

        # User info endpoint with dev_user_id query param
        res_user = self.client.get("/api/user/info?dev_user_id=2001")
        self.assertEqual(res_user.status_code, 200)
        data = res_user.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["user"]["telegram_id"], 2001)
        self.assertEqual(len(data["games"]), 6)

        # Game Start
        res_start = self.client.post("/api/game/start?dev_user_id=2001", json={"game_id": "snake"})
        self.assertEqual(res_start.status_code, 200)
        self.assertTrue(res_start.json()["success"])

        # Game End
        res_end = self.client.post("/api/game/end?dev_user_id=2001", json={
            "game_id": "snake",
            "score": 120,
            "result": "lost"
        })
        self.assertEqual(res_end.status_code, 200)
        self.assertTrue(res_end.json()["success"])

        # Leaderboard
        res_lb = self.client.get("/api/leaderboard?game_id=snake")
        self.assertEqual(res_lb.status_code, 200)
        self.assertTrue(res_lb.json()["success"])

if __name__ == "__main__":
    unittest.main()
