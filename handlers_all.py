"""Хэндлеры общего бота расписания ЕТИ (все курсы и группы)."""

import re
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from config import WEBAPP_URL
from formatter import monday_of_iso, now_iso, split_message
from formatter_all import format_day_all, format_week_all
from schedule_all import (
    COURSES,
    COURSE_IDS,
    group_display,
    group_ids,
    group_days,
    course_title,
)
from storage import SelectionStorage

router = Router()
storage = SelectionStorage()

DAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]


def get_ctx(chat_id: int) -> tuple[str, str]:
    sel = storage.get(chat_id)
    return sel.get("course"), sel.get("group")


def main_menu_keyboard(course: str, gid: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Сегодня", callback_data="today"),
         InlineKeyboardButton(text="Завтра", callback_data="tomorrow")],
        [InlineKeyboardButton(text="Вся неделя", callback_data="week")],
    ]
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(
            text=" Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL))])
    rows.append([InlineKeyboardButton(
        text="Сменить группу", callback_data="groups_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def day_keyboard(d: date) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="‹", callback_data=f"daynav:{d - timedelta(days=1)}"),
         InlineKeyboardButton(text="Сегодня", callback_data="today"),
         InlineKeyboardButton(text="›", callback_data=f"daynav:{d + timedelta(days=1)}")],
        [InlineKeyboardButton(text="Неделя", callback_data="week"),
         InlineKeyboardButton(text="Меню", callback_data="menu")],
    ])


def week_keyboard(monday: date) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="‹", callback_data=f"weeknav:{monday - timedelta(days=7)}"),
         InlineKeyboardButton(text="Эта неделя", callback_data="week"),
         InlineKeyboardButton(text="›", callback_data=f"weeknav:{monday + timedelta(days=7)}")],
        [InlineKeyboardButton(text="Сегодня", callback_data="today"),
         InlineKeyboardButton(text="Меню", callback_data="menu")],
    ])


def courses_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{c} курс", callback_data=f"course:{c}")]
            for c in COURSE_IDS]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def groups_keyboard(course: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for gid in group_ids(course):
        row.append(InlineKeyboardButton(
            text=group_display(course, gid), callback_data=f"pick:{course}:{gid}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Другой курс", callback_data="courses_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def safe_edit(callback: CallbackQuery, text: str,
                    keyboard: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


def menu_text(course: str, gid: str) -> str:
    return (f"<b>Расписание ЕТИ</b>\n{course_title(course)}\n"
            f"Группа: <b>{group_display(course, gid)}</b>\n\n"
            "Выбери, что посмотреть:")


def require_group(func):
    """Декоратор: без выбранной группы — показать выбор."""
    return func


async def ensure_selected(message: Message) -> tuple[str, str] | None:
    course, gid = get_ctx(message.chat.id)
    if course not in COURSES or gid not in group_ids(course):
        await message.answer(
            "Выбери курс и группу:", reply_markup=courses_keyboard())
        return None
    return course, gid


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    course, gid = get_ctx(message.chat.id)
    if course not in COURSES or gid not in group_ids(course):
        await message.answer(
            "<b>Расписание занятий ЕТИ МГТУ «СТАНКИН»</b>\n\n"
            "Выбери курс и группу:",
            reply_markup=courses_keyboard())
        return
    await message.answer(
        menu_text(course, gid), reply_markup=main_menu_keyboard(course, gid))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/start — главное меню\n"
        "/today — расписание на сегодня\n"
        "/tomorrow — на завтра\n"
        "/week — вся неделя\n"
        "/date DD.MM — на дату\n"
        "/monday ... /saturday — по дням недели\n"
        "/groups — сменить группу\n"
        "/webapp — открыть приложение")


@router.message(Command("groups"))
async def cmd_groups(message: Message) -> None:
    await message.answer("Выбери курс:", reply_markup=courses_keyboard())


@router.message(Command("webapp"))
async def cmd_webapp(message: Message) -> None:
    if not WEBAPP_URL:
        await message.answer("Mini App не настроен.")
        return
    await message.answer(
        "Открываю приложение:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Расписание ЕТИ",
                                 web_app=WebAppInfo(url=WEBAPP_URL))]]))


async def send_day(target: Message, d: date, course: str, gid: str) -> None:
    days = group_days(course, gid)
    text = format_day_all(days, d.isoformat())
    for chunk in split_message(text):
        await target.answer(chunk, reply_markup=day_keyboard(d))


async def send_week(target: Message, monday: date, course: str, gid: str) -> None:
    days = group_days(course, gid)
    text = format_week_all(days, monday.isoformat())
    for chunk in split_message(text):
        await target.answer(chunk, reply_markup=week_keyboard(monday))


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    ctx = await ensure_selected(message)
    if ctx:
        await send_day(message, now_iso().date(), *ctx)


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message) -> None:
    ctx = await ensure_selected(message)
    if ctx:
        await send_day(message, now_iso().date() + timedelta(days=1), *ctx)


@router.message(Command("week"))
async def cmd_week(message: Message) -> None:
    ctx = await ensure_selected(message)
    if ctx:
        await send_week(message, monday_of_iso(now_iso().date()), *ctx)


@router.message(Command("date"))
async def cmd_date(message: Message) -> None:
    ctx = await ensure_selected(message)
    if not ctx:
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Формат: /date DD.MM")
        return
    try:
        dd, mm = (int(x) for x in parts[1].split(".")[:2])
        year = 2026 if mm >= 7 else 2027
        d = date(year, mm, dd)
    except ValueError:
        await message.answer("Не понял дату. Формат: /date DD.MM")
        return
    await send_day(message, d, *ctx)


DAY_COMMANDS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5}


@router.message(Command(*DAY_COMMANDS))
async def cmd_day(message: Message) -> None:
    ctx = await ensure_selected(message)
    if not ctx:
        return
    cmd = (message.text or "").lstrip("/").split()[0].lower()
    offset = DAY_COMMANDS.get(cmd)
    if offset is None:
        return
    d = monday_of_iso(now_iso().date()) + timedelta(days=offset)
    await send_day(message, d, *ctx)


# ---------------- callbacks ----------------

@router.callback_query(F.data.startswith("course:"))
async def cb_course(callback: CallbackQuery) -> None:
    course = callback.data.split(":", 1)[1]
    if course not in COURSES:
        await callback.answer()
        return
    await safe_edit(callback, f"{course_title(course)}. Выбери группу:",
                    groups_keyboard(course))
    await callback.answer()


@router.callback_query(F.data == "courses_menu")
async def cb_courses(callback: CallbackQuery) -> None:
    await safe_edit(callback, "Выбери курс:", courses_keyboard())
    await callback.answer()


@router.callback_query(F.data == "groups_menu")
async def cb_groups_menu(callback: CallbackQuery) -> None:
    await safe_edit(callback, "Выбери курс:", courses_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick(callback: CallbackQuery) -> None:
    _, course, gid = callback.data.split(":", 2)
    if course not in COURSES or gid not in group_ids(course):
        await callback.answer()
        return
    storage.set_group(callback.message.chat.id, course, gid)
    await callback.message.edit_text(
        f"Группа: <b>{group_display(course, gid)}</b>\n\n" + menu_text(course, gid),
        reply_markup=main_menu_keyboard(course, gid))
    await callback.answer(f"{group_display(course, gid)} выбрана")


@router.callback_query(F.data == "today")
async def cb_today(callback: CallbackQuery) -> None:
    course, gid = get_ctx(callback.message.chat.id)
    if not course:
        await callback.answer("Сначала выбери группу", show_alert=True)
        return
    await safe_edit(callback, format_day_all(group_days(course, gid), now_iso().date().isoformat()),
                    day_keyboard(now_iso().date()))
    await callback.answer()


@router.callback_query(F.data == "tomorrow")
async def cb_tomorrow(callback: CallbackQuery) -> None:
    course, gid = get_ctx(callback.message.chat.id)
    if not course:
        await callback.answer("Сначала выбери группу", show_alert=True)
        return
    d = now_iso().date() + timedelta(days=1)
    await safe_edit(callback, format_day_all(group_days(course, gid), d.isoformat()),
                    day_keyboard(d))
    await callback.answer()


@router.callback_query(F.data == "week")
async def cb_week(callback: CallbackQuery) -> None:
    course, gid = get_ctx(callback.message.chat.id)
    if not course:
        await callback.answer("Сначала выбери группу", show_alert=True)
        return
    monday = monday_of_iso(now_iso().date())
    await safe_edit(callback, format_week_all(group_days(course, gid), monday.isoformat()),
                    week_keyboard(monday))
    await callback.answer()


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery) -> None:
    course, gid = get_ctx(callback.message.chat.id)
    if not course:
        await callback.answer()
        return
    await safe_edit(callback, menu_text(course, gid),
                    main_menu_keyboard(course, gid))
    await callback.answer()


@router.callback_query(F.data.startswith("daynav:"))
async def cb_daynav(callback: CallbackQuery) -> None:
    course, gid = get_ctx(callback.message.chat.id)
    if not course:
        await callback.answer()
        return
    try:
        d = date.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    await safe_edit(callback, format_day_all(group_days(course, gid), d.isoformat()),
                    day_keyboard(d))
    await callback.answer()


@router.callback_query(F.data.startswith("weeknav:"))
async def cb_weeknav(callback: CallbackQuery) -> None:
    course, gid = get_ctx(callback.message.chat.id)
    if not course:
        await callback.answer()
        return
    try:
        monday = date.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    await safe_edit(callback, format_week_all(group_days(course, gid), monday.isoformat()),
                    week_keyboard(monday))
    await callback.answer()
