from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import config

bot: Bot = None
dp: Dispatcher = Dispatcher(storage=MemoryStorage())

def get_bot() -> Bot:
    global bot
    if bot is None:
        if config.BOT_TOKEN:
            bot = Bot(
                token=config.BOT_TOKEN,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML)
            )
        else:
            # Fallback dummy token for local dev test
            bot = Bot(
                token="1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ123456789",
                default=DefaultBotProperties(parse_mode=ParseMode.HTML)
            )
    return bot
