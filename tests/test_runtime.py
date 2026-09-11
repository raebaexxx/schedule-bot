"""Тесты рантайм-фиксов бота: учебный год для /date, профиль в storage."""

import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from formatter import now  # noqa: E402
from handlers_all import _date_year  # noqa: E402
from storage import SelectionStorage  # noqa: E402


class TestDateYear(unittest.TestCase):
    """Год для /date выводится от текущего учебного года, без хардкода."""

    def test_academic_year_mapping(self):
        today = now().date()
        # учебный год начинается в августе
        start_year = today.year if today.month >= 8 else today.year - 1
        self.assertEqual(_date_year(9), start_year)   # сентябрь
        self.assertEqual(_date_year(12), start_year)  # декабрь
        self.assertEqual(_date_year(7), start_year)   # июль
        self.assertEqual(_date_year(2), start_year + 1)  # февраль
        self.assertEqual(_date_year(5), start_year + 1)  # май


class TestProfilePersistence(unittest.TestCase):
    """Обновлённый профиль пользователя реально сохраняется на диск."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = SelectionStorage(Path(self.tmp.name) / "users.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_name_update_persisted(self):
        self.storage.get_or_create(1, first_name="Старое")
        # новый /start с другим именем
        self.storage.get_or_create(1, first_name="Новое")
        # новый экземпляр storage — чтение с диска
        fresh = SelectionStorage(Path(self.tmp.name) / "users.json")
        self.assertEqual(fresh.get(1)["first_name"], "Новое")

    def test_username_update_persisted(self):
        self.storage.get_or_create(2, first_name="Вася", username="old")
        self.storage.get_or_create(2, first_name="Вася", username="new")
        fresh = SelectionStorage(Path(self.tmp.name) / "users.json")
        self.assertEqual(fresh.get(2)["username"], "new")

    def test_missing_fields_backfilled(self):
        # юзер старой схемы без digest-полей
        self.storage.set_group(3, "4", "БА-231")
        self.storage.get_or_create(3, first_name="Аня")
        fresh = SelectionStorage(Path(self.tmp.name) / "users.json")
        u = fresh.get(3)
        self.assertIn("time", u)
        self.assertIn("digest_enabled", u)


if __name__ == "__main__":
    unittest.main()
