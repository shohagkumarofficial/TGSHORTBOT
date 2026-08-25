from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from app.services.user_service import UserService


class AuthMiddleware(BaseMiddleware):
    def __init__(self, user_service: UserService):
        super().__init__()
        self.user_service = user_service

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        event_user: User = data.get("event_from_user")
        if event_user:
            # Auto register or update user profile
            user, is_new = await self.user_service.get_or_create_user(
                user_id=event_user.id,
                username=event_user.username,
                first_name=event_user.first_name
            )
            data["current_user"] = user
            data["is_new_user"] = is_new

        data["user_service"] = self.user_service
        return await handler(event, data)
