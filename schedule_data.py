"""
СГЕНЕРИРОВАНО scripts/parse_pdf.py — руками не править.
Источник: 4curs2026.pdf
"""

import json
from pathlib import Path

_data = json.loads((Path(__file__).parent / 'data' / 'schedule.json').read_text(encoding='utf-8'))

SCHEDULE = _data["schedule"]
DAY_ORDER = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
DAY_NAMES_RU = {"monday": "Понедельник", "tuesday": "Вторник", "wednesday": "Среда", "thursday": "Четверг", "friday": "Пятница", "saturday": "Суббота"}
SEMESTER_START = _data["semester_start"]
SEMESTER_END = _data["semester_end"]
