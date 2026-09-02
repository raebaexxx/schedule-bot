"""Тесты дайджеста общего бота (scheduler) и storage-полей дайджеста."""

import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiogram.exceptions import TelegramForbiddenError  # noqa: E402
from scheduler import DigestScheduler, should_send  # noqa: E402
from storage import SelectionStorage  # noqa: E402

MSK = timezone(timedelta(hours=3))


def msk(h: int, m: int, d: date = date(2026, 9, 7)) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=MSK)


class TestStorageDigest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = SelectionStorage(Path(self.tmp.name) / "users.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_user(self):
        user = self.storage.get_or_create(42)
        self.assertEqual(user["time"], "07:00")
        self.assertTrue(user["digest_enabled"])
        self.assertIsNone(user["last_sent"])

    def test_set_group_keeps_digest_fields(self):
        self.storage.get_or_create(1)
        self.storage.set_group(1, "4", "БА-231")
        user = self.storage.get(1)
        self.assertEqual(user["group"], "БА-231")
        self.assertEqual(user["time"], "07:00")

    def test_digest_time_and_enabled(self):
        self.storage.set_digest_time(5, "08:30")
        self.storage.set_digest_enabled(5, False)
        user = self.storage.get(5)
        self.assertEqual(user["time"], "08:30")
        self.assertFalse(user["digest_enabled"])
        self.assertIn("5", self.storage.all_chat_ids())
        self.assertEqual(self.storage.digest_users(), {})

    def test_mark_sent(self):
        self.storage.get_or_create(7)
        self.storage.mark_sent(7, "2026-09-07")
        self.assertEqual(self.storage.get(7)["last_sent"], "2026-09-07")


class TestShouldSend(unittest.TestCase):
    USER = {"time": "07:00", "digest_enabled": True, "last_sent": None}

    def test_time_not_reached(self):
        self.assertFalse(should_send(msk(6, 59), self.USER))

    def test_time_reached(self):
        self.assertTrue(should_send(msk(7, 0), self.USER))
        self.assertTrue(should_send(msk(9, 30), self.USER))

    def test_already_sent_today(self):
        user = dict(self.USER, last_sent="2026-09-07")
        self.assertFalse(should_send(msk(8, 0), user))
        self.assertTrue(should_send(msk(8, 0, date(2026, 9, 8)), user))

    def test_disabled_or_bad_time(self):
        self.assertFalse(should_send(msk(7, 0), dict(self.USER, digest_enabled=False)))
        self.assertFalse(should_send(msk(7, 0), dict(self.USER, time="7 утра")))

    def test_custom_time(self):
        user = dict(self.USER, time="08:30")
        self.assertFalse(should_send(msk(8, 0), user))
        self.assertTrue(should_send(msk(8, 30), user))


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class ForbiddenBot(FakeBot):
    async def send_message(self, chat_id, text):
        raise TelegramForbiddenError(method=None, message="blocked")


class TestSchedulerTick(unittest.IsolatedAsyncioTestCase):
    def _make(self, **user_over):
        tmp = tempfile.TemporaryDirectory()
        st = SelectionStorage(Path(tmp.name) / "users.json")
        st.get_or_create(100)
        st.set_group(100, "4", "БА-231")
        st.set_digest_time(100, "00:00")  # время давно прошло — догон
        return tmp, st

    async def test_tick_no_group_silent_mark(self):
        tmp = tempfile.TemporaryDirectory()
        st = SelectionStorage(Path(tmp.name) / "users.json")
        st.get_or_create(100)
        st.set_digest_time(100, "00:00")
        bot = FakeBot()
        sched = DigestScheduler(bot, st)
        await sched.tick()
        self.assertEqual(bot.sent, [])
        self.assertEqual(st.get(100)["last_sent"],
                         datetime.now(MSK).date().isoformat())
        tmp.cleanup()

    async def test_tick_sends_and_marks(self):
        tmp, st = self._make()
        bot = FakeBot()
        sched = DigestScheduler(bot, st)
        with unittest.mock.patch("scheduler.digest_text",
                                 return_value="<b>Доброе утро!</b>"):
            await sched.tick()
        self.assertEqual(len(bot.sent), 1)
        self.assertEqual(st.get(100)["last_sent"],
                         datetime.now(MSK).date().isoformat())
        with unittest.mock.patch("scheduler.digest_text",
                                 return_value="<b>Доброе утро!</b>"):
            await sched.tick()
        self.assertEqual(len(bot.sent), 1, "анти-дубль по дате")
        tmp.cleanup()

    async def test_tick_empty_day_marks(self):
        tmp, st = self._make()
        bot = FakeBot()
        sched = DigestScheduler(bot, st)
        with unittest.mock.patch("scheduler.digest_text", return_value=None), \
                unittest.mock.patch("scheduler.now",
                                    return_value=msk(10, 0, date(2026, 9, 13))):
            await sched.tick()
        self.assertEqual(bot.sent, [])
        self.assertEqual(st.get(100)["last_sent"], "2026-09-13")
        tmp.cleanup()

    async def test_forbidden_disables_digest(self):
        tmp, st = self._make()
        sched = DigestScheduler(ForbiddenBot(), st)
        with unittest.mock.patch("scheduler.digest_text",
                                 return_value="<b>Доброе утро!</b>"):
            await sched.tick()
        self.assertFalse(st.get(100)["digest_enabled"])
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
