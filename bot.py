import asyncio
import logging
import logging.handlers
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, CallbackQuery, ErrorEvent, MenuButtonWebApp, Message, WebAppInfo

from config import BOT_TOKEN, WEBAPP_URL
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

    if WEBAPP_URL:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Расписание", web_app=WebAppInfo(url=WEBAPP_URL)))
            logging.getLogger("bot").info("кнопка меню -> Mini App %s", WEBAPP_URL)
        except Exception:  # noqa: BLE001 - не критично для работы бота
            logging.getLogger("bot").warning(
                "не удалось установить кнопку меню Mini App", exc_info=True)

    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="today", description="Расписание на сегодня"),
            BotCommand(command="tomorrow", description="Расписание на завтра"),
            BotCommand(command="week", description="Вся неделя"),
            BotCommand(command="date", description="На дату: /date DD.MM"),
            BotCommand(command="monday", description="Понедельник"),
            BotCommand(command="tuesday", description="Вторник"),
            BotCommand(command="wednesday", description="Среда"),
            BotCommand(command="thursday", description="Четверг"),
            BotCommand(command="friday", description="Пятница"),
            BotCommand(command="settings", description="Дайджест: вкл/выкл и время"),
            BotCommand(command="webapp", description="Открыть приложение"),
            BotCommand(command="help", description="Помощь"),
        ])
        logging.getLogger("bot").info("меню команд обновлено")
    except Exception:  # noqa: BLE001
        logging.getLogger("bot").warning(
            "не удалось установить меню команд", exc_info=True)

    scheduler = Scheduler(bot, Storage())
    scheduler.start()
    try:
        logging.getLogger("bot").info("Бот запущен")
        await dp.start_polling(bot)
    finally:
        await scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
