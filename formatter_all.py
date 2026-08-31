"""Форматтер расписания для произвольной группы (общий бот)."""

import html

from formatter import (
    DAY_NAMES_RU,
    plural_pairs,
    split_message,
)

WEEKDAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]


def active_slots(days: dict, iso: str) -> list[dict]:
    """Слоты дня с занятиями, актуальными на дату iso (YYYY-MM-DD)."""
    day = days.get(iso and WEEKDAY_KEYS[_wd(iso)])
    if not day:
        return []
    out = []
    for slot in day["slots"]:
        lessons = [l for l in slot["lessons"] if _is_active(l, iso)]
        if lessons:
            out.append({"time": slot["time"], "pair": slot.get("pair", 0),
                        "lessons": lessons})
    return out


def _wd(iso: str) -> int:
    from datetime import date
    return date.fromisoformat(iso).weekday()


def _is_active(lesson: dict, iso: str) -> bool:
    for r_from, r_to in lesson.get("ranges", []):
        if r_from <= iso <= r_to:
            return True
    return iso in lesson.get("exact_dates", [])


def _fmt_lesson(lesson: dict, num: int | None = None) -> str:
    head = f"{num}. " if num is not None else ""
    room = lesson.get("room") or "ауд. не указана"
    line = (f"{head}{html.escape(lesson['kind'])} "
            f"{html.escape(lesson['subject'])}\n"
            f"    {html.escape(lesson['teacher'])} | ауд. {html.escape(room)}")
    parts = []
    for r_from, r_to in lesson.get("ranges", []):
        f = r_from.split("-")   # [year, month, day]
        t = r_to.split("-")
        parts.append(f"с {f[2]}.{f[1]} по {t[2]}.{t[1]}")
    for iso in lesson.get("exact_dates", []):
        y, m, d = iso.split("-")
        parts.append(f"{d}.{m}")
    if parts:
        line += f"\n    ({html.escape(', '.join(parts))})"
    link = lesson.get("link")
    if link:
        line += f'\n    <a href="{html.escape(link, quote=True)}">ссылка на онлайн</a>'
    return line


def format_day_all(days: dict, iso: str, title: str | None = None) -> str:
    from datetime import date as _d
    d = _d.fromisoformat(iso)
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
    from datetime import date as _d, timedelta
    start = _d.fromisoformat(monday_iso)
    lines = [f"<b>Неделя {start.strftime('%d.%m')} — "
             f"{(start + __import__('datetime').timedelta(days=5)).strftime('%d.%m.%Y')}</b>",
             ""]
    for i in range(6):
        iso = (start + timedelta(days=i)).isoformat()
        slots = active_slots(days, iso)
        lines.append(f"<b>{DAY_NAMES_RU[WEEKDAY_KEYS[i]]}, "
                     f"{(start + timedelta(days=i)).strftime('%d.%m')}</b>")
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
