"""Тесты фильтрации по датам и форматирования."""

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from formatter import (  # noqa: E402
    active_lessons,
    format_day_by_date,
    format_week,
    lesson_is_active,
    split_message,
)


class TestLessonActive(unittest.TestCase):
    LESSON = {
        "ranges": [["2026-09-07", "2026-11-09"]],
        "exact_dates": ["2026-11-16"],
    }

    def test_range_bounds_inclusive(self):
        self.assertTrue(lesson_is_active(self.LESSON, date(2026, 9, 7)))
        self.assertTrue(lesson_is_active(self.LESSON, date(2026, 11, 9)))
        self.assertFalse(lesson_is_active(self.LESSON, date(2026, 11, 10)))

    def test_exact_date(self):
        self.assertTrue(lesson_is_active(self.LESSON, date(2026, 11, 16)))
        self.assertFalse(lesson_is_active(self.LESSON, date(2026, 11, 23)))

    def test_outside(self):
        self.assertFalse(lesson_is_active(self.LESSON, date(2026, 9, 6)))
        self.assertFalse(lesson_is_active(self.LESSON, date(2026, 12, 7)))


class TestActiveLessons(unittest.TestCase):
    def test_first_semester_day(self):
        # ПН 07.09.2026: ТПАП (с 07.09) в 08:30, Проект (с 07.09) в 10:15,
        # Бережливое (с 07.09) в 12:20 и 14:05
        slots = active_lessons("monday", date(2026, 9, 7))
        self.assertEqual(len(slots), 4)
        subjects = [l["subject"] for s in slots for l in s["lessons"]]
        self.assertEqual(len(subjects), 4)
        self.assertFalse(any("информатика" in s.lower() for s in subjects))

    def test_exact_date_only(self):
        # ПН 16.11: все 4 слота активны, но Бережливое (до 28.09) — нет
        slots = active_lessons("monday", date(2026, 11, 16))
        subjects = [l["subject"] for s in slots for l in s["lessons"]]
        self.assertEqual(len(slots), 4)
        self.assertFalse(any("Бережливое" in s for s in subjects))
        by_time = {s["time"]: [l["subject"] for l in s["lessons"]]
                   for s in slots}
        self.assertIn("Технологическая информатика автоматизированного "
                      "производства", by_time["08:30-10:05"])
        self.assertIn("Основы автоматизированного проектирования машин",
                      by_time["14:05-15:40"])

    def test_late_semester(self):
        # ПН 07.12: активны только лаб. ТИАП (30.11 и 07.12) в 08:30 и 10:15
        slots = active_lessons("monday", date(2026, 12, 7))
        subjects = [l["subject"] for s in slots for l in s["lessons"]]
        self.assertEqual(len(subjects), 2)
        self.assertFalse(any("Бережливое" in s for s in subjects))
        self.assertTrue(all("информатика" in s.lower() for s in subjects))

    def test_sunday_empty(self):
        self.assertEqual(active_lessons("monday", date(2026, 8, 30)), [])

    def test_after_semester(self):
        self.assertEqual(active_lessons("monday", date(2026, 12, 29)), [])


class TestFormatting(unittest.TestCase):
    def test_sunday_message(self):
        text = format_day_by_date(date(2026, 9, 13))
        self.assertIn("занятий нет", text)

    def test_day_contains_header_and_time(self):
        text = format_day_by_date(date(2026, 9, 7))
        self.assertIn("Понедельник, 07.09.2026", text)
        self.assertIn("08:30-10:05", text)
        self.assertIn("МАХОВ М.А.", text)

    def test_empty_day_message(self):
        text = format_day_by_date(date(2026, 12, 29))
        self.assertIn("Занятий нет", text)

    def test_week_structure(self):
        text = format_week(date(2026, 9, 7))
        for name in ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница"):
            self.assertIn(name, text)
        self.assertNotIn("Суббота", text)

    def test_pair_number_shown(self):
        text = format_day_by_date(date(2026, 9, 7))
        self.assertRegex(text, r"<b>1\. 08:30-10:05</b>")
        self.assertRegex(text, r"<b>3\. 12:20-13:55</b>")

    def test_split_message(self):
        text = "\n".join(f"строка {i} " + "x" * 50 for i in range(200))
        chunks = split_message(text, limit=1000)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 1000)
        self.assertEqual("\n".join(chunks), text)


if __name__ == "__main__":
    unittest.main()
