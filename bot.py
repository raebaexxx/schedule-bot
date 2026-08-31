import asyncio
import logging
import logging.handlers
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, ErrorEvent, Message

from config import BOT_TOKEN
from handlers import router
from scheduler import Scheduler
from storage import Storage

LOG_FILE = Path(__file__).parent / "bot.log"


def setup_logging() -> None:
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s")
    rotating = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    rotating.setFormatter(fmt)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(rotating)
    root.addHandler(stream)


async def on_error(event: ErrorEvent) -> None:
    logging.getLogger("bot").exception(
        "Необработанная ошибка при обработке апдейта",
        exc_info=event.exception)
    update = event.update
    if update.message:
        target: Message | CallbackQuery = update.message
    elif update.callback_query:
        target = update.callback_query
    else:
        target = None
    try:
        if isinstance(target, CallbackQuery):
            await target.answer("Произошла ошибка, попробуйте ещё раз")
        elif isinstance(target, Message):
            await target.answer("Произошла ошибка, попробуйте ещё раз")
    except Exception:  # noqa: BLE001 - fallback-ответ не должен падать
        logging.getLogger("bot").warning("не удалось отправить сообщение об ошибке")


async def main() -> None:
    setup_logging()
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN не задан. Создай файл .env со строкой BOT_TOKEN=...")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    dp.errors.register(on_error)

    scheduler = Scheduler(bot, Storage())
    scheduler.start()
    try:
        logging.getLogger("bot").info("Бот запущен")
        await dp.start_polling(bot)
    finally:
        await scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
