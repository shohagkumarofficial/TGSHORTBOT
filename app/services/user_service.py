from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple, List
from app.storage.base import BaseStorage
from app.config import settings


class UserService:
    def __init__(self, storage: BaseStorage):
        self.storage = storage

    async def get_or_create_user(
        self,
        user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        referrer_id: Optional[int] = None
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Retrieves user or creates a new user account.
        Returns (user_dict, is_new_user).
        """
        existing = await self.storage.get_user(user_id)
        if existing:
            # Update latest username or first_name if changed
            changed = False
            if username and existing.get("username") != username:
                existing["username"] = username
                changed = True
            if first_name and existing.get("first_name") != first_name:
                existing["first_name"] = first_name
                changed = True
            if changed:
                await self.storage.save_user(user_id, existing)
            return existing, False

        # Create new user
        now_iso = datetime.now(timezone.utc).isoformat()
        new_user = {
            "user_id": user_id,
            "username": username or "",
            "first_name": first_name or "User",
            "balance": 0,
            "total_earned": 0,
            "referred_by": None,
            "referrals_count": 0,
            "last_daily_bonus": None,
            "completed_tasks": [],
            "joined_at": now_iso
        }

        # Check referral
        if referrer_id and referrer_id != user_id:
            referrer = await self.storage.get_user(referrer_id)
            if referrer:
                new_user["referred_by"] = referrer_id
                # Bonus for referee
                new_user["balance"] += settings.REFEREE_BONUS_COINS
                new_user["total_earned"] += settings.REFEREE_BONUS_COINS

                # Bonus for referrer
                referrer["balance"] = referrer.get("balance", 0) + settings.REFERRAL_BONUS_COINS
                referrer["total_earned"] = referrer.get("total_earned", 0) + settings.REFERRAL_BONUS_COINS
                referrer["referrals_count"] = referrer.get("referrals_count", 0) + 1
                await self.storage.save_user(referrer_id, referrer)

        await self.storage.save_user(user_id, new_user)
        return new_user, True

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        return await self.storage.get_user(user_id)

    async def add_coins(self, user_id: int, amount: int, reason: str = "Reward") -> Optional[Dict[str, Any]]:
        user = await self.storage.get_user(user_id)
        if not user:
            return None
        
        user["balance"] = user.get("balance", 0) + amount
        user["total_earned"] = user.get("total_earned", 0) + amount
        await self.storage.save_user(user_id, user)
        return user

    async def claim_daily_bonus(self, user_id: int) -> Tuple[bool, str, int]:
        """
        Claims daily bonus if 24 hours have passed since last claim.
        Returns (success, message, coins_awarded).
        """
        user = await self.storage.get_user(user_id)
        if not user:
            return False, "ব্যবহারকারী খুঁজে পাওয়া যায়নি।", 0

        last_claim_str = user.get("last_daily_bonus")
        now = datetime.now(timezone.utc)

        if last_claim_str:
            last_claim = datetime.fromisoformat(last_claim_str)
            time_diff = now - last_claim
            if time_diff < timedelta(hours=24):
                remaining = timedelta(hours=24) - time_diff
                hours, rem = divmod(int(remaining.total_seconds()), 3600)
                minutes, _ = divmod(rem, 60)
                return False, f"⏳ আপনি ইতিমধ্যে আজকের ডেইলি বোনাস নিয়েছেন!\nআবার ক্লেইম করতে পারবেন: {hours} ঘণ্টা {minutes} মিনিট পর।", 0

        # Award daily bonus
        coins = settings.DAILY_BONUS_COINS
        user["balance"] = user.get("balance", 0) + coins
        user["total_earned"] = user.get("total_earned", 0) + coins
        user["last_daily_bonus"] = now.isoformat()
        await self.storage.save_user(user_id, user)

        return True, f"🎉 অভিনন্দন! আপনি <b>+{coins} কয়েন</b> ডেইলি বোনাস পেয়েছেন!", coins

    async def get_stats(self) -> Dict[str, Any]:
        all_users = await self.storage.get_all_users()
        total_users = len(all_users)
        total_coins_distributed = sum(u.get("total_earned", 0) for u in all_users.values())
        return {
            "total_users": total_users,
            "total_coins_distributed": total_coins_distributed
        }

    async def get_top_users(self, limit: int = 10) -> List[Dict[str, Any]]:
        all_users = await self.storage.get_all_users()
        sorted_users = sorted(
            all_users.values(),
            key=lambda x: x.get("balance", 0),
            reverse=True
        )
        return sorted_users[:limit]
