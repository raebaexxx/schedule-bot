"""Хэндлеры общего бота расписания ЕТИ (все курсы и группы)."""

import re
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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
from formatter import (
    format_day_all,
    format_week_all,
    monday_of_iso,
    now_iso,
    split_message,
)
from search import search as search_lessons, format_results as format_search
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
    rows.append([
        InlineKeyboardButton(text="Сменить группу", callback_data="groups_menu"),
        InlineKeyboardButton(text="Настройки", callback_data="settings")])
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
async def cmd_start(message: Message, **kwargs) -> None:
    # подписка на дайджест создаётся по умолчанию (07:00 МСК), отключается в /settings
    u = message.from_user
    storage.get_or_create(message.chat.id,
                          first_name=(u.first_name or "") if u else "",
                          username=(u.username or "") if u else "")
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
async def cmd_help(message: Message, **kwargs) -> None:
    await message.answer(
        "Команды:\n"
        "/start — главное меню\n"
        "/today — расписание на сегодня\n"
        "/tomorrow — на завтра\n"
        "/week — вся неделя\n"
        "/date DD.MM — на дату\n"
        "/monday ... /saturday — по дням недели\n"
        "/groups — сменить группу\n"
        "/settings — дайджест: вкл/выкл и время\n"
        "/find запрос — поиск по предмету/преподавателю\n"
        "/webapp — открыть приложение")


@router.message(Command("groups"))
async def cmd_groups(message: Message, **kwargs) -> None:
    await message.answer("Выбери курс:", reply_markup=courses_keyboard())


@router.message(Command("webapp"))
async def cmd_webapp(message: Message, **kwargs) -> None:
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
async def cmd_today(message: Message, **kwargs) -> None:
    ctx = await ensure_selected(message)
    if ctx:
        await send_day(message, now_iso().date(), *ctx)


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message, **kwargs) -> None:
    ctx = await ensure_selected(message)
    if ctx:
        await send_day(message, now_iso().date() + timedelta(days=1), *ctx)


@router.message(Command("week"))
async def cmd_week(message: Message, **kwargs) -> None:
    ctx = await ensure_selected(message)
    if ctx:
        await send_week(message, monday_of_iso(now_iso().date()), *ctx)


@router.message(Command("date"))
async def cmd_date(message: Message, **kwargs) -> None:
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
async def cmd_day(message: Message, **kwargs) -> None:
    ctx = await ensure_selected(message)
    if not ctx:
        return
    cmd = (message.text or "").lstrip("/").split()[0].lower()
    offset = DAY_COMMANDS.get(cmd)
    if offset is None:
        return
    d = monday_of_iso(now_iso().date()) + timedelta(days=offset)
    await send_day(message, d, *ctx)



# ---------------- поиск по предмету / преподавателю ----------------

FIND_LIMIT = 120  # мягкий лимит результатов


@router.message(Command("find"))
async def cmd_find(message: Message, **kwargs) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or len(parts[1].strip()) < 3:
        await message.answer(
            "Формат: <code>/find запрос</code> — минимум 3 символа.\n"
            "Ищет по названию предмета и фамилии преподавателя во всех курсах.\n"
            "Например: <code>/find махов</code> или <code>/find сопротивление</code>")
        return
    query = parts[1].strip()
    results = search_lessons(query)
    text = format_search(results, query, max_lines=FIND_LIMIT)
    for chunk in split_message(text):
        await message.answer(chunk)


# ---------------- callbacks ----------------


# ---------------- настройки утреннего дайджеста ----------------

class SettingsStates(StatesGroup):
    waiting_time = State()


TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
PRESET_TIMES = ["06:30", "07:00", "07:30", "08:00"]


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
    state = "включён" if user.get("digest_enabled") else "выключен"
    if user.get("digest_enabled"):
        return (f"<b>Настройки</b>\n\n"
                f"Утренний дайджест: <b>{state}</b>\n"
                f"Время: <b>{user.get('time', '07:00')} МСК</b>\n\n"
                "Каждое утро бот пришлёт расписание твоей группы. "
                "Если пар нет — не пишет.")
    return ("<b>Настройки</b>\n\n"
            f"Утренний дайджест: <b>{state}</b>\n\n"
            "Включите, чтобы получать расписание своей группы каждое утро.")


@router.message(Command("settings"))
async def cmd_settings(message: Message, **kwargs) -> None:
    user = storage.get_or_create(message.chat.id)
    await message.answer(settings_text(user),
                         reply_markup=settings_keyboard(user.get("digest_enabled", False)))


@router.callback_query(F.data == "settings")
async def cb_settings(callback: CallbackQuery, **kwargs) -> None:
    user = storage.get_or_create(callback.message.chat.id)
    await safe_edit(callback, settings_text(user),
                    settings_keyboard(user.get("digest_enabled", False)))
    await callback.answer()


@router.callback_query(F.data == "notify:on")
async def cb_notify_on(callback: CallbackQuery, **kwargs) -> None:
    user = storage.set_digest_enabled(callback.message.chat.id, True)
    await safe_edit(callback, settings_text(user), settings_keyboard(True))
    await callback.answer("Включено")


@router.callback_query(F.data == "notify:off")
async def cb_notify_off(callback: CallbackQuery, **kwargs) -> None:
    user = storage.set_digest_enabled(callback.message.chat.id, False)
    await safe_edit(callback, settings_text(user), settings_keyboard(False))
    await callback.answer("Выключено")


@router.callback_query(F.data.startswith("time:"))
async def cb_time(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
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
    user = storage.set_digest_time(chat_id, value)
    await state.clear()
    await safe_edit(callback, settings_text(user), settings_keyboard(True))
    await callback.answer(f"Время: {value} МСК")


@router.message(SettingsStates.waiting_time)
async def msg_custom_time(message: Message, state: FSMContext, **kwargs) -> None:
    text = (message.text or "").strip()
    if not TIME_RE.match(text):
        await message.answer(
            "Не понял. Время в формате ЧЧ:ММ, например <code>07:15</code> "
            "(часы 00–23, минуты 00–59)")
        return
    hh, mm = text.split(":")
    normalized = f"{int(hh):02d}:{mm}"
    user = storage.set_digest_time(message.chat.id, normalized)
    await state.clear()
    await message.answer(f"Готово! Дайджест будет приходить в {user['time']} МСК",
                         reply_markup=settings_keyboard(user.get("digest_enabled", False)))


@router.callback_query(F.data.startswith("course:"))
async def cb_course(callback: CallbackQuery, **kwargs) -> None:
    course = callback.data.split(":", 1)[1]
    if course not in COURSES:
        await callback.answer()
        return
    await safe_edit(callback, f"{course_title(course)}. Выбери группу:",
                    groups_keyboard(course))
    await callback.answer()


@router.callback_query(F.data == "courses_menu")
async def cb_courses(callback: CallbackQuery, **kwargs) -> None:
    await safe_edit(callback, "Выбери курс:", courses_keyboard())
    await callback.answer()


@router.callback_query(F.data == "groups_menu")
async def cb_groups_menu(callback: CallbackQuery, **kwargs) -> None:
    await safe_edit(callback, "Выбери курс:", courses_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick(callback: CallbackQuery, **kwargs) -> None:
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
async def cb_today(callback: CallbackQuery, **kwargs) -> None:
    course, gid = get_ctx(callback.message.chat.id)
    if not course:
        await callback.answer("Сначала выбери группу", show_alert=True)
        return
    await safe_edit(callback, format_day_all(group_days(course, gid), now_iso().date().isoformat()),
                    day_keyboard(now_iso().date()))
    await callback.answer()


@router.callback_query(F.data == "tomorrow")
async def cb_tomorrow(callback: CallbackQuery, **kwargs) -> None:
    course, gid = get_ctx(callback.message.chat.id)
    if not course:
        await callback.answer("Сначала выбери группу", show_alert=True)
        return
    d = now_iso().date() + timedelta(days=1)
    await safe_edit(callback, format_day_all(group_days(course, gid), d.isoformat()),
                    day_keyboard(d))
    await callback.answer()


@router.callback_query(F.data == "week")
async def cb_week(callback: CallbackQuery, **kwargs) -> None:
    course, gid = get_ctx(callback.message.chat.id)
    if not course:
        await callback.answer("Сначала выбери группу", show_alert=True)
        return
    monday = monday_of_iso(now_iso().date())
    await safe_edit(callback, format_week_all(group_days(course, gid), monday.isoformat()),
                    week_keyboard(monday))
    await callback.answer()


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, **kwargs) -> None:
    course, gid = get_ctx(callback.message.chat.id)
    if not course:
        await callback.answer()
        return
    await safe_edit(callback, menu_text(course, gid),
                    main_menu_keyboard(course, gid))
    await callback.answer()


@router.callback_query(F.data.startswith("daynav:"))
async def cb_daynav(callback: CallbackQuery, **kwargs) -> None:
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
async def cb_weeknav(callback: CallbackQuery, **kwargs) -> None:
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
