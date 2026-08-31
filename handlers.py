"""Хэндлеры Telegram-бота с расписанием группы БА-231."""

import re
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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
from storage import Storage

router = Router()
storage = Storage()

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
PRESET_TIMES = ["06:30", "07:00", "07:30", "08:00"]

MENU_TEXT = (
    "<b>Расписание группы БА-231</b>\n"
    "7 семестр, 2026/2027\n\n"
    "Выбери, что посмотреть:\n"
    "утренний дайджест и его время — <b>/settings</b>"
)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сегодня", callback_data="today"),
         InlineKeyboardButton(text="Завтра", callback_data="tomorrow")],
        [InlineKeyboardButton(text="По дням недели", callback_data="days_menu"),
         InlineKeyboardButton(text="Вся неделя", callback_data="week")],
    ])


def day_keyboard(d: date) -> InlineKeyboardMarkup:
    iso = d.isoformat()
    prev_iso = (d - timedelta(days=1)).isoformat()
    next_iso = (d + timedelta(days=1)).isoformat()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="‹", callback_data=f"daynav:{prev_iso}"),
         InlineKeyboardButton(text="Сегодня", callback_data="today"),
         InlineKeyboardButton(text="›", callback_data=f"daynav:{next_iso}")],
        [InlineKeyboardButton(text="По дням недели", callback_data="days_menu"),
         InlineKeyboardButton(text="Вся неделя", callback_data="week")],
        [InlineKeyboardButton(text="Меню", callback_data="back_to_main")],
    ])


def week_keyboard(monday: date) -> InlineKeyboardMarkup:
    prev_iso = (monday - timedelta(days=7)).isoformat()
    next_iso = (monday + timedelta(days=7)).isoformat()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="‹", callback_data=f"weeknav:{prev_iso}"),
         InlineKeyboardButton(text="Эта неделя", callback_data="week"),
         InlineKeyboardButton(text="›", callback_data=f"weeknav:{next_iso}")],
        [InlineKeyboardButton(text="Сегодня", callback_data="today"),
         InlineKeyboardButton(text="Меню", callback_data="back_to_main")],
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


async def safe_edit(callback: CallbackQuery, text: str,
                    keyboard: InlineKeyboardMarkup) -> None:
    """edit_text без падения на «message is not modified»."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def send_day(target: Message, d: date, title: str | None = None) -> None:
    text = format_day_by_date(d, title)
    for chunk in split_message(text):
        await target.answer(chunk, reply_markup=day_keyboard(d))


async def send_week(target: Message, start: date | None = None) -> None:
    start = start or monday_of(now().date())
    text = format_week(start)
    for chunk in split_message(text):
        await target.answer(chunk, reply_markup=week_keyboard(start))


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    # подписка на дайджест создаётся по умолчанию (07:00 МСК), отключается в /settings
    user = storage.get_or_create(message.chat.id)
    if not user.get("enabled", False):
        storage.set_enabled(message.chat.id, True)
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
        "/monday ... /friday — по дням недели\n"
        "/settings — дайджест: вкл/выкл и время\n\n"
        "Под сообщением дня: ‹ › — листать дни, под неделей — недели.",
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
    await safe_edit(callback, format_day_by_date(now().date()),
                    day_keyboard(now().date()))
    await callback.answer()


@router.callback_query(F.data == "tomorrow")
async def cb_tomorrow(callback: CallbackQuery) -> None:
    d = now().date() + timedelta(days=1)
    await safe_edit(callback, format_day_by_date(d), day_keyboard(d))
    await callback.answer()


@router.callback_query(F.data == "week")
async def cb_week(callback: CallbackQuery) -> None:
    monday = monday_of(now().date())
    await safe_edit(callback, format_week(monday), week_keyboard(monday))
    await callback.answer()


@router.callback_query(F.data == "days_menu")
async def cb_days_menu(callback: CallbackQuery) -> None:
    await safe_edit(callback, "Выбери день недели:", days_menu_keyboard())
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
    await safe_edit(callback, format_day_by_date(d), day_keyboard(d))
    await callback.answer()


@router.callback_query(F.data.startswith("daynav:"))
async def cb_daynav(callback: CallbackQuery) -> None:
    try:
        d = date.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    await safe_edit(callback, format_day_by_date(d), day_keyboard(d))
    await callback.answer()


@router.callback_query(F.data.startswith("weeknav:"))
async def cb_weeknav(callback: CallbackQuery) -> None:
    try:
        monday = date.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    await safe_edit(callback, format_week(monday), week_keyboard(monday))
    await callback.answer()


@router.callback_query(F.data == "back_to_main")
async def cb_back(callback: CallbackQuery) -> None:
    await safe_edit(callback, MENU_TEXT, main_menu_keyboard())
    await callback.answer()


# ------------------------------------------------ настройки дайджеста

class SettingsStates(StatesGroup):
    waiting_time = State()


def settings_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    if enabled:
        toggle = InlineKeyboardButton(text="Выключить дайджест",
                                      callback_data="notify:off")
    else:
        toggle = InlineKeyboardButton(text="Включить дайджест",
                                      callback_data="notify:on")
    rows = [[toggle]]
    rows.append([InlineKeyboardButton(text=t, callback_data=f"time:{t}")
                 for t in PRESET_TIMES[:2]])
    rows.append([InlineKeyboardButton(text=t, callback_data=f"time:{t}")
                 for t in PRESET_TIMES[2:]])
    rows.append([InlineKeyboardButton(text="Своё время…", callback_data="time:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_text(user: dict) -> str:
    state = "включён" if user.get("enabled") else "выключен"
    if user.get("enabled"):
        return (f"<b>Настройки</b>\n\n"
                f"Утренний дайджест: <b>{state}</b>\n"
                f"Время: <b>{user.get('time', '07:00')} МСК</b>\n\n"
                "Каждое утро бот пришлёт расписание на день. "
                "Если пар нет — не пишет.")
    return ("<b>Настройки</b>\n\n"
            f"Утренний дайджест: <b>{state}</b>\n\n"
            "Включите, чтобы получать расписание на день каждое утро.")


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    user = storage.get_or_create(message.chat.id)
    await message.answer(settings_text(user),
                         reply_markup=settings_keyboard(user.get("enabled", False)))


@router.callback_query(F.data == "settings")
async def cb_settings(callback: CallbackQuery) -> None:
    user = storage.get_or_create(callback.message.chat.id)
    await safe_edit(callback, settings_text(user),
                    settings_keyboard(user.get("enabled", False)))
    await callback.answer()


@router.callback_query(F.data == "notify:on")
async def cb_notify_on(callback: CallbackQuery) -> None:
    user = storage.set_enabled(callback.message.chat.id, True)
    await safe_edit(callback, settings_text(user), settings_keyboard(True))
    await callback.answer("Включено")


@router.callback_query(F.data == "notify:off")
async def cb_notify_off(callback: CallbackQuery) -> None:
    user = storage.set_enabled(callback.message.chat.id, False)
    await safe_edit(callback, settings_text(user), settings_keyboard(False))
    await callback.answer("Выключено")


@router.callback_query(F.data.startswith("time:"))
async def cb_time(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    chat_id = callback.message.chat.id
    if value == "custom":
        await state.set_state(SettingsStates.waiting_time)
        await callback.message.answer(
            "Введите время в формате ЧЧ:ММ (МСК), например <code>07:15</code>")
        await callback.answer()
        return
    if not TIME_RE.match(value):
        await callback.answer("Некорректное время")
        return
    user = storage.set_time(chat_id, value)
    await state.clear()
    await safe_edit(callback, settings_text(user), settings_keyboard(True))
    await callback.answer(f"Время: {value} МСК")


@router.message(SettingsStates.waiting_time)
async def msg_custom_time(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not TIME_RE.match(text):
        await message.answer(
            "Не понял. Время в формате ЧЧ:ММ, например <code>07:15</code> "
            "(часы 00–23, минуты 00–59)")
        return
    hh, mm = text.split(":")
    normalized = f"{int(hh):02d}:{mm}"
    user = storage.set_time(message.chat.id, normalized)
    await state.clear()
    await message.answer(f"Готово! Дайджест будет приходить в {user['time']} МСК",
                         reply_markup=settings_keyboard(user.get("enabled", False)))
