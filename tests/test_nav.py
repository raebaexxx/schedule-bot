"""Тесты навигационных клавиатур."""

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handlers import day_keyboard, days_menu_keyboard, week_keyboard  # noqa: E402


class TestNavigation(unittest.TestCase):
    def test_day_nav_dates(self):
        kb = day_keyboard(date(2026, 9, 7))
        row = kb.inline_keyboard[0]
        self.assertEqual([b.text for b in row], ["‹", "Сегодня", "›"])
        self.assertEqual(row[0].callback_data, "daynav:2026-09-06")
        self.assertEqual(row[1].callback_data, "today")
        self.assertEqual(row[2].callback_data, "daynav:2026-09-08")

    def test_day_nav_month_boundary(self):
        kb = day_keyboard(date(2026, 8, 31))
        self.assertEqual(kb.inline_keyboard[0][0].callback_data, "daynav:2026-08-30")
        self.assertEqual(kb.inline_keyboard[0][2].callback_data, "daynav:2026-09-01")

    def test_week_nav(self):
        kb = week_keyboard(date(2026, 9, 7))  # понедельник
        row = kb.inline_keyboard[0]
        self.assertEqual(row[0].callback_data, "weeknav:2026-08-31")
        self.assertEqual(row[1].callback_data, "week")
        self.assertEqual(row[2].callback_data, "weeknav:2026-09-14")

    def test_days_menu_no_saturday(self):
        kb = days_menu_keyboard()
        texts = [b.text for row in kb.inline_keyboard for b in row]
        self.assertNotIn("Сб", texts)
        self.assertIn("Пн", texts)


if __name__ == "__main__":
    unittest.main()
