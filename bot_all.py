"""Общий бот расписания ЕТИ: все курсы и группы (отдельный токен)."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN_ALL, WEBAPP_URL
from handlers_all import router
from handlers_admin import router as admin_router
from notify import notify_changes
from scheduler import DigestScheduler
from storage import SelectionStorage

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
    dp.include_router(admin_router)

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

    try:
        from aiogram.types import BotCommand
        await bot.set_my_commands([
            BotCommand(command="start", description="Главное меню / выбор группы"),
            BotCommand(command="today", description="Расписание на сегодня"),
            BotCommand(command="tomorrow", description="Расписание на завтра"),
            BotCommand(command="week", description="Вся неделя"),
            BotCommand(command="date", description="На дату: /date DD.MM"),
            BotCommand(command="monday", description="Понедельник"),
            BotCommand(command="tuesday", description="Вторник"),
            BotCommand(command="wednesday", description="Среда"),
            BotCommand(command="thursday", description="Четверг"),
            BotCommand(command="friday", description="Пятница"),
            BotCommand(command="saturday", description="Суббота"),
            BotCommand(command="groups", description="Сменить группу"),
            BotCommand(command="find", description="Поиск: /find запрос"),
            BotCommand(command="webapp", description="Открыть приложение"),
            BotCommand(command="help", description="Помощь"),
        ])
        logging.getLogger("bot_all").info("меню команд обновлено")
    except Exception:  # noqa: BLE001
        logging.getLogger("bot_all").warning(
            "не удалось установить меню команд", exc_info=True)

    from handlers_admin import storage

    logging.getLogger("bot_all").info("Общий бот запущен")

    # при старте: разослать накопившиеся уведомления об изменениях расписания
    try:
        sent = await notify_changes(bot, storage)
        if sent:
            logging.getLogger("bot_all").info("доставлено уведомлений: %s", sent)
    except Exception:  # noqa: BLE001
        logging.getLogger("bot_all").warning(
            "ошибка рассылки изменений", exc_info=True)

    digest = DigestScheduler(bot, storage)
    digest.start()
    try:
        await dp.start_polling(bot)
    finally:
        await digest.stop()


if __name__ == "__main__":
    asyncio.run(main())
