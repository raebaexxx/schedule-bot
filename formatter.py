"""Форматирование расписания с фильтрацией по датам."""

import html
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from schedule_data import DAY_NAMES_RU, DAY_ORDER, SCHEDULE

TZ = ZoneInfo("Europe/Moscow")

WEEKDAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
# Суббота в БА-231 не используется — бот показывает 5 дней
BOT_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]


def now() -> datetime:
    return datetime.now(TZ)


now_iso = now  # алиас для общего бота


def lesson_is_active(lesson: dict, d: date) -> bool:
    for r_from, r_to in lesson.get("ranges", []):
        if date.fromisoformat(r_from) <= d <= date.fromisoformat(r_to):
            return True
    for iso in lesson.get("exact_dates", []):
        if date.fromisoformat(iso) == d:
            return True
    return False


def active_lessons(day_key: str, d: date) -> list[dict]:
    """Слоты дня с занятиями, актуальными именно на дату d."""
    day = SCHEDULE.get(day_key)
    if not day:
        return []
    result = []
    for slot in day["slots"]:
        lessons = [l for l in slot["lessons"] if lesson_is_active(l, d)]
        if lessons:
            result.append({"time": slot["time"], "pair": slot.get("pair", 0),
                           "lessons": lessons})
    return result


def dates_note(lesson: dict) -> str:
    parts = []
    for r_from, r_to in lesson.get("ranges", []):
        f = date.fromisoformat(r_from)
        t = date.fromisoformat(r_to)
        parts.append(f"с {f.strftime('%d.%m')} по {t.strftime('%d.%m')}")
    for iso in lesson.get("exact_dates", []):
        parts.append(date.fromisoformat(iso).strftime("%d.%m"))
    return ", ".join(parts)


def format_lesson(lesson: dict, num: int | None = None) -> str:
    head = f"{num}. " if num is not None else ""
    room = lesson.get("room") or "ауд. не указана"
    line = (f"{head}{html.escape(lesson['kind'])} "
            f"{html.escape(lesson['subject'])}\n"
            f"    {html.escape(lesson['teacher'])} | ауд. {html.escape(room)}")
    note = dates_note(lesson)
    if note:
        line += f"\n    ({html.escape(note)})"
    link = lesson.get("link")
    if link:
        line += f'\n    <a href="{html.escape(link, quote=True)}">ссылка на онлайн</a>'
    return line


def format_day_by_date(d: date, title: str | None = None) -> str:
    if d.weekday() == 6:
        name = "Воскресенье"
        return (f"<b>{name}, {d.strftime('%d.%m.%Y')}</b>\n\n"
                "Воскресенье — занятий нет.")
    day_key = WEEKDAY_KEYS[d.weekday()]
    slots = active_lessons(day_key, d)
    name = DAY_NAMES_RU[day_key]
    header = title or f"{name}, {d.strftime('%d.%m.%Y')}"
    lines = [f"<b>{html.escape(header)}</b>", ""]
    if not slots:
        lines.append("Занятий нет.")
        return "\n".join(lines)
    for slot in slots:
        pair = slot.get("pair")
        time_head = f"{pair}. {slot['time']}" if pair else slot["time"]
        lines.append(f"<b>{html.escape(time_head)}</b>")
        for i, lesson in enumerate(slot["lessons"], 1):
            lines.append(format_lesson(lesson, i if len(slot["lessons"]) > 1 else None))
        lines.append("")
    return "\n".join(lines).rstrip()


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def monday_of_iso(d: date) -> date:
    return monday_of(d)


def format_week(start: date | None = None) -> str:
    start = start or monday_of(now().date())
    lines = [f"<b>Неделя {start.strftime('%d.%m')} — "
             f"{(start + timedelta(days=4)).strftime('%d.%m.%Y')}</b>", ""]
    for i, day_key in enumerate(BOT_DAYS):
        d = start + timedelta(days=i)
        slots = active_lessons(day_key, d)
        lines.append(f"<b>{DAY_NAMES_RU[day_key]}, {d.strftime('%d.%m')}</b>")
        if not slots:
            lines.append("  —")
        else:
            for slot in slots:
                pair = slot.get("pair")
                time_head = f"{pair}. {slot['time']}" if pair else slot["time"]
                for lesson in slot["lessons"]:
                    room = lesson.get("room") or "—"
                    lines.append(
                        f"  {html.escape(time_head)} "
                        f"{html.escape(lesson['kind'])} "
                        f"{html.escape(lesson['subject'])} "
                        f"({html.escape(lesson['teacher'])}, ауд. "
                        f"{html.escape(room)})")
        lines.append("")
    return "\n".join(lines).rstrip()


def split_message(text: str, limit: int = 3900) -> list[str]:
    """Режет длинный текст на части по границам строк."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], []
    size = 0
    for line in text.splitlines():
        if size + len(line) + 1 > limit and cur:
            chunks.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def plural_pairs(n: int) -> str:
    if n == 1:
        return "1 пара"
    if 2 <= n <= 4:
        return f"{n} пары"
    return f"{n} пар"


def digest_text(d: date) -> str | None:
    """Утренний дайджест: заголовок + расписание дня. None — пар нет."""
    if d.weekday() == 6:
        return None
    day_key = WEEKDAY_KEYS[d.weekday()]
    slots = active_lessons(day_key, d)
    total = sum(len(s["lessons"]) for s in slots)
    if total == 0:
        return None
    title = (f"Доброе утро! Сегодня {DAY_NAMES_RU[day_key]}, "
             f"{d.strftime('%d.%m')} — {plural_pairs(total)}")
    return format_day_by_date(d, title=title)
