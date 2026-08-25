from datetime import datetime, timezone
import uuid
from typing import Dict, Any, List, Optional, Tuple
from app.storage.base import BaseStorage


class TaskService:
    def __init__(self, storage: BaseStorage):
        self.storage = storage

    async def init_default_tasks_if_empty(self) -> None:
        """Seed default tasks if storage has no tasks."""
        all_tasks = await self.storage.get_all_tasks()
        if not all_tasks:
            default_tasks = [
                {
                    "task_id": "task_tg_official",
                    "title": "📢 Join Official Channel",
                    "description": "আমাদের অফিসিয়াল টেলিগ্রাম চ্যানেলে জয়েন করুন এবং আপডেট থাকুন।",
                    "task_type": "channel_join",
                    "target_url": "https://t.me/telegram",
                    "channel_username": "@telegram",
                    "reward": 100,
                    "is_active": True,
                    "created_at": datetime.now(timezone.utc).isoformat()
                },
                {
                    "task_id": "task_shortlink_1",
                    "title": "🔗 Visit TGSHORT Partner Link",
                    "description": "স্পন্সর লিংকটি ভিজিট করুন এবং ভেরিফাই করে রিওয়ার্ড নিন।",
                    "task_type": "link_visit",
                    "target_url": "https://example.com/short/tg123",
                    "verification_code": "TG777",
                    "reward": 75,
                    "is_active": True,
                    "created_at": datetime.now(timezone.utc).isoformat()
                },
                {
                    "task_id": "task_survey_welcome",
                    "title": "📝 Quick Feedback Task",
                    "description": "আমাদের সার্ভিস সম্পর্কে আপনার মতামত দিন।",
                    "task_type": "custom",
                    "target_url": "https://forms.gle/sample",
                    "verification_code": "DONE",
                    "reward": 50,
                    "is_active": True,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
            ]
            for t in default_tasks:
                await self.storage.save_task(t["task_id"], t)

    async def get_user_task_list(self, user_id: int) -> List[Dict[str, Any]]:
        """Returns all active tasks along with completion status for the specified user."""
        user = await self.storage.get_user(user_id)
        completed_task_ids = set(user.get("completed_tasks", [])) if user else set()
        
        all_tasks = await self.storage.get_all_tasks()
        result = []
        for task_id, task in all_tasks.items():
            if not task.get("is_active", True):
                continue
            item = dict(task)
            item["is_completed"] = task_id in completed_task_ids
            result.append(item)
        return result

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return await self.storage.get_task(task_id)

    async def create_task(
        self,
        title: str,
        description: str,
        task_type: str,
        reward: int,
        target_url: str,
        channel_username: Optional[str] = None,
        verification_code: Optional[str] = None
    ) -> Dict[str, Any]:
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        task_data = {
            "task_id": task_id,
            "title": title,
            "description": description,
            "task_type": task_type,
            "reward": reward,
            "target_url": target_url,
            "channel_username": channel_username,
            "verification_code": verification_code,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await self.storage.save_task(task_id, task_data)
        return task_data

    async def delete_task(self, task_id: str) -> bool:
        return await self.storage.delete_task(task_id)

    async def complete_task(self, user_id: int, task_id: str) -> Tuple[bool, str, int]:
        """
        Completes a task for user and awards coins.
        """
        user = await self.storage.get_user(user_id)
        if not user:
            return False, "User not found.", 0

        task = await self.storage.get_task(task_id)
        if not task:
            return False, "টাস্কটি খুঁজে পাওয়া যায়নি বা মুছে ফেলা হয়েছে।", 0

        completed_tasks = user.get("completed_tasks", [])
        if task_id in completed_tasks:
            return False, "⚠️ আপনি ইতিমধ্যে এই টাস্কটি সম্পন্ন করে রিওয়ার্ড নিয়েছেন!", 0

        reward = task.get("reward", 0)
        completed_tasks.append(task_id)
        user["completed_tasks"] = completed_tasks
        user["balance"] = user.get("balance", 0) + reward
        user["total_earned"] = user.get("total_earned", 0) + reward

        await self.storage.save_user(user_id, user)
        return True, f"🎉 দারুণ! টাস্কটি সম্পন্ন হয়েছে। আপনি <b>+{reward} কয়েন</b> পেয়েছেন!", reward
