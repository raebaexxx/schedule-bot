"""Вычисление изменений между версиями schedule_all.json и очередь уведомлений."""

import html
import json
import re
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
PENDING_FILE = DATA_DIR / "pending_changes.json"

DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
DAY_RU = {"monday": "ПН", "tuesday": "ВТ", "wednesday": "СР", "thursday": "ЧТ",
          "friday": "ПТ", "saturday": "СБ"}
DAY_NUM = {d: i for i, d in enumerate(DAY_ORDER)}


def _lesson_key(l: dict) -> tuple:
    return (l.get("kind", ""), l.get("subject", ""), l.get("teacher", ""),
            l.get("room") or "", json.dumps(l.get("ranges", [])),
            json.dumps(l.get("exact_dates", [])), l.get("link") or "")


def _dates_str(l: dict) -> str:
    parts = []
    for a, b in l.get("ranges", []):
        parts.append(f"{a[8:]}.{a[5:7]}..{b[8:]}.{b[5:7]}")
    for d in l.get("exact_dates", []):
        parts.append(f"{d[8:]}.{d[5:7]}")
    return ", ".join(parts)


def _fmt(l: dict, sign: str) -> str:
    room = l.get("room") or ""
    room_s = f", ауд.{room}" if room else ""
    return (f"{sign} {l['kind']} {l['subject']} "
            f"({l['teacher']}{room_s}, {_dates_str(l)})")


def _collect_cells(data: dict) -> dict:
    """{(course, gid, day, time): [lesson, ...]}"""
    cells: dict = {}
    for course, cdata in data["courses"].items():
        for gid, grp in cdata["groups"].items():
            for day, ddata in grp["days"].items():
                for slot in ddata["slots"]:
                    for l in slot["lessons"]:
                        cells.setdefault((course, gid, day, slot["time"]),
                                         []).append(l)
    return cells


def compute_changes(old: dict, new: dict) -> dict[str, list[str]]:
    """{group_key: [строки изменений]}, group_key = 'course:gid'."""
    old_cells = _collect_cells(old)
    new_cells = _collect_cells(new)
    changes: dict[str, list[tuple[tuple, str]]] = {}
    for key in set(old_cells) | set(new_cells):
        o = old_cells.get(key, [])
        n = new_cells.get(key, [])
        o_keys = {_lesson_key(l) for l in o}
        n_keys = {_lesson_key(l) for l in n}
        removed = [l for l in o if _lesson_key(l) not in n_keys]
        added = [l for l in n if _lesson_key(l) not in o_keys]
        if not removed and not added:
            continue
        course, gid, day, time = key
        gkey = f"{course}:{gid}"
        slot = (DAY_NUM[day], time)
        for l in removed:
            changes.setdefault(gkey, []).append((slot, f"{DAY_RU[day]} {time}: − "
                                                      f"{_fmt(l, '').strip()}"))
        for l in added:
            changes.setdefault(gkey, []).append((slot, f"{DAY_RU[day]} {time}: + "
                                                      f"{_fmt(l, '').strip()}"))
    # сортировка по дню/времени внутри группы
    result: dict[str, list[str]] = {}
    for gkey, items in changes.items():
        items.sort(key=lambda x: (x[0][0], x[0][1], x[1]))
        result[gkey] = [text for _, text in items]
    return result


def save_pending(changes: dict[str, list[str]]) -> bool:
    """Сохраняет очередь уведомлений. False — изменений нет."""
    if not changes:
        return False
    DATA_DIR.mkdir(exist_ok=True)
    payload = {"generated": date.today().isoformat(), "changes": changes}
    PENDING_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    return True


def load_pending() -> dict | None:
    if not PENDING_FILE.exists():
        return None
    try:
        return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def clear_pending() -> None:
    PENDING_FILE.unlink(missing_ok=True)


def format_group_changes(gkey: str, lines: list[str], display: str,
                         limit: int = 40) -> str:
    """Сообщение пользователю об изменениях его группы."""
    shown = lines[:limit]
    tail = "" if len(lines) <= limit else f"\n… и ещё {len(lines) - limit} изм."
    body = "\n".join(html.escape(line) for line in shown)
    return (f"<b>Обновление расписания</b>\n"
            f"Группа <b>{html.escape(display)}</b>\n\n" + body + tail)
