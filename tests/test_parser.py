"""Тесты парсера: разбор занятий из токенов + регрессия по реальному PDF."""

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import parse_pdf as pp  # noqa: E402


class TestParseLesson(unittest.TestCase):
    def test_range_simple(self):
        lesson = pp.parse_lesson(
            ["лек.", "САПР", "технологических", "процессов", "с", "04.09",
             "по", "25.09", "ЧОРИЕВА", "А.А.", "304"])
        self.assertEqual(lesson["kind"], "лек.")
        self.assertEqual(lesson["subject"], "САПР технологических процессов")
        self.assertEqual(lesson["teacher"], "ЧОРИЕВА А.А.")
        self.assertEqual(lesson["room"], "304")
        self.assertEqual(lesson["ranges"], [["2026-09-04", "2026-09-25"]])
        self.assertEqual(lesson["exact_dates"], [])

    def test_range_with_teacher_between(self):
        # 'с' и даты разнесены переносом, ФИО и аудитория между ними
        lesson = pp.parse_lesson(
            ["лек.,", "пр.", "Технологические", "процессы", "автоматизированных",
             "производств", "с", "МАХОВ", "М.А.", "111", "07.09", "по", "09.11"])
        self.assertEqual(lesson["kind"], "лек., пр.")
        self.assertEqual(lesson["subject"],
                         "Технологические процессы автоматизированных производств")
        self.assertEqual(lesson["teacher"], "МАХОВ М.А.")
        self.assertEqual(lesson["room"], "111")
        self.assertEqual(lesson["ranges"], [["2026-09-07", "2026-11-09"]])

    def test_single_date(self):
        lesson = pp.parse_lesson(
            ["лек.,", "пр.", "Технологическая", "информатика",
             "автоматизированного", "производства", "МАХОВ", "А.А.", "111",
             "16.11"])
        self.assertEqual(lesson["exact_dates"], ["2026-11-16"])
        self.assertEqual(lesson["ranges"], [])

    def test_two_dates(self):
        lesson = pp.parse_lesson(
            ["лаб.", "Технологическая", "информатика", "автоматизированного",
             "производства", "МАХОВ", "А.А.", "305", "30.11", "и", "07.12"])
        self.assertEqual(lesson["exact_dates"], ["2026-11-30", "2026-12-07"])

    def test_dates_first(self):
        # даты идут до ФИО (порядок токенов не важен)
        lesson = pp.parse_lesson(
            ["лаб.", "Моделирование", "систем", "с", "14.10", "по", "11.11",
             "КОРНЕЕВ", "П.Е.", "305"])
        self.assertEqual(lesson["ranges"], [["2026-10-14", "2026-11-11"]])
        self.assertEqual(lesson["teacher"], "КОРНЕЕВ П.Е.")
        self.assertEqual(lesson["room"], "305")

    def test_two_rooms(self):
        lesson = pp.parse_lesson(
            ["лек.", "Электропривод", "с", "12.11", "по", "26.11",
             "МАХОВ", "А.А.", "310\\111"])
        self.assertEqual(lesson["room"], "310\\111")

    def test_virtual_room_and_link(self):
        lesson = pp.parse_lesson(
            ["пр.", "Технологии", "индустрии", "4.0", "АФАНАСЬЕВА", "О.В.",
             "вирт.", "ауд.", "3", "https://my.mts-", "link.ru/j/127681561/vk3",
             "с", "12.09", "по", "28.11"])
        self.assertEqual(lesson["room"], "вирт. ауд. 3")
        self.assertEqual(lesson["link"], "https://my.mts-link.ru/j/127681561/vk3")
        self.assertIn("4.0", lesson["subject"])

    def test_project_kind(self):
        lesson = pp.parse_lesson(
            ["Проект", "по", '"Технологические', "процессы",
             "автоматизированных", "МАХОВ", "М.А.", "310",
             'производств"', "с", "07.09", "по", "05.10"])
        self.assertEqual(lesson["kind"], "Проект")
        self.assertEqual(lesson["ranges"], [["2026-09-07", "2026-10-05"]])

    def test_empty_room_allowed(self):
        lesson = pp.parse_lesson(
            ["лек.,", "пр.", "Бережливое", "производство", "ЗАМЛЕЛАЯ", "А.Т.",
             "с", "01.09", "по", "15.09"])
        self.assertEqual(lesson["room"], "")
        self.assertEqual(lesson["teacher"], "ЗАМЛЕЛАЯ А.Т.")


class TestFullPipeline(unittest.TestCase):
    """Регрессия по реальным выгрузкам PDF из data/."""

    @classmethod
    def setUpClass(cls):
        bbox = (ROOT / "data" / "bbox.xml").read_text(encoding="utf-8")
        words = pp.parse_words(bbox)
        vlines = [l for l in pp.cluster_visual_lines(words) if l["y"] > 95]
        cls.day_anchors, time_anchors, content = pp.collect_inputs(vlines)
        sections = pp.build_day_sections(cls.day_anchors)
        rows = pp.assign_time_anchors(time_anchors, sections)
        slots = pp.assign_content(content, rows)
        cls.schedule = pp.collect(slots)

    def all_lessons(self):
        for day in pp.DAY_ORDER:
            for slot in self.schedule[day]["slots"]:
                for lesson in slot["lessons"]:
                    yield day, slot["time"], lesson

    def test_total_count(self):
        total = sum(len(s["lessons"]) for d in self.schedule.values()
                    for s in d["slots"])
        self.assertEqual(total, 43)

    def test_every_slot_grid(self):
        for day in pp.DAY_ORDER:
            times = [s["time"] for s in self.schedule[day]["slots"]]
            self.assertEqual(times,
                             [pp.normalize_time(t) for t in pp.EXPECTED_SLOTS[day]])

    def test_pair_numbers(self):
        thu = self.schedule["thursday"]["slots"]
        self.assertEqual([s["pair"] for s in thu], [1, 2, 3, 4, 5])

    def test_every_lesson_complete(self):
        for day, time, lesson in self.all_lessons():
            with self.subTest(day=day, time=time, subject=lesson["subject"][:30]):
                self.assertTrue(lesson["subject"])
                self.assertTrue(lesson["kind"])
                self.assertTrue(lesson["teacher"])
                self.assertTrue(lesson["ranges"] or lesson["exact_dates"])

    def test_dates_within_semester(self):
        lo, hi = pp.SEMESTER_START, pp.SEMESTER_END
        for day, time, lesson in self.all_lessons():
            ds = [x for r in lesson["ranges"] for x in r] + lesson["exact_dates"]
            for d in ds:
                self.assertTrue(lo <= date.fromisoformat(d) <= hi,
                                f"{day} {time}: дата {d} вне семестра")

    def test_saturday_empty(self):
        total = sum(len(s["lessons"]) for s in self.schedule["saturday"]["slots"])
        self.assertEqual(total, 0)

    def test_spot_checks(self):
        # ПН 08:30 — 4 занятия
        mon = {s["time"]: s["lessons"] for s in self.schedule["monday"]["slots"]}
        self.assertEqual(len(mon["08:30-10:05"]), 4)
        self.assertEqual(mon["08:30-10:05"][1]["exact_dates"], ["2026-11-16"])
        # ВТ 08:30 — Бережливое без аудитории (пустая ячейка в PDF)
        tue = {s["time"]: s["lessons"] for s in self.schedule["tuesday"]["slots"]}
        self.assertEqual(tue["08:30-10:05"][0]["room"], "")
        self.assertEqual(tue["08:30-10:05"][0]["ranges"],
                         [["2026-09-01", "2026-09-15"]])
        # ЧТ 12:20 — Диагностика СОППА + лаб. Электропривод
        thu = {s["time"]: s["lessons"] for s in self.schedule["thursday"]["slots"]}
        self.assertEqual(len(thu["12:20-13:55"]), 2)
        self.assertEqual(thu["12:20-13:55"][0]["teacher"], "СОППА И.В.")
        self.assertEqual(thu["12:20-13:55"][1]["room"], "310\\111")
        # ПТ 08:30 — лек. и лаб. САПР
        fri = {s["time"]: s["lessons"] for s in self.schedule["friday"]["slots"]}
        self.assertEqual(len(fri["08:30-10:05"]), 2)
        self.assertEqual(fri["08:30-10:05"][0]["teacher"], "ЧОРИЕВА А.А.")


if __name__ == "__main__":
    unittest.main()
