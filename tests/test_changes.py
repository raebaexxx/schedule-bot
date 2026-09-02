"""Тесты вычисления и форматирования изменений расписания."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from changes import (  # noqa: E402
    compute_changes, format_group_changes, save_pending, load_pending,
    clear_pending,
)


def lesson(kind="лек.", subject="Физика", teacher="ИВАНОВ И.И.",
           room="310", ranges=(("2026-09-07", "2026-12-07"),),
           exact=(), link=None):
    return {"kind": kind, "subject": subject, "teacher": teacher,
            "room": room,
            "ranges": [list(r) for r in ranges],
            "exact_dates": list(exact), "link": link}


def schedule(cells):
    """cells: {(course, gid, day, time): [lesson]}"""
    courses = {}
    for (course, gid, day, time), lessons in cells.items():
        grp = courses.setdefault(course, {"semester": "", "groups": {}}) \
            ["groups"].setdefault(gid, {"display": gid, "days": {}})
        slots = grp["days"].setdefault(day, {"name": "", "slots": []})["slots"]
        slot = next((s for s in slots if s["time"] == time), None)
        if slot is None:
            slot = {"time": time, "pair": 1, "lessons": []}
            slots.append(slot)
        slot["lessons"].extend(lessons)
    return {"courses": courses}


class TestComputeChanges(unittest.TestCase):
    def test_no_changes(self):
        cells = {("4", "БА-231", "monday", "08:30-10:05"): [lesson()]}
        old, new = schedule(cells), schedule(cells)
        self.assertEqual(compute_changes(old, new), {})

    def test_added_lesson(self):
        old_cells = {("4", "БА-231", "monday", "08:30-10:05"): [lesson()]}
        new_cells = dict(old_cells)
        new_cells[("4", "БА-231", "monday", "10:15-11:50")] = [
            lesson(kind="пр.", subject="Химия", teacher="ПЕТРОВ П.П.",
                   room="305", ranges=(("2026-09-08", "2026-12-08"),))]
        changes = compute_changes(schedule(old_cells), schedule(new_cells))
        self.assertIn("4:БА-231", changes)
        joined = "\n".join(changes["4:БА-231"])
        self.assertIn("ПН 10:15-11:50: +", joined)
        self.assertIn("Химия", joined)

    def test_removed_lesson(self):
        old_cells = {("4", "БА-231", "monday", "08:30-10:05"): [
            lesson(), lesson(kind="пр.", subject="Химия", teacher="П.П.П.",
                             room="1", ranges=(("2026-09-07", "2026-09-08"),))]}
        new_cells = {("4", "БА-231", "monday", "08:30-10:05"): [lesson()]}
        changes = compute_changes(schedule(old_cells), schedule(new_cells))
        joined = "\n".join(changes["4:БА-231"])
        self.assertIn("− пр. Химия", joined)

    def test_changed_teacher(self):
        old_cells = {("1", "БК-261", "monday", "08:30-10:05"): [
            lesson(teacher="ИВАНОВ И.И.")]}
        new_cells = {("1", "БК-261", "monday", "08:30-10:05"): [
            lesson(teacher="ПЕТРОВ П.П.")]}
        changes = compute_changes(schedule(old_cells), schedule(new_cells))
        joined = "\n".join(changes["1:БК-261"])
        self.assertIn("−", joined)
        self.assertIn("+", joined)
        self.assertIn("ПЕТРОВ П.П.", joined)

    def test_new_group(self):
        changes = compute_changes(schedule({}), schedule(
            {("1", "БК-261", "monday", "08:30-10:05"): [lesson()]}))
        self.assertIn("1:БК-261", changes)

    def test_removed_group(self):
        changes = compute_changes(
            schedule({("1", "БК-261", "monday", "08:30-10:05"): [lesson()]}),
            schedule({}))
        self.assertIn("1:БК-261", changes)


class TestPending(unittest.TestCase):
    def setUp(self):
        import tempfile
        import changes as ch
        self.tmp = tempfile.TemporaryDirectory()
        from pathlib import Path
        self.old_path = ch.PENDING_FILE
        ch.PENDING_FILE = Path(self.tmp.name) / "pending.json"

    def tearDown(self):
        import changes as ch
        ch.PENDING_FILE = self.old_path
        self.tmp.cleanup()

    def test_save_load_clear(self):
        self.assertFalse(save_pending({}))
        self.assertIsNone(load_pending())
        save_pending({"4:БА-231": ["ПН 08:30: + пр. Химия"]})
        pending = load_pending()
        self.assertEqual(pending["changes"]["4:БА-231"],
                         ["ПН 08:30: + пр. Химия"])
        clear_pending()
        self.assertIsNone(load_pending())


class TestFormat(unittest.TestCase):
    def test_format_escapes(self):
        text = format_group_changes("4:БА-231", ["ПН 08:30: + <b>Химия</b>"],
                                    "БА-231")
        self.assertIn("<b>Обновление расписания</b>", text)
        self.assertIn("БА-231", text)
        self.assertNotIn("+ <b>Химия</b>", text)  # экранировано
        self.assertIn("&lt;b&gt;", text)

    def test_limit(self):
        lines = [f"ПН {i}: + пара {i}" for i in range(50)]
        text = format_group_changes("4:БА-231", lines, "БА-231", limit=40)
        self.assertIn("ещё 10", text)
        self.assertNotIn("ПН 49:", text)


if __name__ == "__main__":
    unittest.main()
