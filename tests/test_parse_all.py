"""Тесты универсального парсера (все курсы, все группы)."""

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from parse_all import (  # noqa: E402
    PAIR_NUMBERS,
    parse_lesson as _unused,  # noqa: F401  (импорт модуля целиком)
)
import parse_pdf  # noqa: E402
from parse_pdf import parse_lesson  # noqa: E402


class TestFullPipelineAll(unittest.TestCase):
    """Регрессия по данным, сгенерированным из 4 PDF."""

    @classmethod
    def setUpClass(cls):
        import json
        p = ROOT / "data" / "schedule_all.json"
        if not p.exists():
            raise unittest.SkipTest("data/schedule_all.json не сгенерирован")
        cls.data = json.loads(p.read_text(encoding="utf-8"))

    def all_lessons(self):
        for course, cdata in self.data["courses"].items():
            for gid, grp in cdata["groups"].items():
                for day, ddata in grp["days"].items():
                    for slot in ddata["slots"]:
                        for lesson in slot["lessons"]:
                            yield course, gid, day, slot["time"], lesson

    def test_structure(self):
        self.assertEqual(sorted(self.data["courses"]), ["1", "2", "3", "4"])
        self.assertEqual(sorted(self.data["courses"]["1"]["groups"]),
                         ["БК-261", "БТ-261", "БТТ-261"])
        self.assertEqual(sorted(self.data["courses"]["2"]["groups"]),
                         ["БА-251", "БК-251", "БК-251(у)", "БТ-251", "БТТ-251"])
        self.assertEqual(sorted(self.data["courses"]["4"]["groups"]),
                         ["БА-231", "БК-231", "БТ-231", "БЭ-231"])

    def test_total_count(self):
        total = sum(1 for _ in self.all_lessons())
        self.assertEqual(total, 636)

    def test_every_lesson_complete(self):
        for course, gid, day, time, lesson in self.all_lessons():
            with self.subTest(course=course, gid=gid, day=day, time=time):
                self.assertTrue(lesson["kind"])
                self.assertTrue(lesson["subject"])
                self.assertTrue(lesson["teacher"])
                self.assertTrue(lesson["ranges"] or lesson["exact_dates"])

    def test_dates_within_semester(self):
        lo, hi = date(2026, 8, 25), date(2026, 12, 31)
        for course, gid, day, time, lesson in self.all_lessons():
            ds = [x for r in lesson["ranges"] for x in r] + lesson["exact_dates"]
            for d in ds:
                self.assertTrue(lo <= date.fromisoformat(d) <= hi,
                                f"{course}/{gid} {day} {time}: {d}")

    def test_pair_numbers(self):
        for course, cdata in self.data["courses"].items():
            for gid, grp in cdata["groups"].items():
                for day, ddata in grp["days"].items():
                    for slot in ddata["slots"]:
                        self.assertIn(slot["pair"], (1, 2, 3, 4, 5, 6, 7),
                                      f"{course}/{gid} {day} {slot['time']}")

    def test_spot_checks_4curs(self):
        # сверено вручную с PDF 4 курса
        ba = self.data["courses"]["4"]["groups"]["БА-231"]["days"]
        mon = {s["time"]: s["lessons"] for s in ba["monday"]["slots"]}
        self.assertEqual(len(mon["08:30-10:05"]), 4)
        self.assertEqual(mon["08:30-10:05"][1]["exact_dates"], ["2026-11-16"])
        # БК-231 суббота: Технологии индустрии 4.0, АФАНАСЬЕВА
        bk = self.data["courses"]["4"]["groups"]["БК-231"]["days"]
        sat_lessons = [l for s in bk["saturday"]["slots"] for l in s["lessons"]]
        self.assertTrue(any("индустрии 4.0" in l["subject"] for l in sat_lessons))
        self.assertTrue(any(l["teacher"] == "АФАНАСЬЕВА О.В." for l in sat_lessons))

    def test_spot_checks_1curs(self):
        # сверено вручную с PDF 1 курса (стр. ПН 08:30):
        # БК-261: лек. Математический анализ ИЛЮШИН В.Б. 310 (с 07.09 по 07.12)
        bk = self.data["courses"]["1"]["groups"]["БК-261"]["days"]
        mon = {s["time"]: s["lessons"] for s in bk["monday"]["slots"]}
        self.assertEqual(mon["08:30-10:05"][0]["subject"], "Математический анализ")
        self.assertEqual(mon["08:30-10:05"][0]["teacher"], "ИЛЮШИН В.Б.")
        self.assertEqual(mon["08:30-10:05"][0]["room"], "310")
        self.assertEqual(mon["08:30-10:05"][0]["ranges"],
                         [["2026-09-07", "2026-12-07"]])


class TestParseLessonExtended(unittest.TestCase):
    """Доп. кейсы разбора (мультикурсовые особенности)."""

    def test_virtual_priority_over_numeric(self):
        lesson = parse_lesson(
            ["пр.", "Философия", "219", "1", "вирт.", "ауд.", "1",
             "с", "05.09", "по", "07.11"])
        self.assertEqual(lesson["room"], "вирт. ауд. 1")
        self.assertNotIn("219", lesson["subject"])

    def test_slash_room(self):
        lesson = parse_lesson(
            ["лаб.", "Физика", "211/305", "В.Ю.", "с", "24.11", "по", "15.12"])
        self.assertEqual(lesson["room"], "211/305")

    def test_teacher_interleaved(self):
        # ФИО разорвано предметом: "Планирование АФАНАСЬЕВА эксперимента ... О.В."
        lesson = parse_lesson(
            ["лек.,", "пр.", "Планирование", "АФАНАСЬЕВА", "вирт.", "ауд.", "3",
             "эксперимента", "в", "исследовании", "О.В.", "https://my.mts-",
             "техпроцесса", "с", "04.09", "по", "06.11",
             "link.ru/j/127681561/vk3"])
        self.assertEqual(lesson["teacher"], "АФАНАСЬЕВА О.В.")
        self.assertEqual(lesson["subject"],
                         "Планирование эксперимента в исследовании техпроцесса")
        self.assertEqual(lesson["room"], "вирт. ауд. 3")
        self.assertEqual(lesson["link"], "https://my.mts-link.ru/j/127681561/vk3")

    def test_teacher_initials_first(self):
        lesson = parse_lesson(
            ["лаб.", "Физика", "211/305", "В.Ю.", "с", "24.11", "по", "15.12",
             "НИКИФОРОВ"])
        self.assertEqual(lesson["teacher"], "НИКИФОРОВ В.Ю.")

    def test_pair_numbers_extended(self):
        self.assertEqual(PAIR_NUMBERS["17.35-19.10"], 6)
        self.assertEqual(PAIR_NUMBERS["19.20-20.55"], 7)
        self.assertEqual(PAIR_NUMBERS["12.00-13.35"], 3)


if __name__ == "__main__":
    unittest.main()
