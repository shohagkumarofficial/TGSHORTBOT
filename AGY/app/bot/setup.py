import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.storage.base import BaseStorage
from app.services.user_service import UserService
from app.services.task_service import TaskService
from app.bot.middlewares.auth import AuthMiddleware
from app.bot.handlers import start, tasks, profile, admin

logger = logging.getLogger(__name__)


def create_bot_and_dispatcher(storage: BaseStorage):
    """Creates and configures Bot and Dispatcher instances."""
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    fsm_storage = MemoryStorage()
    dp = Dispatcher(storage=fsm_storage)

    user_service = UserService(storage)
    task_service = TaskService(storage)

    # Register Middlewares
    auth_middleware = AuthMiddleware(user_service)
    dp.message.outer_middleware(auth_middleware)
    dp.callback_query.outer_middleware(auth_middleware)

    # Dependency Injection into handlers
    dp["user_service"] = user_service
    dp["task_service"] = task_service
    dp["storage"] = storage

    # Register Handlers / Routers
    dp.include_router(start.router)
    dp.include_router(profile.router)
    dp.include_router(tasks.router)
    dp.include_router(admin.router)

    return bot, dp, user_service, task_service
