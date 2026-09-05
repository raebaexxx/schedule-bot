"""Поиск занятий по предмету и преподавателю (все курсы и группы)."""

import html

from formatter import lesson_is_active  # iso-фильтр дат
from schedule_all import COURSE_IDS, COURSES


def _dates_str(lesson: dict) -> str:
    parts = []
    for a, b in lesson.get("ranges", []):
        ay, am, ad = a.split("-")
        by, bm, bd = b.split("-")
        parts.append(f"с {ad}.{am} по {bd}.{bm}")
    for iso in lesson.get("exact_dates", []):
        _, m, d = iso.split("-")
        parts.append(f"{d}.{m}")
    return ", ".join(parts)


DAY_RU = {"monday": "ПН", "tuesday": "ВТ", "wednesday": "СР", "thursday": "ЧТ",
          "friday": "ПТ", "saturday": "СБ"}


def search(query: str, iso: str | None = None, limit_groups: int = 40):
    """Поиск по подстроке предмета/преподавателя (case-insensitive).

    Возвращает список словарей:
      {course, gid, display, day, time, pair, lesson}
    отсортированный по (курс, группа, день, время). iso — если задан,
    оставлять только занятия, активные на эту дату.
    """
    q = query.strip().lower()
    if len(q) < 3:
        return []
    results = []
    for course in COURSE_IDS:
        cdata = COURSES.get(course, {})
        for gid, grp in cdata.get("groups", {}).items():
            for day in ("monday", "tuesday", "wednesday", "thursday",
                        "friday", "saturday"):
                ddata = grp["days"].get(day)
                if not ddata:
                    continue
                for slot in ddata["slots"]:
                    for lesson in slot["lessons"]:
                        if (q in lesson.get("subject", "").lower()
                                or q in lesson.get("teacher", "").lower()):
                            if iso and not lesson_is_active(lesson, iso):
                                continue
                            results.append({
                                "course": course,
                                "gid": gid,
                                "display": grp.get("display", gid),
                                "day": day,
                                "time": slot["time"],
                                "pair": slot.get("pair", 0),
                                "lesson": lesson,
                            })
    return results


def format_results(results: list, query: str, max_lines: int = 60) -> str:
    """HTML-текст ответа на поиск."""
    if not results:
        return (f"По запросу <b>{html.escape(query)}</b> ничего не найдено.\n"
                "Подсказка: ищется подстрока в названии предмета или фамилии "
                "преподавателя, минимум 3 символа.")

    # группировка: курс → группа
    lines = [f"<b>Поиск: {html.escape(query)}</b>",
             f"Найдено занятий: {len(results)}", ""]
    shown = 0
    last_head = None
    for r in results:
        if shown >= max_lines:
            rest = len(results) - shown
            lines.append(f"… и ещё {rest} — уточните запрос")
            break
        head = f"{r['display']} ({r['course']} курс)"
        if head != last_head:
            lines.append(f"<b>{html.escape(head)}</b>")
            last_head = head
        lesson = r["lesson"]
        room = f", ауд.{lesson['room']}" if lesson.get("room") else ""
        dates = _dates_str(lesson)
        ds = f" · {dates}" if dates else ""
        lines.append(
            f"  {html.escape(DAY_RU.get(r['day'], r['day'][:2]))} {html.escape(r['time'])} · "
            f"{html.escape(lesson['kind'] or '—')} "
            f"{html.escape(lesson['subject'])} "
            f"({html.escape(lesson['teacher'])}{html.escape(room)}){html.escape(ds)}")
        shown += 1
    return "\n".join(lines)
