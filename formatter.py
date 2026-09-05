"""Форматирование расписания (общий бот: произвольная группа, фильтр по датам)."""

import html
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Moscow")

WEEKDAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
                "saturday", "sunday"]
DAY_NAMES_RU = {
    "monday": "Понедельник", "tuesday": "Вторник", "wednesday": "Среда",
    "thursday": "Четверг", "friday": "Пятница", "saturday": "Суббота",
    "sunday": "Воскресенье",
}


def now() -> datetime:
    return datetime.now(TZ)


now_iso = now  # алиас


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def monday_of_iso(d: date) -> date:
    return monday_of(d)


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


def lesson_is_active(lesson: dict, iso: str) -> bool:
    for r_from, r_to in lesson.get("ranges", []):
        if r_from <= iso <= r_to:
            return True
    return iso in lesson.get("exact_dates", [])


def active_slots(days: dict, iso: str) -> list[dict]:
    """Слоты дня с занятиями, актуальными на дату iso (YYYY-MM-DD)."""
    day_key = WEEKDAY_KEYS[date.fromisoformat(iso).weekday()]
    day = days.get(day_key)
    if not day:
        return []
    out = []
    for slot in day["slots"]:
        lessons = [l for l in slot["lessons"] if lesson_is_active(l, iso)]
        if lessons:
            out.append({"time": slot["time"], "pair": slot.get("pair", 0),
                        "lessons": lessons})
    return out


def count_lessons(slots: list[dict]) -> int:
    return sum(len(s["lessons"]) for s in slots)


def _fmt_lesson(lesson: dict, num: int | None = None) -> str:
    head = f"{num}. " if num is not None else ""
    room = lesson.get("room") or "ауд. не указана"
    line = (f"{head}{html.escape(lesson['kind'])} "
            f"{html.escape(lesson['subject'])}\n"
            f"    {html.escape(lesson['teacher'])} | ауд. {html.escape(room)}")
    parts = []
    for r_from, r_to in lesson.get("ranges", []):
        fy, fm, fd = r_from.split("-")
        ty, tm, td = r_to.split("-")
        parts.append(f"с {fd}.{fm} по {td}.{tm}")
    for iso in lesson.get("exact_dates", []):
        _, m, d = iso.split("-")
        parts.append(f"{d}.{m}")
    if parts:
        line += f"\n    ({html.escape(', '.join(parts))})"
    link = lesson.get("link")
    if link:
        line += f'\n    <a href="{html.escape(link, quote=True)}">ссылка на онлайн</a>'
    return line


def format_day_all(days: dict, iso: str, title: str | None = None) -> str:
    d = date.fromisoformat(iso)
    wd = d.weekday()
    name = DAY_NAMES_RU[WEEKDAY_KEYS[wd]]
    header = title or f"{name}, {d.strftime('%d.%m.%Y')}"
    lines = [f"<b>{html.escape(header)}</b>", ""]
    if wd == 6:
        lines.append("Воскресенье — занятий нет.")
        return "\n".join(lines)
    slots = active_slots(days, iso)
    if not slots:
        lines.append("Занятий нет.")
        return "\n".join(lines)
    for slot in slots:
        pair = slot.get("pair")
        time_head = f"{pair}. {slot['time']}" if pair else slot["time"]
        lines.append(f"<b>{html.escape(time_head)}</b>")
        for i, lesson in enumerate(slot["lessons"], 1):
            lines.append(_fmt_lesson(lesson, i if len(slot["lessons"]) > 1 else None))
        lines.append("")
    return "\n".join(lines).rstrip()


def format_week_all(days: dict, monday_iso: str) -> str:
    start = date.fromisoformat(monday_iso)
    lines = [f"<b>Неделя {start.strftime('%d.%m')} — "
             f"{(start + timedelta(days=5)).strftime('%d.%m.%Y')}</b>", ""]
    for i in range(6):
        d = start + timedelta(days=i)
        iso = d.isoformat()
        slots = active_slots(days, iso)
        lines.append(f"<b>{DAY_NAMES_RU[WEEKDAY_KEYS[i]]}, {d.strftime('%d.%m')}</b>")
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


def digest_text(days: dict, d: date) -> str | None:
    """Утренний дайджест по группе. None — пар нет (в т.ч. воскресенье)."""
    if d.weekday() == 6:
        return None
    slots = active_slots(days, d.isoformat())
    total = count_lessons(slots)
    if total == 0:
        return None
    day_key = WEEKDAY_KEYS[d.weekday()]
    title = (f"Доброе утро! Сегодня {DAY_NAMES_RU[day_key]}, "
             f"{d.strftime('%d.%m')} — {plural_pairs(total)}")
    return format_day_all(days, d.isoformat(), title=title)
