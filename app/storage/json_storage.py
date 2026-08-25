import asyncio
import json
import os
import logging
from typing import Dict, Any, Optional

from app.storage.base import BaseStorage

logger = logging.getLogger(__name__)


class JSONStorage(BaseStorage):
    """File-backed JSON storage with in-memory caching and async locking."""

    def __init__(self, file_path: str = "data.json"):
        self.file_path = file_path
        self._lock = asyncio.Lock()
        self._data: Dict[str, Any] = {
            "users": {},
            "tasks": {},
            "transactions": []
        }
        self._initialized = False

    def _sync_read(self) -> Dict[str, Any]:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, mode="r", encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():
                        return json.loads(content)
            except Exception as e:
                logger.error(f"Error reading {self.file_path}: {e}")
        return {"users": {}, "tasks": {}, "transactions": []}

    def _sync_write(self, data: Dict[str, Any]) -> None:
        try:
            temp_file = f"{self.file_path}.tmp"
            with open(temp_file, mode="w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2, ensure_ascii=False))
            
            if os.path.exists(self.file_path):
                os.replace(temp_file, self.file_path)
            else:
                os.rename(temp_file, self.file_path)
        except Exception as e:
            logger.error(f"Failed to persist storage to {self.file_path}: {e}")

    async def init(self) -> None:
        """Initialize storage by loading existing data or creating fresh structure."""
        if self._initialized:
            return

        async with self._lock:
            loop = asyncio.get_running_loop()
            loaded = await loop.run_in_executor(None, self._sync_read)
            self._data = loaded
            
            # Ensure keys exist
            self._data.setdefault("users", {})
            self._data.setdefault("tasks", {})
            self._data.setdefault("transactions", [])
            
            await loop.run_in_executor(None, self._sync_write, self._data)
            self._initialized = True

    async def _save_to_file_locked(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_write, self._data)

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        if not self._initialized:
            await self.init()
        return self._data["users"].get(str(user_id))

    async def save_user(self, user_id: int, user_data: Dict[str, Any]) -> None:
        if not self._initialized:
            await self.init()
        async with self._lock:
            self._data["users"][str(user_id)] = user_data
            await self._save_to_file_locked()

    async def get_all_users(self) -> Dict[str, Dict[str, Any]]:
        if not self._initialized:
            await self.init()
        return self._data["users"]

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        if not self._initialized:
            await self.init()
        return self._data["tasks"].get(str(task_id))

    async def get_all_tasks(self) -> Dict[str, Dict[str, Any]]:
        if not self._initialized:
            await self.init()
        return self._data["tasks"]

    async def save_task(self, task_id: str, task_data: Dict[str, Any]) -> None:
        if not self._initialized:
            await self.init()
        async with self._lock:
            self._data["tasks"][str(task_id)] = task_data
            await self._save_to_file_locked()

    async def delete_task(self, task_id: str) -> bool:
        if not self._initialized:
            await self.init()
        async with self._lock:
            if str(task_id) in self._data["tasks"]:
                del self._data["tasks"][str(task_id)]
                await self._save_to_file_locked()
                return True
            return False

    async def add_transaction(self, tx_data: Dict[str, Any]) -> None:
        if not self._initialized:
            await self.init()
        async with self._lock:
            self._data["transactions"].append(tx_data)
            await self._save_to_file_locked()
