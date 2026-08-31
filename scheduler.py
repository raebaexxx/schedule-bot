"""Планировщик утреннего дайджеста: asyncio-задача внутри процесса бота."""

import asyncio
import logging
from datetime import date, datetime

from aiogram import Bot

from formatter import digest_text, now
from storage import Storage

logger = logging.getLogger("bot.scheduler")

TIME_FMT = "%H:%M"


def should_send(moscow_now: datetime, user: dict) -> bool:
    """Пора ли слать дайджест этому пользователю прямо сейчас."""
    if not user.get("enabled", False):
        return False
    try:
        target = datetime.strptime(user.get("time", "07:00"), TIME_FMT).time()
    except ValueError:
        return False
    if moscow_now.time() < target:
        return False
    return moscow_now.date().isoformat() != user.get("last_sent")


class Scheduler:
    def __init__(self, bot: Bot, storage: Storage, interval: int = 30) -> None:
        self.bot = bot
        self.storage = storage
        self.interval = interval
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - задача не должна умирать
                logger.exception("ошибка в цикле планировщика")
            await asyncio.sleep(self.interval)

    async def tick(self) -> None:
        """Один проход: отправить дайджест тем, кому пора."""
        moscow_now = now()
        today = moscow_now.date()
        for chat_id, user in self.storage.enabled_users().items():
            if not should_send(moscow_now, user):
                continue
            ok = await self.send_digest(int(chat_id), today)
            if ok:
                self.storage.mark_sent(chat_id, today.isoformat())
            else:
                logger.warning("дайджест для %s не отправлен", chat_id)

    async def send_digest(self, chat_id: int, d: date) -> bool:
        """Отправляет дайджест. False — пользователь заблокировал бота."""
        text = digest_text(d)
        if text is None:
            return True  # пар нет — «молчим», но день отмечаем, чтобы не пересылать
        try:
            await self.bot.send_message(chat_id, text)
            return True
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__
            logger.warning("не удалось отправить дайджест %s: %s: %s",
                           chat_id, name, e)
            if name in ("TelegramForbiddenError", "TelegramUnauthorizedError"):
                self.storage.set_enabled(chat_id, False)
                logger.info("подписка %s отключена (бот заблокирован)", chat_id)
            return False
