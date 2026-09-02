"""Админ-панель общего бота: /admin только для ADMIN_IDS."""

import asyncio
import html
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import ADMIN_IDS, BOT_VERSION
from formatter import now
from schedule_all import COURSE_IDS, COURSES
from storage import SelectionStorage

storage = SelectionStorage()

router = Router()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SCHEDULE_FILE = DATA_DIR / "schedule_all.json"
PENDING_FILE = DATA_DIR / "pending_changes.json"
PDF_DIR = DATA_DIR / "incoming_pdf"
PARSE_SCRIPT = ROOT / "scripts" / "parse_all.py"

DAY_RU = {"monday": "ПН", "tuesday": "ВТ", "wednesday": "СР",
          "thursday": "ЧТ", "friday": "ПТ", "saturday": "СБ"}


def is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


def admin_guard(func):
    """Гвард: не-админ получает отказ, callback просто закрывается.
    kwargs (dispatcher, state и т.п.) пробрасываются как есть."""
    async def wrapper(event, *args, **kwargs):
        user_id = getattr(event, "from_user", None)
        uid = user_id.id if user_id else None
        if not is_admin(uid):
            if isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=True)
            else:
                await event.answer("⛔ Нет доступа")
            return
        return await func(event, *args, **kwargs)
    return wrapper


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="📣 Рассылка", callback_data="adm:broadcast")],
        [InlineKeyboardButton(text="🖥 Статус", callback_data="adm:status")],
        [InlineKeyboardButton(text="📥 Обновить PDF", callback_data="adm:pdf")],
        [InlineKeyboardButton(text="Закрыть", callback_data="adm:close")],
    ])


# ---------------- /admin ----------------

@router.message(F.text == "/admin")
@admin_guard
async def cmd_admin(message: Message, **kwargs) -> None:
    await message.answer("<b>Админ-панель</b>", reply_markup=admin_menu())


@router.callback_query(F.data == "adm:close")
@admin_guard
async def cb_close(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except Exception:  # noqa: BLE001
        pass
    await callback.answer()


# ---------------- статистика ----------------

def _stats_text(storage: SelectionStorage) -> str:
    users = storage._load()
    total = len(users)
    by_course: dict[str, int] = {}
    by_group: dict[str, int] = {}
    no_group = 0
    digest_on = sum(1 for u in users.values() if u.get("digest_enabled"))
    for u in users.values():
        course, gid = u.get("course"), u.get("group")
        if course and gid:
            by_course[course] = by_course.get(course, 0) + 1
            display = COURSES.get(course, {}).get("groups", {}) \
                .get(gid, {}).get("display", gid)
            by_group[f"{display} (курс {course})"] = \
                by_group.get(f"{display} (курс {course})", 0) + 1
        else:
            no_group += 1

    lines = [f"<b>Статистика</b>",
             f"Всего юзеров: <b>{total}</b> (дайджест вкл: {digest_on})"]
    if by_course:
        max_c = max(by_course.values())
        for course in COURSE_IDS:
            n = by_course.get(course, 0)
            bar = "▓" * round(10 * n / max_c) if n else ""
            lines.append(f"  {course} курс: {n} {bar}")
    if no_group:
        lines.append(f"  без группы: {no_group}")
    lines.append("")
    for g in sorted(by_group, key=lambda g: -by_group[g]):
        lines.append(f"  {g}: {by_group[g]}")

    # детальный список юзеров
    lines.append("")
    lines.append(f"<b>Пользователи ({total})</b>")
    for cid, u in sorted(users.items(), key=lambda kv: (kv[1].get("course", "9"),
                                                        kv[1].get("group", ""))):
        name = u.get("first_name") or "—"
        uname = f"@{u['username']}" if u.get("username") else ""
        course, gid = u.get("course"), u.get("group")
        grp = ""
        if course and gid:
            disp = COURSES.get(course, {}).get("groups", {}) \
                .get(gid, {}).get("display", gid)
            grp = f" · {disp}"
        dg = f" · {u.get('time', '07:00')}" if u.get("digest_enabled") \
            else " · дайджест выкл"
        lines.append(f"  <code>{cid}</code> {html.escape(name)} "
                     f"{html.escape(uname)}{grp}{dg}")
    return "\n".join(lines)


@router.callback_query(F.data == "adm:stats")
@admin_guard
async def cb_stats(callback: CallbackQuery, **kwargs) -> None:
    try:
        await callback.message.edit_text(_stats_text(storage),
                                         reply_markup=admin_menu())
    except Exception:  # noqa: BLE001
        await callback.message.answer(_stats_text(storage),
                                      reply_markup=admin_menu())
    await callback.answer()


# ---------------- статус ----------------

def _schedule_status() -> str:
    try:
        data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "  schedule_all.json: не читается"
    lines = [f"  Обновлено: <b>{data.get('generated', '?')}</b>"]
    for course in COURSE_IDS:
        groups = data.get("courses", {}).get(course, {}).get("groups", {})
        n = sum(len(slot["lessons"]) for g in groups.values()
                for d in g["days"].values() for slot in d["slots"])
        lines.append(f"  {course} курс: {n} пар, {len(groups)} групп")
    return "\n".join(lines)


def _status_text(storage: SelectionStorage) -> str:
    proc = uptime_seconds()
    proc_s = f"{proc // 3600} ч {(proc % 3600) // 60} мин" if proc >= 0 else "?"
    pending = "есть (бот разошлёт при рестарте)" if PENDING_FILE.exists() else "нет"
    return ("<b>Статус</b>\n\n"
            f"Версия бота: <b>{BOT_VERSION}</b>\n"
            f"Uptime процесса: <b>{proc_s}</b>\n"
            f"Админов: {len(ADMIN_IDS)}\n\n"
            "<b>Расписание</b>\n" + _schedule_status() +
            f"\n\nОчередь изменений: {pending}")


def uptime_seconds() -> float:
    try:
        with open("/proc/self/stat", encoding="utf-8") as f:
            fields = f.read().split()
        ticks = float(fields[21])
        hz = 100
        boot = float(Path("/proc/stat").read_text().split("btime ")[1].split()[0])
        return time.time() - boot - ticks / hz
    except Exception:  # noqa: BLE001
        return -1


@router.callback_query(F.data == "adm:status")
@admin_guard
async def cb_status(callback: CallbackQuery, **kwargs) -> None:
    try:
        await callback.message.edit_text(_status_text(storage),
                                         reply_markup=admin_menu())
    except Exception:  # noqa: BLE001
        await callback.message.answer(_status_text(storage),
                                      reply_markup=admin_menu())
    await callback.answer()


# ---------------- рассылка ----------------

class BroadcastStates(StatesGroup):
    audience = State()
    text = State()
    confirm = State()


def audience_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Всем юзерам", callback_data="aud:all")]]
    rows.append([InlineKeyboardButton(text=f"Курс {c}", callback_data=f"aud:course:{c}")
                 for c in COURSE_IDS[:2]])
    rows.append([InlineKeyboardButton(text=f"Курс {c}", callback_data=f"aud:course:{c}")
                 for c in COURSE_IDS[2:]])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "adm:broadcast")
@admin_guard
async def cb_broadcast(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await state.set_state(BroadcastStates.audience)
    await callback.message.edit_text(
        "Кому отправить?", reply_markup=audience_keyboard())
    await callback.answer()


@router.callback_query(BroadcastStates.audience, F.data.startswith("aud:"))
@admin_guard
async def cb_audience(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    data = callback.data.split(":", 1)[1]
    if data == "all":
        audience = {"all": True}
    else:
        _, course = data.split(":", 1)
        audience = {"course": course}
    await state.update_data(audience=audience)
    await state.set_state(BroadcastStates.text)
    label = "всем юзерам" if "all" in audience else f"курс {audience['course']}"
    await callback.message.edit_text(
        f"Аудитория: <b>{label}</b>.\nПришли текст сообщения "
        "(HTML разрешён):", reply_markup=None)
    await callback.answer()


@router.message(BroadcastStates.text, F.text)
@admin_guard
async def msg_broadcast_text(message: Message, state: FSMContext, **kwargs) -> None:
    await state.update_data(text=message.text)
    await state.set_state(BroadcastStates.confirm)
    data = await state.get_data()
    aud = data["audience"]
    label = "всем юзерам" if aud.get("all") else f"курс {aud['course']}"
    preview = message.text[:500]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="aud:go"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")]])
    await message.answer(
        f"<b>Предпросмотр</b> (аудитория: {label})\n\n{preview}\n\nОтправлять?",
        reply_markup=kb)


@router.callback_query(BroadcastStates.confirm, F.data == "aud:go")
@admin_guard
async def cb_broadcast_go(callback: CallbackQuery, state: FSMContext,
                          **kwargs) -> None:
    bot = callback.bot
    data = await state.get_data()
    await state.clear()
    aud, text = data["audience"], data["text"]
    users = storage._load()
    targets = []
    for cid, u in users.items():
        if aud.get("all"):
            targets.append(cid)
        elif u.get("course") == aud.get("course"):
            targets.append(cid)
    ok = err = 0
    for cid in targets:
        try:
            await bot.send_message(int(cid), text)
            ok += 1
        except Exception:  # noqa: BLE001
            err += 1
    await callback.message.edit_text(
        f"Рассылка завершена: доставлено <b>{ok}</b>, ошибок {err}.",
        reply_markup=admin_menu())
    await callback.answer()


@router.callback_query(F.data == "adm:cancel")
@admin_guard
async def cb_cancel(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await state.clear()
    try:
        await callback.message.edit_text("Отменено.", reply_markup=admin_menu())
    except Exception:  # noqa: BLE001
        pass
    await callback.answer()


# ---------------- обновление PDF через бота ----------------

class PdfStates(StatesGroup):
    waiting_files = State()


@router.callback_query(F.data == "adm:pdf")
@admin_guard
async def cb_pdf(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await state.set_state(PdfStates.waiting_files)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="adm:cancel")]])
    await callback.message.edit_text(
        "Пришли PDF-файлы расписания (1–4 файла, по одному на курс).\n"
        "Файлы: <code>{N}curs{год}.pdf</code> — курс распознаётся из имени.\n"
        "После загрузки запущу парсер, обновлю JSON и разошлю изменения.",
        reply_markup=kb)
    await callback.answer()


@router.message(PdfStates.waiting_files, F.document)
@admin_guard
async def msg_pdf_files(message: Message, state: FSMContext,
                        **kwargs) -> None:
    bot = message.bot
    doc = message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".pdf"):
        await message.answer("Это не PDF. Присылай .pdf файлы.")
        return
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    target = PDF_DIR / doc.file_name
    await bot.download(doc, destination=target)
    await state.clear()

    status = await message.answer("⏳ Запускаю парсер…")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(PARSE_SCRIPT), str(PDF_DIR),
        cwd=str(ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
    except TimeoutError:
        proc.kill()
        await status.edit_text("❌ Парсер не уложился в 5 минут, убит.")
        return
    output = out.decode("utf-8", errors="replace")
    tail = "\n".join(output.strip().splitlines()[-25:])
    if proc.returncode != 0:
        await status.edit_text(
            f"❌ Парсер упал (код {proc.returncode}):\n"
            f"<pre>{html.escape(tail[-2000:])}</pre>")
        return
    summary = _parse_summary(output)
    # JSON уже перезаписан парсером; рассылаем изменения
    from notify import notify_changes
    sent = await notify_changes(bot, storage)
    await status.edit_text(
        f"✅ Расписание обновлено.\n{summary}\n"
        f"Уведомлений доставлено: {sent}.",
        reply_markup=admin_menu())


def _parse_summary(output: str) -> str:
    """Ключевые строки из вывода парсера: занятия, подтверждение, изменения."""
    keep = []
    for line in output.splitlines():
        if ("Занятий:" in line or "все занятия подтверждены" in line
                or "отклонений нет" in line or "Изменения:" in line
                or "Изменений нет" in line or "[B]" in line or "[S]" in line):
            keep.append(line.strip()[:120])
    if not keep:
        return ""
    shown = keep[:14]
    more = "" if len(keep) <= 14 else f"\n… и ещё {len(keep) - 14} строк"
    return "<pre>" + html.escape("\n".join(shown)) + "</pre>" + more


@router.message(PdfStates.waiting_files)
@admin_guard
async def msg_pdf_not_document(message: Message, **kwargs) -> None:
    await message.answer("Жду PDF-документы (или «Отмена» в меню выше).")
