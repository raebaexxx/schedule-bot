"""Тесты интеграции Mini App (web_app-кнопка)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import handlers  # noqa: E402


class TestWebAppButton(unittest.TestCase):
    def test_no_webapp_without_url(self):
        old = handlers.WEBAPP_URL
        try:
            handlers.WEBAPP_URL = ""
            kb = handlers.main_menu_keyboard()
            for row in kb.inline_keyboard:
                for btn in row:
                    self.assertIsNone(btn.web_app)
        finally:
            handlers.WEBAPP_URL = old

    def test_webapp_button_with_url(self):
        old = handlers.WEBAPP_URL
        try:
            handlers.WEBAPP_URL = "https://app.raebae.fun"
            kb = handlers.main_menu_keyboard()
            webapps = [b for row in kb.inline_keyboard for b in row if b.web_app]
            self.assertEqual(len(webapps), 1)
            self.assertEqual(webapps[0].web_app.url, "https://app.raebae.fun")
            self.assertEqual(webapps[0].text, " Открыть приложение")
        finally:
            handlers.WEBAPP_URL = old


if __name__ == "__main__":
    unittest.main()
