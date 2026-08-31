"""Тесты хранилища подписок, дайджеста и логики планировщика."""

import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datetime import timezone, timedelta  # noqa: E402

from aiogram.exceptions import TelegramForbiddenError  # noqa: E402
from formatter import digest_text, plural_pairs  # noqa: E402
from scheduler import Scheduler, should_send  # noqa: E402
from storage import Storage  # noqa: E402

MSK = timezone(timedelta(hours=3))


def msk(h: int, m: int, d: date = date(2026, 9, 7)) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=MSK)


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "users.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_user(self):
        user = self.storage.get_or_create(42)
        self.assertEqual(user["time"], "07:00")
        self.assertTrue(user["enabled"])
        self.assertIsNone(user["last_sent"])

    def test_persistence(self):
        self.storage.set_time(42, "08:15")
        self.storage.set_enabled(42, False)
        other = Storage(Path(self.tmp.name) / "users.json")
        user = other.get_or_create(42)
        self.assertEqual(user["time"], "08:15")
        self.assertFalse(user["enabled"])

    def test_enabled_users_filtering(self):
        self.storage.get_or_create(1)
        self.storage.get_or_create(2)
        self.storage.set_enabled(2, False)
        enabled = self.storage.enabled_users()
        self.assertIn("1", enabled)
        self.assertNotIn("2", enabled)

    def test_mark_sent(self):
        self.storage.get_or_create(7)
        self.storage.mark_sent(7, "2026-09-07")
        self.assertEqual(self.storage.get_or_create(7)["last_sent"], "2026-09-07")

    def test_remove(self):
        self.storage.get_or_create(5)
        self.storage.remove(5)
        self.assertEqual(self.storage.enabled_users(), {})


class TestShouldSend(unittest.TestCase):
    USER = {"time": "07:00", "enabled": True, "last_sent": None}

    def test_time_not_reached(self):
        self.assertFalse(should_send(msk(6, 59), self.USER))

    def test_time_reached(self):
        self.assertTrue(should_send(msk(7, 0), self.USER))
        self.assertTrue(should_send(msk(7, 30), self.USER))

    def test_already_sent_today(self):
        user = dict(self.USER, last_sent="2026-09-07")
        self.assertFalse(should_send(msk(8, 0), user))
        self.assertTrue(should_send(msk(8, 0, date(2026, 9, 8)), user))

    def test_disabled(self):
        self.assertFalse(should_send(msk(7, 0), dict(self.USER, enabled=False)))

    def test_bad_time_format(self):
        self.assertFalse(should_send(msk(7, 0), dict(self.USER, time="7 утра")))

    def test_custom_time(self):
        user = dict(self.USER, time="08:30")
        self.assertFalse(should_send(msk(8, 0), user))
        self.assertTrue(should_send(msk(8, 30), user))


class TestDigestText(unittest.TestCase):
    def test_day_with_lessons(self):
        text = digest_text(date(2026, 9, 7))  # понедельник с парами
        self.assertIn("Доброе утро!", text)
        self.assertIn("Понедельник, 07.09", text)
        self.assertIn("08:30-10:05", text)

    def test_sunday_none(self):
        self.assertIsNone(digest_text(date(2026, 9, 13)))

    def test_outside_semester_none(self):
        self.assertIsNone(digest_text(date(2026, 12, 29)))

    def test_plural_pairs(self):
        self.assertEqual(plural_pairs(1), "1 пара")
        self.assertEqual(plural_pairs(3), "3 пары")
        self.assertEqual(plural_pairs(6), "6 пар")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class ForbiddenBot(FakeBot):
    async def send_message(self, chat_id, text):
        raise TelegramForbiddenError(method=None, message="blocked")


from scheduler import Scheduler  # noqa: E402


class TestSchedulerTick(unittest.IsolatedAsyncioTestCase):
    async def test_tick_sends_and_marks(self):
        tmp = tempfile.TemporaryDirectory()
        st = Storage(Path(tmp.name) / "users.json")
        st.get_or_create(100)
        bot = FakeBot()
        sched = Scheduler(bot, st)
        await sched.tick()
        self.assertEqual(len(bot.sent), 0, "07:00 ещё не наступило — молчим")

    async def test_tick_sends_after_target_time(self):
        tmp = tempfile.TemporaryDirectory()
        st = Storage(Path(tmp.name) / "users.json")
        st.get_or_create(100)
        st.set_time(100, "00:00")  # время давно прошло — догон при старте
        bot = FakeBot()
        sched = Scheduler(bot, st)
        # подменяем дайджест: «сегодня» в тесте может оказаться днём без пар
        with unittest.mock.patch("scheduler.digest_text",
                                 return_value="<b>Доброе утро!</b>"):
            await sched.tick()
        self.assertEqual(len(bot.sent), 1)
        self.assertEqual(st.get_or_create(100)["last_sent"],
                         datetime.now(MSK).date().isoformat())
        # повторный tick не дублирует
        with unittest.mock.patch("scheduler.digest_text",
                                 return_value="<b>Доброе утро!</b>"):
            await sched.tick()
        self.assertEqual(len(bot.sent), 1)
        tmp.cleanup()

    async def test_tick_skips_empty_day(self):
        tmp = tempfile.TemporaryDirectory()
        st = Storage(Path(tmp.name) / "users.json")
        st.get_or_create(100)
        st.set_time(100, "00:00")
        bot = FakeBot()
        sched = Scheduler(bot, st)
        # воскресенье: digest_text -> None; send не вызывается, но день отмечается
        with unittest.mock.patch("scheduler.digest_text", return_value=None), \
                unittest.mock.patch("scheduler.now",
                                    return_value=msk(10, 0, date(2026, 9, 13))):
            await sched.tick()
        self.assertEqual(bot.sent, [])
        self.assertEqual(st.get_or_create(100)["last_sent"], "2026-09-13")
        tmp.cleanup()

    async def test_forbidden_disables_user(self):
        tmp = tempfile.TemporaryDirectory()
        st = Storage(Path(tmp.name) / "users.json")
        st.get_or_create(100)
        st.set_time(100, "00:00")
        with unittest.mock.patch("scheduler.digest_text",
                                 return_value="<b>Доброе утро!</b>"):
            sched = Scheduler(ForbiddenBot(), st)
            await sched.tick()
        self.assertFalse(st.get_or_create(100)["enabled"])
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
