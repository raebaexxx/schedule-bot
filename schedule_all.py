"""Данные расписания всех курсов (генерируется scripts/parse_all.py)."""

import json
from pathlib import Path

_data = json.loads(
    (Path(__file__).parent / "data" / "schedule_all.json").read_text(encoding="utf-8"))

COURSES = _data["courses"]
SEMESTER_START = _data["semester_start"]
SEMESTER_END = _data["semester_end"]
COURSE_IDS = sorted(COURSES, key=int)


def group_ids(course: str) -> list[str]:
    return list(COURSES[course]["groups"])


def group_display(course: str, gid: str) -> str:
    return COURSES[course]["groups"][gid]["display"]


def group_days(course: str, gid: str) -> dict:
    """{day: {"name": ..., "slots": [{time, pair, lessons}]}}"""
    return COURSES[course]["groups"][gid]["days"]


def course_title(course: str) -> str:
    sem = COURSES[course]["semester"]
    return f"{course} курс · {sem}" if sem else f"{course} курс"
