from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseStorage(ABC):
    """Abstract interface for application storage."""

    @abstractmethod
    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def save_user(self, user_id: int, user_data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def get_all_users(self) -> Dict[str, Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_all_tasks(self) -> Dict[str, Dict[str, Any]]:
        pass

    @abstractmethod
    async def save_task(self, task_id: str, task_data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def delete_task(self, task_id: str) -> bool:
        pass
