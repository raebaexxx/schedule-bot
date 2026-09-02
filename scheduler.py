"""Планировщик утреннего дайджеста (общий бот): по группе юзера из schedule_all."""

import asyncio
import logging

from aiogram import Bot

from formatter import digest_text, now
from schedule_all import group_days
from storage import SelectionStorage

logger = logging.getLogger("bot_all.scheduler")

TIME_FMT = "%H:%M"


def should_send(moscow_now, user: dict) -> bool:
    """Пора ли слать дайджест этому пользователю прямо сейчас."""
    if not user.get("digest_enabled", False):
        return False
    try:
        target = __import__("datetime").datetime.strptime(
            user.get("time", "07:00"), TIME_FMT).time()
    except ValueError:
        return False
    if moscow_now.time() < target:
        return False
    return moscow_now.date().isoformat() != user.get("last_sent")


class DigestScheduler:
    def __init__(self, bot: Bot, storage: SelectionStorage, interval: int = 30) -> None:
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
            except Exception:  # noqa: BLE001
                logger.exception("ошибка в цикле планировщика")
            await asyncio.sleep(self.interval)

    async def tick(self) -> None:
        """Один проход: отправить дайджест тем, кому пора."""
        from datetime import datetime
        moscow_now = now()
        today = moscow_now.date()
        for chat_id, user in self.storage.digest_users().items():
            if not should_send(moscow_now, user):
                continue
            ok = await self.send_digest(int(chat_id), today)
            if ok:
                self.storage.mark_sent(chat_id, today.isoformat())
            else:
                logger.warning("дайджест для %s не отправлен", chat_id)

    async def send_digest(self, chat_id: int, d) -> bool:
        """Отправляет дайджест. False — пользователь заблокировал бота."""
        from datetime import date as _date
        sel = self.storage.get(chat_id)
        course, gid = sel.get("course"), sel.get("group")
        if not course or not gid:
            return True  # группу ещё не выбрал — молчим, но день отмечаем
        try:
            days = group_days(course, gid)
        except KeyError:
            return True
        text = digest_text(days, d if isinstance(d, _date) else _date.fromisoformat(d))
        if text is None:
            return True  # пар нет — молчим, но день отмечаем
        try:
            await self.bot.send_message(chat_id, text)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("дайджест %s не доставлен: %s: %s",
                           chat_id, type(e).__name__, e)
            if type(e).__name__ in ("TelegramForbiddenError",
                                    "TelegramUnauthorizedError"):
                self.storage.set_digest_enabled(chat_id, False)
                logger.info("дайджест %s отключён (бот заблокирован)", chat_id)
            return False
