"""Общий бот расписания ЕТИ: все курсы и группы (отдельный токен)."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN_ALL, WEBAPP_URL
from handlers_all import router

LOG_FILE = __import__("pathlib").Path(__file__).parent / "bot_all.log"


def setup_logging() -> None:
    import logging.handlers
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    rotating = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    rotating.setFormatter(fmt)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(rotating)
    root.addHandler(stream)


async def main() -> None:
    setup_logging()
    if not BOT_TOKEN_ALL:
        print("ERROR: BOT_TOKEN_ALL не задан в .env")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN_ALL, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    if WEBAPP_URL:
        try:
            from aiogram.types import MenuButtonWebApp, WebAppInfo
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Расписание", web_app=WebAppInfo(url=WEBAPP_URL)))
            logging.getLogger("bot_all").info("кнопка меню -> Mini App %s", WEBAPP_URL)
        except Exception:  # noqa: BLE001
            logging.getLogger("bot_all").warning(
                "не удалось установить кнопку меню Mini App", exc_info=True)

    logging.getLogger("bot_all").info("Общий бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
