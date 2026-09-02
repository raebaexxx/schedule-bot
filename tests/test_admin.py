"""Тесты админ-гварда и хелперов админки."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import handlers_admin as ha  # noqa: E402
from config import ADMIN_IDS  # noqa: E402


class _User:
    def __init__(self, uid):
        self.id = uid


class _Msg:
    def __init__(self, uid):
        self.from_user = _User(uid)

    async def answer(self, *a, **k):
        self.answered = (a, k)


class TestAdminGuard(unittest.IsolatedAsyncioTestCase):
    async def test_admin_passes(self):
        calls = []

        @ha.admin_guard
        async def handler(message):
            calls.append(message)

        m = _Msg(next(iter(ADMIN_IDS)))
        await handler(m)
        self.assertEqual(len(calls), 1)

    async def test_non_admin_rejected(self):
        calls = []

        @ha.admin_guard
        async def handler(message):
            calls.append(message)

        m = _Msg(12345)
        await handler(m)
        self.assertEqual(calls, [])
        self.assertTrue(hasattr(m, "answered"))


class TestAdminHelpers(unittest.TestCase):
    def test_uptime_nonnegative(self):
        self.assertGreater(ha.uptime_seconds(), 0)

    def test_parse_summary_filters(self):
        out = "мусорная строка\nЗанятий: 639\n  все занятия подтверждены\n" \
              "  [B] что-то\nоткрытие: 2026-09-02"
        s = ha._parse_summary(out)
        self.assertIn("Занятий: 639", s)
        self.assertIn("подтверждены", s)
        self.assertNotIn("мусорная", s)

    def test_status_contains_version(self):
        import tempfile
        from storage import SelectionStorage
        tmp = tempfile.TemporaryDirectory()
        st = SelectionStorage(Path(tmp.name) / "u.json")
        text = ha._status_text(st)
        self.assertIn("Версия бота", text)
        self.assertIn("Uptime", text)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
