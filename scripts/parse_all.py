#!/usr/bin/env python3
"""
Универсальный парсер расписаний ЕТИ МГТУ «СТАНКИН»: все курсы и все группы.

Вход: PDF-файлы вида {N}curs{год}.pdf (Excel-выгрузка, 1 страница, N колонок-групп).
Выход: data/schedule_all.json — {courses: {"1": {semester, groups: {...}}}}.

Алгоритм (развитие parse_pdf.py до мультиколоночного случая):
  1. pdftotext -bbox-layout -> слова -> кластеризация в визуальные строки.
  2. Строка подзаголовков ("Дисциплины/Преподаватели/Ауд.") даёт якоря колонок.
     Границы колонок: boundary_i = disc_{i+1}.x0 - indent, где indent —
     расстояние от «Дисциплин» колонки до первого слова контента колонки
     (у каждого PDF свой, определяется по факту).
  3. Заголовки групп (БК - 261, БК - 251 (у), ...) восстанавливаются из слов
     полосы над подзаголовками; метки времени — из колонки «Часы».
  4. Сетка строк таблицы динамическая: все найденные метки времени,
     сгруппированные по дням (маркеры ПНД..СБТ) с исправлением утечек
     через монотонность времени звонков.
  5. Для каждой колонки: строки контента -> сегментация занятий по маркерам
     типа -> DP-раскладка занятий по строкам (метод из parse_pdf.py).
  6. Валидация: метод B (layout-срез каждой группы) + sanity-чеки.

Запуск:
  .venv/bin/python scripts/parse_all.py [папка_с_pdf]
"""

import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from parse_pdf import (  # noqa: E402
    DAY_MARKERS,
    DAY_NAMES_RU,
    DAY_ORDER,
    INITIALS_RE,
    KIND_COMBINED_RE,
    KIND_SIMPLE_RE,
    PAIR_NUMBERS,
    SEMESTER_END,
    SEMESTER_START,
    SURNAME_RE,
    TIME_RE,
    _distribute_lessons,
    _make_lesson_block,
    build_day_sections,
    cluster_visual_lines,
    normalize_time,
    parse_lesson,
    parse_words,
    pdftotext_text,
    rough_day_of,
)

GROUP_WORD_RE = re.compile(r"^[А-ЯЁ]{2,3}$")
GROUP_TAIL_RE = re.compile(r"^(-|\d{3}|\(\s*[уУ]\s*\)|[уУ]\))$")
pa_VIRT_RE = re.compile(r"^(вирт[.]?|ауд[.]?|\d+)$")


PAIR_LOOKUP = {normalize_time(k): v for k, v in PAIR_NUMBERS.items()}


def warn_local(msg: str) -> None:
    print(f"  [!] {msg}", file=sys.stderr)


def time_key(label: str) -> tuple[int, int]:
    """Ключ сортировки слота по времени начала."""
    h, m = label.split("-")[0].split(".")
    return int(h), int(m)


# ---------------------------------------------------------------- структура PDF

def load_visual_lines(pdf_path: Path) -> list[dict]:
    xml = pdftotext_text(pdf_path, "-bbox-layout")
    words = parse_words(xml)
    return [l for l in cluster_visual_lines(words) if l["y"] > 50]


def detect_columns(lines: list[dict], page_width: float) -> dict:
    """Колонки-группы: ярлыки, x-границыи Y подзаголовков."""
    disc_words = sorted(
        (w for ln in lines for w in ln["words"]
         if w["text"] == "Дисциплины" and w["x0"] > 60),
        key=lambda w: w["x0"])
    if not disc_words:
        raise RuntimeError("не найдены подзаголовки «Дисциплины»")
    sub_y = disc_words[0]["y0"]

    aud_words = sorted(
        (w for ln in lines for w in ln["words"]
         if w["text"] == "Ауд." and abs(w["y0"] - sub_y) < 3),
        key=lambda w: w["x0"])
    if len(aud_words) != len(disc_words):
        warn_local(f"Ауд. ({len(aud_words)}) != Дисциплины ({len(disc_words)})")

    def aud_x1(idx: int) -> float | None:
        """x1 подзаголовка «Ауд.» колонки idx; None — подзаголовка нет."""
        if 0 <= idx < len(aud_words):
            return aud_words[idx]["x1"]
        return None

    content_words = [w for ln in lines for w in ln["words"] if w["y0"] > sub_y + 2]

    # indent_i (индивидуальный): disc_i.x0 - левый край контента колонки i
    indents = []
    for i, d in enumerate(disc_words):
        left = aud_x1(i - 1) if i > 0 else None
        left_lim = left if left is not None else 0.0
        zone = [w for w in content_words if left_lim < w["x0"] < d["x0"]]
        if zone:
            indents.append(d["x0"] - min(w["x0"] for w in zone))
    if not indents:
        raise RuntimeError("не удалось определить отступ контента колонки")
    fallback_indent = sorted(indents)[len(indents) // 2]

    def indent_of(i: int) -> float:
        """Индивидуальный отступ колонки; для пустых — медианный."""
        d = disc_words[i]
        left = aud_x1(i - 1) if i > 0 else None
        left_lim = left if left is not None else 0.0
        zone = [w for w in content_words
                if left_lim < w["x0"] < d["x0"]
                and w["text"] not in DAY_MARKERS
                and w["text"] not in ("Дни", "Часы")
                and not TIME_RE.match(w["text"])
                and w["text"] not in ("БА", "БК", "БТ", "БЭ", "БТТ", "-")]
        if zone:
            return d["x0"] - min(w["x0"] for w in zone)
        return fallback_indent

    # заголовки групп: полоса [sub_y-12, sub_y-0.5)
    band = sorted(
        (w for ln in lines for w in ln["words"]
         if sub_y - 12 <= w["y0"] < sub_y - 0.5),
        key=lambda w: w["x0"])
    labels = []
    cur = None
    for w in band:
        if GROUP_WORD_RE.match(w["text"]):
            cur = {"parts": [w["text"]], "x0": w["x0"]}
            labels.append(cur)
        elif cur is not None and GROUP_TAIL_RE.match(w["text"]):
            cur["parts"].append(w["text"])
        else:
            cur = None
    groups = []
    for lb in labels:
        raw = "".join(lb["parts"])
        m = re.match(r"^([А-ЯЁ]{2,3})-?(\d{3})(\(\s*[уУ]\s*\))?$", raw)
        if not m:
            warn_local(f"странный заголовок группы: {raw!r}")
            continue
        suffix = "(у)" if m.group(3) else ""
        gid = f"{m.group(1)}-{m.group(2)}{suffix}"
        groups.append({"id": gid, "x0": lb["x0"]})

    if len(groups) != len(disc_words):
        raise RuntimeError(f"заголовков групп {len(groups)} != колонок {len(disc_words)}")

    bounds = []
    teacher_zones = []
    for i, d in enumerate(disc_words):
        start = d["x0"] - indent_of(i)
        end = (disc_words[i + 1]["x0"] - indent_of(i + 1)) \
            if i + 1 < len(disc_words) else page_width - 5
        prev_aud = aud_x1(i - 1) if i > 0 else None
        if prev_aud is not None:
            start = max(start, prev_aud + 0.5)
        bounds.append({"left": start, "right": end})
        # учительская зона: между «Дисциплины» и «Ауд.»; без «Ауд.» —
        # до правой границы колонки
        cur_aud = aud_x1(i)
        zone_end = cur_aud + 5 if cur_aud is not None else bounds[-1]["right"] - 5
        teacher_zones.append([d["x0"] - 12, zone_end])
    has_teacher_zone = any(
        w["text"] == "Преподаватели" and abs(w["y0"] - sub_y) < 3
        for ln in lines for w in ln["words"])
    return {"labels": groups, "bounds": bounds, "sub_y": sub_y,
            "teacher_zones": teacher_zones, "has_teacher_zone": has_teacher_zone}


def split_line_columns(line: dict, bounds: list[dict]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for w in line["words"]:
        for i, b in enumerate(bounds):
            if b["left"] <= w["x0"] < b["right"]:
                out.setdefault(i, []).append(w["text"])
                break
    return out


def detect_day_and_time(
    lines: list[dict], first_col_left: float
) -> tuple[dict[str, float], list[dict]]:
    """Маркеры дней и якоря времени (метки в зоне «Часы», левее первой колонки).

    Маркер дня и метка времени могут оказаться на одной визуальной строке —
    ищем их независимо.
    """
    day_anchors: dict[str, float] = {}
    time_anchors: list[dict] = []
    time_x_max = first_col_left - 1
    for ln in lines:
        for w in ln["words"]:
            if w["text"] in DAY_MARKERS and w["x1"] < time_x_max:
                day_anchors.setdefault(DAY_MARKERS[w["text"]], ln["y"])
                break
        for w in ln["words"]:
            if w["x0"] < time_x_max and TIME_RE.match(w["text"]):
                time_anchors.append({"time": w["text"], "y": ln["y"]})
                break
    if set(day_anchors) < set(DAY_MARKERS.values()):
        warn_local(f"не все маркеры дней найдены: {sorted(day_anchors)}")
    time_anchors.sort(key=lambda a: a["y"])
    return day_anchors, time_anchors


def assign_anchors_to_days(
    time_anchors: list[dict],
    sections: dict[str, tuple[float, float]],
) -> dict[str, list[dict]]:
    """Якоря по дням с исправлением утечек через монотонность времени звонков."""
    rows: dict[str, list[dict]] = {d: [] for d in DAY_ORDER}
    for a in time_anchors:
        day = rough_day_of(a["y"], sections)
        if day is None:
            warn_local(f"якорь времени {a['time']} y={a['y']:.1f} вне секций")
            continue
        rows[day].append(a)

    for i, day in enumerate(DAY_ORDER):
        anchors = sorted(rows[day], key=lambda a: a["y"])
        moved: list[dict] = []
        while len(anchors) >= 2 and \
                time_key(anchors[1]["time"]) < time_key(anchors[0]["time"]):
            moved.append(anchors.pop(0))
        if moved:
            if i == 0:
                warn_local(f"{day}: внеочередные якоря отброшены: "
                           f"{[a['time'] for a in moved]}")
            else:
                rows[DAY_ORDER[i - 1]].extend(moved)
                warn_local(f"якоря {[a['time'] for a in moved]} перенесены: "
                           f"{day} -> {DAY_ORDER[i - 1]}")
        rows[day] = anchors

    for i, day in enumerate(DAY_ORDER):
        anchors = sorted(rows[day], key=lambda a: a["y"])
        moved = []
        while len(anchors) >= 2 and \
                time_key(anchors[-1]["time"]) < time_key(anchors[-2]["time"]):
            moved.insert(0, anchors.pop())
        if moved:
            if i + 1 < len(DAY_ORDER):
                rows[DAY_ORDER[i + 1]] = moved + rows[DAY_ORDER[i + 1]]
                warn_local(f"якоря {[a['time'] for a in moved]} перенесены: "
                           f"{day} -> {DAY_ORDER[i + 1]}")
            else:
                # последний день (суббота): перенести некуда — оставляем,
                # иначе слоты субботы молча теряются
                anchors = moved + anchors
                warn_local(f"{day}: хвостовые якоря не монотонны, оставлены: "
                           f"{[a['time'] for a in moved]} — сверить с PDF")
        rows[day] = anchors

    for day in DAY_ORDER:
        times = [a["time"] for a in sorted(rows[day], key=lambda a: a["y"])]
        keys = [time_key(t) for t in times]
        if any(keys[i + 1] <= keys[i] for i in range(len(keys) - 1)):
            warn_local(f"{day}: якоря времени не возрастают: {times}")
        if len(set(times)) != len(times):
            warn_local(f"{day}: дубли якорей времени: {times}")
        rows[day] = sorted(rows[day], key=lambda a: a["y"])
    return rows


def parse_course_pdf(pdf_path: Path) -> tuple[str, dict[str, dict]]:
    """Разбирает один PDF. Возвращает (semester_title, {group_id: расписание}).

    расписание = {day: {"name": ..., "slots": [{time, pair, lessons: [...]}]}}
    """
    layout = pdftotext_text(pdf_path, "-layout")
    semester_title = ""
    ms = re.search(r"(\d+ семестр \d{4}/\d{4})", layout)
    if ms:
        semester_title = ms.group(1)

    lines = load_visual_lines(pdf_path)
    columns = detect_columns(lines, page_width=595.2)
    labels, bounds = columns["labels"], columns["bounds"]
    teacher_zones = columns["teacher_zones"]
    has_teacher_zone = columns["has_teacher_zone"]
    # всё, что выше подзаголовков (титул, шапка таблицы) — не контент
    lines = [l for l in lines if l["y"] > columns["sub_y"] + 2]

    day_anchors, time_anchors = detect_day_and_time(lines, bounds[0]["left"])
    sections = build_day_sections(day_anchors)
    rows_by_day = assign_anchors_to_days(time_anchors, sections)

    global_rows: list[dict] = []
    for day in DAY_ORDER:
        for a in rows_by_day[day]:
            global_rows.append({"day": day, "time": a["time"], "y": a["y"]})
    global_rows.sort(key=lambda r: r["y"])
    seen: set = set()
    deduped = []
    for r in global_rows:
        key = (r["day"], r["time"])
        if key in seen:
            warn_local(f"дубль строки {key} — пропущен")
            continue
        seen.add(key)
        deduped.append(r)
    global_rows = deduped
    if not global_rows:
        raise RuntimeError(f"{pdf_path.name}: не найдено строк расписания")

    # подпись под таблицей: cutoff — ГЛОБАЛЬНЫЙ (по самой верхней строке
    # подписи), т.к. вирт-цифры и хвосты подписей переползают между колонками
    cutoff_y = None
    for ln in lines:
        if any(w["text"] in ("Начальник", "УМО", "ОРО") for w in ln["words"]):
            if cutoff_y is None or ln["y"] < cutoff_y:
                cutoff_y = ln["y"]
    cutoffs = {k: cutoff_y for k in range(len(labels))}

    col_words_all: dict[int, list[dict]] = {}
    for k in range(len(labels)):
        cw: list[dict] = []
        for ln in sorted(lines, key=lambda l: l["y"]):
            if cutoffs[k] is not None and ln["y"] >= cutoffs[k]:
                continue
            for w in ln["words"]:
                # Excel выводит цифры виртуальных аудиторий («вирт ауд. 5»)
                # с overflow за правую границу колонки. Такие цифры висят
                # далеко от остального контента строки — возвращаем их
                # владельцу по X-близости.
                if not (bounds[k]["left"] <= w["x0"] < bounds[k]["right"]):
                    if not (re.match(r"^\d+$", w["text"]) and k + 1 < len(labels)
                            and bounds[k]["right"] <= w["x0"] < bounds[k]["right"] + 12):
                        continue
                cw.append({
                    "text": w["text"], "x0": w["x0"], "x1": w["x1"],
                    "y0": w["y0"], "y1": w["y1"], "line_y": ln["y"],
                })
        col_words_all[k] = cw

    # цифры виртуальных аудиторий («вирт ауд. 5») Excel печатает с overflow
    # за границу колонки — возвращаем их владельцу (колонка кончается вирт/ауд)
    all_ys = sorted({w["line_y"] for cw in col_words_all.values() for w in cw})
    for y in all_ys:
        for k in range(len(labels) - 1):
            wk = [w for w in col_words_all[k] if w["line_y"] == y]
            wk1 = [w for w in col_words_all[k + 1] if w["line_y"] == y]
            if not wk or not wk1:
                continue
            wk.sort(key=lambda w: w["x0"])
            wk1.sort(key=lambda w: w["x0"])
            if not re.match(r"^(вирт|ауд)[.]?$", wk[-1]["text"]):
                continue
            first = wk1[0]
            if re.match(r"^\d{1,2}$", first["text"]) \
                    and first["x0"] < bounds[k]["right"] + 40:
                col_words_all[k].append(first)
                col_words_all[k + 1] = [
                    w for w in col_words_all[k + 1] if w is not first]

    schedule: dict[str, dict] = {}
    for k, label in enumerate(labels):
        t_zone = teacher_zones[k]
        col_words = col_words_all[k]

        # --- блоки занятий (по строкам) ---
        lines_of_col: dict[float, list[dict]] = {}
        for w in col_words:
            lines_of_col.setdefault(w["line_y"], []).append(w)
        ordered_lines = [lines_of_col[y] for y in sorted(lines_of_col)]

        # --- сегментация по блокам занятий ---
        # строки-мусор: только 1-2-значные числа (переползшие чужие вирт-цифры)
        ordered_lines = [wl for wl in ordered_lines
                         if not all(re.match(r"^\d{1,2}$", w["text"])
                                    for w in wl)]

        def is_sandwich(wl: list[dict]) -> bool:
            """Сэндвич-строка: ≤3 слов, все — фамилия/инициалы/вирт/ауд.
            (ФИО, разбитое переносами: 'НИКИФОРОВА' / 'Л.С.')."""
            if not (1 <= len(wl) <= 3):
                return False
            return all(SURNAME_RE.match(w["text"])
                       or INITIALS_RE.match(w["text"])
                       or pa_VIRT_RE.match(w["text"]) for w in wl)

        GAP_SPLIT = 5.5  # pt: внутри занятия ≤4-5.5, граница занятия >5.5
        blocks: list[list[dict]] = []
        cur: list[dict] = []
        prev_y: float | None = None
        for wl in ordered_lines:
            words = [w["text"] for w in wl]
            starts_kind = bool(KIND_COMBINED_RE.match(words[0])
                               or KIND_SIMPLE_RE.match(words[0]))
            gap = (wl[0]["y0"] - prev_y) if prev_y is not None else 0.0
            starts_gap = gap > GAP_SPLIT and not is_sandwich(wl)
            starts_new = starts_kind or starts_gap
            if starts_new and cur:
                # строки-хвосты ячейки («вирт. ауд.», «вирт. ауд. 3») уводим
                # в НАСТУПАЮЩЕЕ занятие, но только если в них нет цифры-номера
                # аудитории: «вирт ауд. 5» — номер принадлежит ПРЕДЫДУЩЕЙ паре
                virt_tail = []
                while cur and all(pa_VIRT_RE.match(w["text"]) for w in cur[-1]) \
                        and not any(re.match(r"^\d+$", w["text"]) for w in cur[-1]):
                    virt_tail.insert(0, cur.pop())
                blocks.append(cur)
                cur = virt_tail + [wl]
                prev_y = wl[0]["y0"]
                continue
            cur.append(wl)
            if prev_y is None or wl[0]["y0"] > prev_y:
                prev_y = wl[0]["y0"]
        if cur:
            blocks.append(cur)

        # --- начальный разбор (многопроходный) ---
        parsed_blocks: list[dict] = []
        for blk in blocks:
            wl = [w for line in blk for w in line]
            tokens = [w["text"] for w in wl]
            lesson = parse_lesson(tokens)
            if lesson is None:
                continue
            block = {
                "words": wl,
                "tokens": tokens,
                "lesson": lesson,
                "row": None,
                "ymin": min(w["y0"] for w in wl),
                "ymax": max(w["y1"] for w in wl),
            }
            parsed_blocks.append(block)

        # --- учитель из учительской зоны (сэндвич ФАМИЛИЯ над / И.О. под) ---
        # у занятия, чей учитель не распознан в потоке, забираем ближайшие
        # фамилию и инициалы из учительской подколонки (окно ±5..14 pt).
        # Если фамилия-сирота есть в блоке, а инициалы уехали за границу
        # колонки (Excel-overflow) — ищем их в соседних колонках.
        used_teacher_ids: set[int] = set()
        attached: dict[int, list[str]] = {}
        if has_teacher_zone:
            zone_words_by_col: dict[int, list[dict]] = {}
            for ci, tz in enumerate(teacher_zones):
                cutoff_c = cutoffs.get(ci)
                for w in col_words_all[ci]:
                    if cutoff_c is not None and w["line_y"] >= cutoff_c:
                        continue
                    if tz[0] <= w["x0"] < tz[1] \
                            and (SURNAME_RE.match(w["text"]) or INITIALS_RE.match(w["text"])) \
                            and w["text"] not in ("Начальник", "УМО", "ОРО"):
                        zone_words_by_col.setdefault(ci, []).append(w)
            for ci in zone_words_by_col:
                zone_words_by_col[ci].sort(key=lambda w: w["y0"])

            WINDOW_UP, WINDOW_DOWN = 14.0, 9.0

            def find_in_zone(ci: int, lo: float, hi: float):
                surname = init = None
                for w in zone_words_by_col.get(ci, []):
                    if id(w) in used_teacher_ids:
                        continue
                    if not (lo <= w["y1"] <= hi):
                        continue
                    if SURNAME_RE.match(w["text"]):
                        surname = w
                    elif INITIALS_RE.match(w["text"]):
                        init = w
                return surname, init

            for b in parsed_blocks:
                if b["lesson"]["teacher"]:
                    continue
                # своя фамилия-сирота в токенах блока?
                own_surname = None
                for w in b["words"]:
                    if w["x0"] >= t_zone[0] and SURNAME_RE.match(w["text"]) \
                            and w["text"] not in ("Начальник", "УМО", "ОРО"):
                        own_surname = w
                        break
                lo, hi = b["ymax"] - WINDOW_DOWN, b["ymax"] + WINDOW_UP
                surname, init = find_in_zone(k, lo, hi)
                if surname is None and init is None:
                    continue
                if own_surname is not None:
                    surname = own_surname
                    if init is None:
                        # инициалы могли уехать в соседнюю колонку
                        for ci in (k + 1, k - 1):
                            s2, i2 = find_in_zone(ci, lo, hi)
                            if i2 is not None:
                                init = i2
                                used_teacher_ids.add(id(i2))
                                break
                    if init is not None:
                        b["lesson"]["teacher"] = f"{surname['text']} {init['text']}"
                        used_teacher_ids.add(id(surname))
                        attached[id(b)] = [surname["text"], init["text"]]
                    continue
                if surname and init:
                    b["lesson"]["teacher"] = f"{surname['text']} {init['text']}"
                    b["lesson"].pop("_teacher_span", None)
                    used_teacher_ids.add(id(surname))
                    used_teacher_ids.add(id(init))
                    attached[id(b)] = [surname["text"], init["text"]]

        # --- DP-раскладка по строкам ---
        blocks_for_dp = parsed_blocks
        _distribute_lessons(blocks_for_dp, global_rows)

        # --- сборка слотов ---
        day_struct = {d: {"name": DAY_NAMES_RU[d], "slots": []} for d in DAY_ORDER}
        slot_map: dict[tuple[str, str], dict] = {}
        for b in blocks_for_dp:
            lesson = b["lesson"]
            if b["row"] is None:
                continue
            # чистка subject: убрать привязанные сэндвич-ФИО и хвостовых
            # «сирот» из учительской зоны (они принадлежат соседним ячейкам)
            subject = lesson.get("subject", "")
            for tok in attached.get(id(b), []):
                subject = re.sub(rf"(?<!\S){re.escape(tok)}(?!\S)", "", subject)
            consumed = lesson.pop("_consumed", [])
            if consumed:
                for w in b["words"][max(consumed) + 1:]:
                    if t_zone[0] <= w["x0"] < t_zone[1] and \
                            (SURNAME_RE.match(w["text"]) or INITIALS_RE.match(w["text"])):
                        subject = re.sub(rf"(?<!\S){re.escape(w['text'])}(?!\S)",
                                         "", subject)
            lesson["subject"] = re.sub(r"\s+", " ", subject).strip()
            # хирургия склеек: Excel-overflow приносит в subject хвосты чужих
            # ячеек (повторный маркер типа, номера вирт-аудиторий, подпись)
            subj2 = lesson["subject"]
            # 1) обрезать всё после ВТОРОГО маркера типа («… 5 лек., пр. …»)
            for m in re.finditer(r"(лек\., пр\.|лек\.|пр\.|лаб\.)", subj2):
                if m.start() > 0:
                    subj2 = subj2[:m.start()]
                    break
            # 2) хвостовые ФИО (фамилия + инициалы) из чужой ячейки
            subj2 = re.sub(
                r"\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.?\s*$", "", subj2)
            subj2 = re.sub(r"\s+[А-ЯЁ]{2,}\s+[А-ЯЁ]\.[А-ЯЁ]\.?\s*$", "", subj2)
            # 3) одиночные цифры 3/5 (номера вирт-аудиторий) — только по краям
            #    subject: утечка приходит с края соседней колонки; в середине
            #    цифры не трогаем («Часть 3», «Модуль 5»)
            if re.fullmatch(r"\s*[35]\s*", subj2):
                subj2 = ""
            else:
                subj2 = re.sub(r"^\s*(?<![\w.])[35](?![\w.])\s+", "", subj2)
                subj2 = re.sub(r"\s+(?<![\w.])[35](?![\w.])\s*$", "", subj2)
            # 4) повторы одиночных слов («материального производства» дубль
            #    не трогаем — безопаснее оставить)
            subj2 = re.sub(r"\s+", " ", subj2).strip(" ,")
            lesson["subject"] = subj2
            lesson.pop("_teacher_span", None)
            if not lesson["subject"]:
                continue
            row = b["row"]
            key = (row["day"], row["time"])
            slot = slot_map.get(key)
            if slot is None:
                slot = {"time": normalize_time(row["time"]),
                        "pair": PAIR_LOOKUP.get(normalize_time(row["time"]), 0),
                        "lessons": []}
                slot_map[key] = slot
            slot["lessons"].append(lesson)
        for day in DAY_ORDER:
            slots = sorted(
                (s for (d, _), s in slot_map.items() if d == day),
                key=lambda s: time_key(s["time"].replace(":", ".")))
            day_struct[day]["slots"] = slots
        schedule[label["id"]] = {
            "display": re.sub(r"^([А-ЯЁ]+)(\d{3})", r"\1-\2", label["id"])
                       .replace("(у)", " (у)"),
            "days": day_struct,
        }
    return semester_title, schedule


# ------------------------------------------------------- метод B: контроль

def _cut_line(ln: str, left: int, right: int) -> str:
    """Срезает строку по пробельным зазорам, ближайшим к границам колонки —
    жёсткая резка режет слова посередине (колонки в layout гуляют ±3 симв.)."""
    best = 0
    for m in re.finditer(r"\s{2,}", ln[:left + 10]):
        best = m.end()
    rend = len(ln)
    for m in re.finditer(r"\s{2,}", ln):
        if m.start() >= right - 10:
            rend = m.start()
            break
    return ln[best:rend]


def layout_group_slices(layout: str, group_ids: list[str]) -> dict[str, str]:
    """Срезы текста колонок из layout-выгрузки.

    Заголовки групп в Excel-выгрузках бывают смещены относительно своих
    колонок, поэтому режем по позициям подзаголовков «Дисциплины» (вторая
    строка шапки) — они выровнены с контентом колонок.
    """
    lines = layout.splitlines()
    header_idx = next(
        (i for i, ln in enumerate(lines) if "Дни" in ln and "Часы" in ln), None)
    if header_idx is None:
        raise RuntimeError("в layout-выгрузке не найдена шапка «Дни … Часы»")
    sub_idx = next(
        (i for i, ln in enumerate(lines[header_idx:], header_idx)
         if ln.count("Дисциплины") >= len(group_ids)), None)
    if sub_idx is None:
        raise RuntimeError(
            "в layout-выгрузке не найдена строка «Дисциплины» "
            f"с {len(group_ids)} колонками")
    sub = lines[sub_idx]

    positions = [m.start() for m in re.finditer(r"Дисциплины", sub)]
    slices = {}
    for i, gid in enumerate(group_ids):
        left = max(0, positions[i] - 25)
        right = (positions[i + 1] + 30) if i + 1 < len(positions) else len(sub)
        parts = [_cut_line(ln, left, right) for ln in lines[sub_idx + 1:]]
        slices[gid] = re.sub(r"\s+", " ", "\n".join(parts))
    return slices


def cross_check_course(
    groups: dict[str, dict], slices: dict[str, str]
) -> list[str]:
    """Каждый элемент занятия должен присутствовать в layout-срезе группы."""
    problems = []
    for gid, days in groups.items():
        compact = slices.get(gid, "")
        # «1н-1п, 2н-2п» в layout vs «1н-1п,2н-2п» в токенах
        compact_c = re.sub(r",\s+", ",", compact)
        if not compact:
            problems.append(f"{gid}: пустой layout-срез")
            continue
        for day in DAY_ORDER:
            for slot in days[day]["slots"]:
                for lesson in slot["lessons"]:
                    tag = (f"{gid} {day} {slot['time']} "
                           f"[{lesson['kind']}] {lesson['subject'][:28]}")
                    surname = lesson["teacher"].split()[0] if lesson["teacher"] else ""
                    if surname and surname not in compact:
                        problems.append(f"{tag}: фамилия {surname} не найдена")
                    room = lesson["room"]
                    if room and re.search(r"[\\/]", room):
                        for part in re.split(r"[\\/]", room):
                            if part not in compact:
                                problems.append(f"{tag}: аудитория {part} не найдена")
                    elif room and "вирт" not in room and room not in compact:
                        problems.append(f"{tag}: аудитория {room} не найдена")
                    for r in lesson["ranges"]:
                        d1 = date.fromisoformat(r[0]).strftime("%d.%m")
                        d2 = date.fromisoformat(r[1]).strftime("%d.%m")
                        if d1 not in compact or d2 not in compact:
                            problems.append(f"{tag}: даты {d1}..{d2} не найдены")
                    for d in lesson["exact_dates"]:
                        ds = date.fromisoformat(d).strftime("%d.%m")
                        if ds not in compact:
                            problems.append(f"{tag}: дата {ds} не найдена")
                    head = [w for w in lesson["subject"].split()[:3] if len(w) > 2]
                    # длинные слова бывают с переносом — сверяем префикс
                    missing = [w for w in head
                               if w[:6] not in compact and w not in compact_c]
                    if missing:
                        problems.append(
                            f"{tag}: слова предмета {missing} не найдены")
    return problems


def sanity_course(groups: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    # в PDF встречаются даты чуть дальше конца семестра — граница sanity
    # мягче на 3 дня (SEMESTER_END=28.12 -> 31.12)
    end_limit = SEMESTER_END + timedelta(days=3)
    for gid, days in groups.items():
        for day in DAY_ORDER:
            for slot in days[day]["slots"]:
                for lesson in slot["lessons"]:
                    all_d = [x for r in lesson["ranges"] for x in r] \
                        + lesson["exact_dates"]
                    for d in all_d:
                        if not (SEMESTER_START <= date.fromisoformat(d) <= end_limit):
                            problems.append(
                                f"{gid} {day} {slot['time']}: дата {d} вне семестра "
                                f"({lesson['subject'][:30]})")
                    if not lesson["subject"]:
                        problems.append(f"{gid} {day} {slot['time']}: пустой предмет")
                    if not lesson["teacher"]:
                        problems.append(f"{gid} {day} {slot['time']}: нет преподавателя")
    return problems


# ---------------------------------------------------------------- main

def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 \
        else Path.home() / "Загрузки/StankinE_Schedule"
    pdfs = sorted(src.glob("*curs*.pdf"))
    if not pdfs:
        print(f"PDF не найдены в {src}", file=sys.stderr)
        sys.exit(1)

    courses: dict[str, dict] = {}
    for pdf in pdfs:
        m = re.search(r"(\d)curs", pdf.name)
        if not m:
            print(f"!! {pdf.name}: в имени нет номера курса "
                  "(ожидается вида '1curs2026.pdf') — файл пропущен",
                  file=sys.stderr)
            continue
        course = m.group(1)
        print(f"\n=== {pdf.name} (курс {course}) ===")
        semester, groups = parse_course_pdf(pdf)
        print(f"Группы: {', '.join(groups)}")
        total = sum(
            len(s["lessons"])
            for g in groups.values()
            for d in g["days"].values()
            for s in d["slots"])
        print(f"Занятий: {total}")
        for gid, g in groups.items():
            cnt = sum(len(s["lessons"])
                      for d in g["days"].values() for s in d["slots"])
            print(f"  {g['display']}: {cnt}")

        layout = pdftotext_text(pdf, "-layout")
        print("--- контрольная сверка с layout (метод B) ---")
        problems = cross_check_course(
            {gid: g["days"] for gid, g in groups.items()},
            layout_group_slices(layout, list(groups)))
        if problems:
            for p in problems[:40]:
                print(f"  [B] {p}")
            if len(problems) > 40:
                print(f"  ... и ещё {len(problems) - 40}")
        else:
            print("  все занятия подтверждены")
        print("--- sanity ---")
        sproblems = sanity_course({gid: g["days"] for gid, g in groups.items()})
        for p in sproblems[:20]:
            print(f"  [S] {p}")
        if not sproblems:
            print("  отклонений нет")

        courses[course] = {
            "semester": semester,
            "groups": {gid: {"display": g["display"], "days": g["days"]}
                       for gid, g in groups.items()},
        }

    now_msk = datetime.now(ZoneInfo("Europe/Moscow"))
    payload = {
        "generated": now_msk.date().isoformat(),
        "generated_at": now_msk.isoformat(timespec="minutes"),
        "semester_start": SEMESTER_START.isoformat(),
        "semester_end": SEMESTER_END.isoformat(),
        "courses": courses,
    }
    out = ROOT / "data" / "schedule_all.json"
    out.parent.mkdir(exist_ok=True)

    # дифф со старой версией — читаем ДО перезаписи (changes.py)
    old_json = None
    if out.exists():
        try:
            old_json = json.loads(out.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            old_json = None

    # основной JSON пишем атомарно: бот парсит файл при импорте,
    # битый JSON = падение бота на старте
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, out)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print(f"\nJSON: {out}")

    # очередь уведомлений — после успешной записи JSON
    if old_json is not None:
        sys.path.insert(0, str(ROOT))
        from changes import compute_changes, save_pending
        changes = compute_changes(old_json, payload)
        if save_pending(changes):
            n_groups = len(changes)
            n_lines = sum(len(v) for v in changes.values())
            print(f"Изменения: {n_lines} в {n_groups} группах "
                  f"-> data/pending_changes.json")
        else:
            print("Изменений нет")


if __name__ == "__main__":
    main()
