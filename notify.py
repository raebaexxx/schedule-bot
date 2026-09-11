"""Рассылка уведомлений об изменениях расписания (общий бот)."""

import asyncio
import html
import logging

from aiogram import Bot

from changes import clear_pending, format_group_changes, load_pending
from formatter import split_message
from schedule_all import group_display
from storage import SelectionStorage

logger = logging.getLogger("bot_all.changes")


async def notify_changes(bot: Bot, storage: SelectionStorage) -> int:
    """Отправляет ожидающие уведомления. Возвращает число доставленных."""
    pending = load_pending()
    if not pending:
        return 0
    changes = pending.get("changes", {})
    if not changes:
        clear_pending()
        return 0
    delivered = 0
    for chat_id in storage.all_chat_ids():
        sel = storage.get(chat_id)
        course, gid = sel.get("course"), sel.get("group")
        if not course or not gid:
            continue
        gkey = f"{course}:{gid}"
        lines = changes.get(gkey)
        if not lines:
            continue
        try:
            display = group_display(course, gid)
        except KeyError:
            continue
        text = format_group_changes(gkey, lines, display)
        try:
            for chunk in split_message(text):
                await bot.send_message(int(chat_id), chunk)
                await asyncio.sleep(0.05)
            delivered += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("уведомление %s не доставлено: %s: %s",
                           chat_id, type(e).__name__, e)
    clear_pending()
    logger.info("уведомления об изменениях отправлены: %s", delivered)
    return delivered
