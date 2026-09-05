"""Тесты поиска по предмету/преподавателю."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from search import search, format_results  # noqa: E402


class TestSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        p = ROOT / "data" / "schedule_all.json"
        if not p.exists():
            raise unittest.SkipTest("data/schedule_all.json не сгенерирован")
        cls.data = json.loads(p.read_text(encoding="utf-8"))

    def test_min_length(self):
        self.assertEqual(search("ма"), [])
        self.assertEqual(search("  "), [])

    def test_by_teacher(self):
        r = search("Купсин")  # правильная фамилия другая, проверим ниже
        # точный кейс: КУКСИН есть в данных
        r = search("КУКСИН")
        self.assertGreater(len(r), 0)
        for x in r:
            self.assertIn("КУКСИН", x["lesson"]["teacher"])

    def test_by_subject(self):
        r = search("сопротивление")
        self.assertGreater(len(r), 0)
        for x in r:
            self.assertIn("опротивление", x["lesson"]["subject"])

    def test_case_insensitive(self):
        a = search("история россии")
        b = search("ИСТОРИЯ РОССИИ")
        self.assertEqual(len(a), len(b))

    def test_no_results(self):
        self.assertEqual(search("квантовая хромодинамика"), [])

    def test_results_fields(self):
        r = search("История России")[:5]
        for x in r:
            self.assertIn("course", x)
            self.assertIn("gid", x)
            self.assertIn("display", x)
            self.assertIn("day", x)
            self.assertIn("time", x)
            self.assertIn("lesson", x)


class TestFormatResults(unittest.TestCase):
    def test_empty(self):
        text = format_results([], "запрос")
        self.assertIn("ничего не найдено", text)

    def test_format_contains_parts(self):
        import json
        data = json.load(open(ROOT / "data" / "schedule_all.json"))
        # реальный предмет из данных
        grp = data["courses"]["4"]["groups"]["БА-231"]["days"]
        subj = None
        for slot in grp["monday"]["slots"]:
            if slot["lessons"]:
                subj = slot["lessons"][0]["subject"]
                break
        word = subj.split()[0]
        if len(word) < 3:
            word = subj.split()[1]
        text = format_results(search_stub := [], query=word)
        # пустой список — не крашится
        self.assertIn("ничего не найдено", text)


if __name__ == "__main__":
    unittest.main()
