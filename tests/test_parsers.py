"""Юнит-тесты фиксов парсеров: якоря дней, чистка subject."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from parse_all import assign_anchors_to_days, clean_subject  # noqa: E402


class TestSaturdayAnchors(unittest.TestCase):
    """Немонотонные хвостовые якоря последнего дня не теряются молча."""

    SECTIONS = {"friday": (0, 100), "saturday": (100, 300)}

    def test_saturday_tail_kept(self):
        anchors = [
            {"time": "08.30-10.05", "y": 110},
            {"time": "10.15-11.50", "y": 150},
            {"time": "08.30-10.05", "y": 200},  # хвост ломает монотонность
        ]
        rows = assign_anchors_to_days(anchors, self.SECTIONS)
        self.assertEqual(len(rows["saturday"]), 3,
                         "хвостовой якорь субботы должен остаться на месте")

    def test_tail_leak_moved_to_next_day(self):
        # хвост пятницы с временем меньше предыдущего — утечка в субботу
        anchors = [
            {"time": "08.30-10.05", "y": 10},
            {"time": "10.15-11.50", "y": 30},
            {"time": "08.30-10.05", "y": 60},
        ]
        rows = assign_anchors_to_days(anchors, self.SECTIONS)
        self.assertEqual(len(rows["friday"]), 2)
        self.assertEqual(len(rows["saturday"]), 1)


class TestCleanSubject(unittest.TestCase):
    def test_trailing_virt_digit_stripped(self):
        self.assertEqual(clean_subject("Физическая культура 3"),
                         "Физическая культура")

    def test_leading_virt_digit_stripped(self):
        self.assertEqual(clean_subject("5 Физическая культура"),
                         "Физическая культура")

    def test_digit_alone_dropped(self):
        self.assertEqual(clean_subject("3"), "")

    def test_mid_digit_preserved(self):
        self.assertEqual(clean_subject("Часть 3 Модуль 5 теории"),
                         "Часть 3 Модуль 5 теории")

    def test_decimal_preserved(self):
        self.assertEqual(clean_subject("Технологии индустрии 4.0"),
                         "Технологии индустрии 4.0")

    def test_trailing_type_marker_cut(self):
        self.assertEqual(clean_subject("Физика лек., пр. Хвост"),
                         "Физика")

    def test_trailing_surname_cut(self):
        self.assertEqual(clean_subject("Математический анализ ПЕТРОВ И.И."),
                         "Математический анализ")


if __name__ == "__main__":
    unittest.main()
