"""Хэндлеры Telegram-бота с расписанием группы БА-231."""

from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from formatter import (
    BOT_DAYS,
    format_day_by_date,
    format_week,
    monday_of,
    now,
    split_message,
)
from schedule_data import DAY_NAMES_RU

router = Router()

MENU_TEXT = (
    "<b>Расписание группы БА-231</b>\n"
    "7 семестр, 2026/2027\n\n"
    "Выбери, что посмотреть:"
)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сегодня", callback_data="today"),
         InlineKeyboardButton(text="Завтра", callback_data="tomorrow")],
        [InlineKeyboardButton(text="По дням недели", callback_data="days_menu"),
         InlineKeyboardButton(text="Вся неделя", callback_data="week")],
    ])


def days_menu_keyboard() -> InlineKeyboardMarkup:
    short = {"monday": "Пн", "tuesday": "Вт", "wednesday": "Ср",
             "thursday": "Чт", "friday": "Пт"}
    buttons, row = [], []
    for i, day_key in enumerate(BOT_DAYS):
        row.append(InlineKeyboardButton(
            text=short[day_key], callback_data=f"day:{i}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_day(target: Message, d: date, title: str | None = None) -> None:
    text = format_day_by_date(d, title)
    for chunk in split_message(text):
        await target.answer(chunk, reply_markup=main_menu_keyboard())


async def send_week(target: Message) -> None:
    text = format_week()
    for chunk in split_message(text):
        await target.answer(chunk, reply_markup=main_menu_keyboard())


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(MENU_TEXT, reply_markup=main_menu_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/start — главное меню\n"
        "/today — расписание на сегодня\n"
        "/tomorrow — расписание на завтра\n"
        "/week — вся неделя\n"
        "/date DD.MM — расписание на дату (например /date 15.09)\n"
        "/monday ... /friday — по дням недели",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    await send_day(message, now().date())


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message) -> None:
    await send_day(message, now().date() + timedelta(days=1))


@router.message(Command("week"))
async def cmd_week(message: Message) -> None:
    await send_week(message)


@router.message(Command("date"))
async def cmd_date(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Формат: /date DD.MM (например /date 15.09)")
        return
    try:
        day, month = (int(x) for x in parts[1].split(".")[:2])
        year = 2026 if month >= 7 else 2027  # 2026/2027 учебный год
        d = date(year, month, day)
    except ValueError:
        await message.answer("Не понял дату. Формат: /date DD.MM")
        return
    await send_day(message, d, title=f"Расписание на {d.strftime('%d.%m.%Y')}")


DAY_COMMANDS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4}


@router.message(Command(*DAY_COMMANDS))
async def cmd_day(message: Message) -> None:
    cmd = (message.text or "").lstrip("/").split()[0].lower()
    offset = DAY_COMMANDS.get(cmd)
    if offset is None:
        return
    d = monday_of(now().date()) + timedelta(days=offset)
    await send_day(message, d)


@router.callback_query(F.data == "today")
async def cb_today(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        format_day_by_date(now().date()), reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "tomorrow")
async def cb_tomorrow(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        format_day_by_date(now().date() + timedelta(days=1)),
        reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "week")
async def cb_week(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        format_week(), reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "days_menu")
async def cb_days_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Выбери день недели:", reply_markup=days_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("day:"))
async def cb_day(callback: CallbackQuery) -> None:
    try:
        offset = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    if not (0 <= offset < len(BOT_DAYS)):
        await callback.answer()
        return
    d = monday_of(now().date()) + timedelta(days=offset)
    await callback.message.edit_text(
        format_day_by_date(d), reply_markup=days_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "back_to_main")
async def cb_back(callback: CallbackQuery) -> None:
    await callback.message.edit_text(MENU_TEXT, reply_markup=main_menu_keyboard())
    await callback.answer()
