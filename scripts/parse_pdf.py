#!/usr/bin/env python3
"""
Парсер расписания группы БА-231 из PDF (расписание 4 курса ЕТИ МГТУ «СТАНКИН»).

Источник: Excel-выгрузка расписания в PDF. pdftotext -bbox-layout даёт слова
и строки с координатами.

Алгоритм (метод A — основной, координатный, построчный):
  1. pdftotext -bbox-layout -> XML; из него берём СТРОКИ (line) со словами.
  2. Колонка БА-231 выделяется по X: строки с xMin в [113, 206.5).
     (границы сняты с координат заголовков и подзаголовков таблицы)
  3. Метки времени (08.30-10.05) — строки в колонке «Часы»; часть из них
     слита со строкой занятия — срезаем префикс. Маркеры дней (ПНД/ВТР/...)
     дают секции; якоря времени сопоставляются с ожидаемой сеткой слотов.
  4. Строки колонки раскладываются по (день, слот) по Y.
  5. Занятие сегментируется по маркерам типа (лек. / пр. / лаб. / Проект),
     из потока слов достаётся предмет, преподаватель, аудитория, даты.

Валидация (метод B — контрольный, независимый):
  Каждое занятие проверяется по выгрузке pdftotext -layout: фамилия,
  аудитория и даты должны присутствовать в срезе колонки БА-231 внутри
  секции соответствующего дня (секции определяются по меткам времени).

Выход: data/schedule.json и schedule_data.py (генерируется).
"""

import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

GROUP_COLUMN = (113.0, 206.5)   # X-диапазон колонки БА-231
DAY_COLUMN_MAX_X = 112.0        # колонка «Дни» (маркеры ПНД/ВТР/...)
TIME_COLUMN_MIN_X = 113.0       # колонка «Часы»
TIME_COLUMN_MAX_X = 160.0       # колонка «Часы»

DAY_MARKERS = {
    "ПНД": "monday",
    "ВТР": "tuesday",
    "СРД": "wednesday",
    "ЧТВ": "thursday",
    "ПТН": "friday",
    "СБТ": "saturday",
}
DAY_NAMES_RU = {
    "monday": "Понедельник",
    "tuesday": "Вторник",
    "wednesday": "Среда",
    "thursday": "Четверг",
    "friday": "Пятница",
    "saturday": "Суббота",
}
DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]

# Ожидаемая сетка слотов по дням (по факту этого PDF; для нового семестра сверить)
EXPECTED_SLOTS = {
    "monday": ["08.30-10.05", "10.15-11.50", "12.20-13.55", "14.05-15.40"],
    "tuesday": ["08.30-10.05", "10.15-11.50", "12.20-13.55", "14.05-15.40"],
    "wednesday": ["08.30-10.05", "10.15-11.50", "12.20-13.55", "14.05-15.40"],
    "thursday": ["08.30-10.05", "10.15-11.50", "12.20-13.55", "14.05-15.40", "15.50-17.25"],
    "friday": ["08.30-10.05", "10.15-11.50", "12.20-13.55", "14.05-15.40"],
    "saturday": ["08.30-10.05", "10.15-11.50", "12.00-13.35", "13.45-15.20", "15.30-17.05"],
}

SEMESTER_START = date(2026, 9, 1)
SEMESTER_END = date(2026, 12, 28)

# Номер пары по времени слота (общая сетка звонков)
PAIR_NUMBERS = {
    "08.30-10.05": 1,
    "10.15-11.50": 2,
    "12.00-13.35": 3,
    "12.20-13.55": 3,
    "13.45-15.20": 4,
    "14.05-15.40": 4,
    "15.30-17.05": 5,
    "15.50-17.25": 5,
}

TIME_RE = re.compile(r"^\d{2}\.\d{2}-\d{2}\.\d{2}$")
DATE_TOKEN_RE = re.compile(r"^\d{2}\.\d{2}$")
SURNAME_RE = re.compile(r"^[А-ЯЁ]{2,}(?:-[А-ЯЁ]{2,})?$")
INITIALS_RE = re.compile(r"^[А-ЯЁ]\.[А-ЯЁ]\.?$")
ROOM_RE = re.compile(r"^\d{3}(?:\\+\d{3})?$")
KIND_COMBINED_RE = re.compile(r"^лек\.,$")
KIND_SIMPLE_RE = re.compile(r"^(лек\.|пр\.|лаб\.|Проект)$")
LINK_PART_RE = re.compile(r"^(https://my\.mts-|link\.ru/.+)$")
VIRT_ROOM_RE = re.compile(r"^вирт[.]?ауд[.]?(\d+)$")

WARNINGS: list[str] = []


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"  [!] {msg}", file=sys.stderr)


# ---------------------------------------------------------------- извлечение

def run_pdftotext(pdf_path: Path) -> tuple[str, str]:
    DATA_DIR.mkdir(exist_ok=True)
    layout = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True, capture_output=True, text=True,
    ).stdout
    bbox = subprocess.run(
        ["pdftotext", "-bbox-layout", str(pdf_path), "-"],
        check=True, capture_output=True, text=True,
    ).stdout
    (DATA_DIR / "layout.txt").write_text(layout, encoding="utf-8")
    (DATA_DIR / "bbox.xml").write_text(bbox, encoding="utf-8")
    return layout, bbox


def parse_words(bbox_xml: str) -> list[dict]:
    """Извлекает слова с координатами."""
    root = ET.fromstring(bbox_xml)
    words = []
    for w in root.iter():
        if not w.tag.endswith("word"):
            continue
        t = re.sub(r"\s+", "", (w.text or ""))
        if t:
            words.append({
                "x0": float(w.attrib["xMin"]),
                "x1": float(w.attrib["xMax"]),
                "y0": float(w.attrib["yMin"]),
                "y1": float(w.attrib["yMax"]),
                "text": t,
            })
    return words


def cluster_visual_lines(words: list[dict], tol: float = 1.0) -> list[dict]:
    """Кластеризует слова в визуальные строки по Y (Excel-выгрузка рвёт
    одну строку на несколько <line>; слова одной строки имеют одинаковый yMin)."""
    ordered = sorted(words, key=lambda w: (w["y0"], w["x0"]))
    rows: list[list[dict]] = []
    for w in ordered:
        if rows and abs(w["y0"] - rows[-1][0]["y0"]) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        lines.append({
            "y": (row[0]["y0"] + row[0]["y1"]) / 2,
            "words": row,
        })
    return lines


def collect_inputs(visual_lines: list[dict]) -> tuple[dict[str, float], list[dict], list[dict]]:
    """(маркеры дней, якоря времени, строки контента) из визуальных строк."""
    day_anchors: dict[str, float] = {}
    time_anchors: list[dict] = []
    content: list[dict] = []
    for vl in visual_lines:
        parts = split_line_columns(vl)
        if parts["day"]:
            day_anchors.setdefault(DAY_MARKERS[parts["day"]], parts["y"])
        if parts["time"]:
            time_anchors.append({"time": parts["time"], "y": parts["y"]})
        if parts["content"]:
            # подпись под таблицей («Начальник УМО Т.В. Волкова» и т.п.)
            if parts["content"][0] in ("Начальник", "УМО", "ОРО"):
                continue
            content.append(parts)
    if set(day_anchors) < set(DAY_MARKERS.values()):
        warn(f"не все маркеры дней найдены: {sorted(day_anchors)}")
    time_anchors.sort(key=lambda a: a["y"])
    return day_anchors, time_anchors, content


def split_line_columns(line: dict) -> dict:
    """Разделяет визуальную строку на маркер дня / метку времени / контент БА."""
    day_word = next((w["text"] for w in line["words"]
                     if w["x0"] < DAY_COLUMN_MAX_X and w["text"] in DAY_MARKERS), None)
    time_w = next((w for w in line["words"]
                   if TIME_COLUMN_MIN_X <= w["x0"] < TIME_COLUMN_MAX_X
                   and TIME_RE.match(w["text"])), None)
    content_words = [w["text"] for w in line["words"]
                     if GROUP_COLUMN[0] <= w["x0"] < GROUP_COLUMN[1]
                     and w is not time_w]
    return {"day": day_word,
            "time": time_w["text"] if time_w else None,
            "content": content_words, "y": line["y"]}


# ------------------------------------------------- сетка дней и слотов

def build_day_sections(day_anchors: dict[str, float]) -> dict[str, tuple[float, float]]:
    """Границы секций дней — середины между центрами соседних маркеров."""
    days = sorted(day_anchors.items(), key=lambda kv: kv[1])
    sections: dict[str, tuple[float, float]] = {}
    for i, (day, y) in enumerate(days):
        top = (days[i - 1][1] + y) / 2 if i > 0 else 0.0
        bottom = (y + days[i + 1][1]) / 2 if i + 1 < len(days) else 1e9
        sections[day] = (top, bottom)
    return sections


def rough_day_of(y: float, sections: dict[str, tuple[float, float]]) -> str | None:
    for day, (top, bottom) in sections.items():
        if top <= y < bottom:
            return day
    return None


def assign_time_anchors(
    time_anchors: list[dict],
    sections: dict[str, tuple[float, float]],
) -> list[dict]:
    """Раскладывает якоря времени по дням (ожидаемая сетка), возвращает
    глобальный список 26 строк в порядке Y с днём и временем."""
    rows: dict[str, list[dict]] = {d: [] for d in DAY_ORDER}
    for a in time_anchors:
        day = rough_day_of(a["y"], sections)
        if day is None:
            warn(f"якорь времени {a['time']} y={a['y']} вне секций дней")
            continue
        rows[day].append(a)

    # якорь мог сместиться в соседнюю секцию (граница по серединам маркеров
    # приближённая): переносим «лишний» якорь, если он закрывает пропуск соседа
    for i, day in enumerate(DAY_ORDER):
        anchors = rows[day]
        if len(anchors) > len(EXPECTED_SLOTS[day]):
            first = anchors[0]
            if i > 0:
                prev_day = DAY_ORDER[i - 1]
                prev_times = [a["time"] for a in rows[prev_day]]
                if first["time"] in EXPECTED_SLOTS[prev_day] \
                        and first["time"] not in prev_times:
                    rows[prev_day].append(first)
                    rows[day] = anchors[1:]
                    warn(f"якорь {first['time']} y={first['y']:.1f} перенесён: "
                         f"{day} -> {prev_day}")

    global_rows: list[dict] = []
    for day in DAY_ORDER:
        expected = EXPECTED_SLOTS[day]
        anchors = sorted(rows[day], key=lambda a: a["y"])
        found = [a["time"] for a in anchors]
        subseq = [t for t in expected if t in found]
        if found != subseq:
            warn(f"{day}: якоря времени не по порядку: {found}")
        for t in expected:
            match = next((a for a in anchors if a["time"] == t), None)
            if match is not None:
                global_rows.append({"day": day, "time": t, "y": match["y"],
                                    "lines": []})
            else:
                warn(f"{day}: метка {t} не найдена")
    global_rows.sort(key=lambda r: r["y"])
    return global_rows


def assign_content(
    content: list[dict],
    global_rows: list[dict],
) -> dict[str, dict[str, list[dict]]]:
    """Сегментирует контент на занятия (по маркерам типа) и раскладывает
    целые занятия по строкам таблицы DP-оптимизацией: занятие не может быть
    разрезано между строками, а метка времени в Excel центрирована в своей
    строке, поэтому верное распределение минимизирует суммарное отклонение
    центров занятий от якорей."""
    ordered = sorted(content, key=lambda l: l["y"])
    lessons: list[dict] = []
    cur: list[dict] = []
    for ln in ordered:
        words = ln["content"]
        starts_new = bool(KIND_COMBINED_RE.match(words[0])
                          or KIND_SIMPLE_RE.match(words[0]))
        if starts_new and cur:
            lessons.append(_make_lesson_block(cur))
            cur = []
        cur.append(ln)
    if cur:
        lessons.append(_make_lesson_block(cur))

    _distribute_lessons(lessons, global_rows)

    slots: dict[str, dict[str, list[dict]]] = {
        d: {r["time"]: [] for r in global_rows if r["day"] == d} for d in DAY_ORDER
    }
    for les in lessons:
        slots[les["row"]["day"]][les["row"]["time"]].append(les)
    return slots


def _make_lesson_block(lines: list[dict]) -> dict:
    return {
        "lines": lines,
        "tokens": [w for ln in lines for w in ln["content"]],
        "ymin": min(ln["y"] for ln in lines),
        "ymax": max(ln["y"] for ln in lines),
        "row": None,
    }


def _distribute_lessons(lessons: list[dict], rows: list[dict]) -> None:
    """DP: раскладывает занятия по строкам таблицы. Стоимость строки:
    сумма отклонений центров занятий от якоря + отклонение центра диапазона
    строки от якоря (метка времени в Excel центрирована в своей строке,
    поэтому верное распределение симметрично относительно якоря)."""
    m, n = len(lessons), len(rows)
    if m == 0:
        return
    if n == 0:
        warn(f"{m} занятий не распределено: нет строк сетки")
        return
    centers = [(l["ymin"] + l["ymax"]) / 2 for l in lessons]
    # S[j][t] = сумма |center_u - anchor_j| для u < t
    S = [[0.0] * (m + 1) for _ in range(n)]
    for j in range(n):
        a = rows[j]["y"]
        for t in range(1, m + 1):
            S[j][t] = S[j][t - 1] + abs(centers[t - 1] - a)

    INF = float("inf")
    dp = [[INF] * (n + 1) for _ in range(m + 1)]
    take = [[0] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0
    for j in range(1, n + 1):
        sj = S[j - 1]
        a = rows[j - 1]["y"]
        for i in range(0, m + 1):
            best = dp[i][j - 1]          # строка может остаться пустой
            take[i][j] = i
            for k in range(0, i):
                if dp[k][j - 1] == INF:
                    continue
                span = abs((lessons[k]["ymin"] + lessons[i - 1]["ymax"]) / 2 - a)
                v = dp[k][j - 1] + (sj[i] - sj[k]) + span
                if v < best:
                    best = v
                    take[i][j] = k
            dp[i][j] = best

    i = m
    for j in range(n, 0, -1):
        k = take[i][j]
        for t in range(k, i):
            lessons[t]["row"] = rows[j - 1]
        i = k
    if i != 0:
        warn(f"{i} первых занятий не удалось привязать к строкам")


# ------------------------------------------------- разбор занятия

def normalize_time(t: str) -> str:
    return t.replace(".", ":")


def infer_year(month: int) -> int:
    return 2026 if month >= 7 else 2027


def _mkdate(ddmm: str) -> date | None:
    try:
        d, m = (int(x) for x in ddmm.split("."))
        return date(infer_year(m), m, d)
    except ValueError:
        return None


def parse_lesson(tokens: list[str]) -> dict | None:
    """Разбирает поток слов одного занятия (многопроходно, порядок независим).

    Проходы: тип -> преподаватель -> аудитория -> ссылка -> даты -> предмет.
    Многопроходность нужна, потому что между 'с' и датами диапазона могут
    стоять ФИО и аудитория (перенос строк в Excel-ячейке).
    """
    if not tokens:
        return None
    kind = ""
    idx = 0
    if KIND_COMBINED_RE.match(tokens[0]):
        if len(tokens) > 1 and tokens[1] == "пр.":
            kind = "лек., пр."
            idx = 2
        else:
            warn(f"'лек.,' без 'пр.': {' '.join(tokens[:6])}")
            kind = "лек."
            idx = 1
    elif KIND_SIMPLE_RE.match(tokens[0]):
        kind = tokens[0]
        idx = 1
    else:
        warn(f"занятие без типа в начале: {' '.join(tokens[:8])}")

    n = len(tokens)
    used = [False] * n
    for i in range(idx):
        used[i] = True

    # проход 1: преподаватель (ФАМИЛИЯ + И.О., могут быть на разных строках)
    teacher = None
    for j in range(idx, n - 1):
        if not used[j] and not used[j + 1] \
                and SURNAME_RE.match(tokens[j]) and INITIALS_RE.match(tokens[j + 1]):
            teacher = f"{tokens[j]} {tokens[j + 1]}"
            used[j] = used[j + 1] = True
            break

    # проход 2: аудитория
    room = None
    for j in range(idx, n):
        if used[j]:
            continue
        if ROOM_RE.match(tokens[j]):
            room = tokens[j]
            used[j] = True
            break
        m = VIRT_ROOM_RE.match(tokens[j])
        if m:
            room = f"вирт. ауд. {m.group(1)}"
            used[j] = True
            break
        if re.match(r"^вирт[.]?$", tokens[j]) and j + 1 < n \
                and re.match(r"^ауд[.]?$", tokens[j + 1]):
            num = tokens[j + 2] if j + 2 < n else ""
            room = f"вирт. ауд. {num}"
            for k in range(j, min(j + 3, n)):
                used[k] = True
            break

    # проход 3: ссылка на онлайн-занятие
    link = None
    for j in range(idx, n):
        if used[j]:
            continue
        if LINK_PART_RE.match(tokens[j]):
            parts = []
            k = j
            while k < n and not used[k] and LINK_PART_RE.match(tokens[k]):
                parts.append(tokens[k])
                used[k] = True
                k += 1
            link = "".join(parts)
            break

    # проход 4: даты
    ranges: list[list[str]] = []
    exact: list[str] = []

    def next_unused(start: int, limit: int) -> int | None:
        for k in range(start, min(limit, n)):
            if not used[k]:
                return k
        return None

    for j in range(idx, n):
        if used[j]:
            continue
        t = tokens[j]
        if t == "с":
            k = next_unused(j + 1, j + 8)
            if k is not None and DATE_TOKEN_RE.match(tokens[k]):
                d1 = _mkdate(tokens[k])
                k2 = next_unused(k + 1, k + 2)
                if d1 and k2 is not None and tokens[k2] == "по":
                    k3 = next_unused(k2 + 1, k2 + 2)
                    if k3 is not None and DATE_TOKEN_RE.match(tokens[k3]):
                        d2 = _mkdate(tokens[k3])
                        if d1 and d2:
                            ranges.append([d1.isoformat(), d2.isoformat()])
                            used[j] = used[k] = used[k2] = used[k3] = True
                            continue
                if d1:
                    exact.append(d1.isoformat())
                    used[j] = used[k] = True
                    continue
        elif DATE_TOKEN_RE.match(t):
            d1 = _mkdate(t)
            if d1 is None:
                continue
            k2 = next_unused(j + 1, j + 2)
            if k2 is not None and tokens[k2] == "по":
                k3 = next_unused(k2 + 1, k2 + 2)
                if k3 is not None and DATE_TOKEN_RE.match(tokens[k3]):
                    d2 = _mkdate(tokens[k3])
                    if d2:
                        ranges.append([d1.isoformat(), d2.isoformat()])
                        used[j] = used[k2] = used[k3] = True
                        continue
            if k2 is not None and tokens[k2] == "и":
                k3 = next_unused(k2 + 1, k2 + 2)
                if k3 is not None and DATE_TOKEN_RE.match(tokens[k3]):
                    d2 = _mkdate(tokens[k3])
                    if d2:
                        exact.extend([d1.isoformat(), d2.isoformat()])
                        used[j] = used[k2] = used[k3] = True
                        continue
            exact.append(d1.isoformat())
            used[j] = True

    # проход 5: предмет = всё оставшееся
    subject = " ".join(t for j, t in enumerate(tokens) if not used[j]).strip()
    if ranges or exact:
        subject = re.sub(r"\s+с$", "", subject)  # висячий предлог из-за переноса
    subject = re.sub(r"\s+", " ", subject).strip()

    if not subject:
        warn(f"пустой предмет: {' '.join(tokens)}")
    if teacher is None:
        warn(f"нет преподавателя: {kind} {subject}")
        teacher = ""
    if room is None:
        room = ""  # в исходном PDF ячейка аудитории может быть пустой
    if not ranges and not exact:
        warn(f"нет дат: {kind} {subject} {teacher}")

    lesson = {
        "kind": kind,
        "subject": subject,
        "teacher": teacher,
        "room": room,
        "ranges": ranges,
        "exact_dates": exact,
    }
    if link:
        lesson["link"] = link
    return lesson


def extract_slot_lessons(slot_blocks: list[dict]) -> list[dict]:
    """Разбирает блоки занятий слота в итоговые словари."""
    out = []
    for block in sorted(slot_blocks, key=lambda b: b["ymin"]):
        lesson = parse_lesson(block["tokens"])
        if lesson is not None:
            out.append(lesson)
    return out


def collect(slots: dict) -> dict:
    schedule = {}
    for day in DAY_ORDER:
        day_slots = [{"time": normalize_time(t),
                      "pair": PAIR_NUMBERS.get(t, 0),
                      "lessons": extract_slot_lessons(b)}
                     for t, b in slots[day].items()]
        schedule[day] = {"name": DAY_NAMES_RU[day], "slots": day_slots}
    return schedule


# --------------------------------- метод B: контроль по layout-тексту

def layout_ba_column(layout_text: str) -> str:
    """Весь текст колонки БА-231 из layout-выгрузки (контроль значений).

    Независим от координатного метода: границы колонки — середины между
    позициями заголовков групп в строке шапки.
    """
    lines = layout_text.splitlines()
    header_idx = next(i for i, ln in enumerate(lines)
                      if "БА" in ln and "БК" in ln and "БТ" in ln and "БЭ" in ln)
    header = lines[header_idx]
    idxs = [header.index(g) for g in ("БА", "БК", "БТ", "БЭ")]
    left = idxs[0] - (idxs[1] - idxs[0]) // 2   # левее начала контента БА
    right = (idxs[0] + idxs[1]) // 2            # середина БА..БК
    parts = [ln[left:right] for ln in lines[header_idx + 2:]]
    return re.sub(r"\s+", " ", "\n".join(parts))


def cross_check(schedule: dict, layout_text: str) -> list[str]:
    """Контроль значений: фамилия, аудитория, даты и начало предмета каждого
    занятия должны присутствовать в тексте колонки БА-231."""
    compact = layout_ba_column(layout_text)
    problems = []
    for day in DAY_ORDER:
        for slot in schedule[day]["slots"]:
            for lesson in slot["lessons"]:
                tag = f"{day} {slot['time']} [{lesson['kind']}] {lesson['subject'][:30]}"
                surname = lesson["teacher"].split()[0] if lesson["teacher"] else ""
                if surname and surname not in compact:
                    problems.append(f"{tag}: фамилия {surname} не найдена в layout")
                room = lesson["room"]
                if room and "\\" in room:
                    for part in room.split("\\"):
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
                head = " ".join(lesson["subject"].split()[:2])
                if head and head not in compact:
                    problems.append(f"{tag}: предмет {head!r} не найден")
    return problems


def sanity_checks(schedule: dict) -> list[str]:
    problems = []
    for day in DAY_ORDER:
        for slot in schedule[day]["slots"]:
            for lesson in slot["lessons"]:
                all_d = [x for r in lesson["ranges"] for x in r] + lesson["exact_dates"]
                for d in all_d:
                    dd = date.fromisoformat(d)
                    if not (SEMESTER_START <= dd <= SEMESTER_END):
                        problems.append(f"{day} {slot['time']}: дата {d} вне семестра "
                                        f"({lesson['subject'][:30]})")
                if not lesson["subject"]:
                    problems.append(f"{day} {slot['time']}: пустой предмет")
                if not lesson["teacher"]:
                    problems.append(f"{day} {slot['time']}: нет преподавателя "
                                    f"({lesson['subject'][:30]})")
    return problems


def main() -> None:
    pdf_arg = sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / "Загрузки/4curs2026.pdf")
    pdf_path = Path(pdf_arg)
    if not pdf_path.exists():
        print(f"PDF не найден: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Источник: {pdf_path}")
    layout_text, bbox_xml = run_pdftotext(pdf_path)
    words = parse_words(bbox_xml)
    visual_lines = [l for l in cluster_visual_lines(words) if l["y"] > 95]
    print(f"Слов: {len(words)}, визуальных строк: {len(visual_lines)}")

    day_anchors, time_anchors, content = collect_inputs(visual_lines)
    print(f"Маркеров дней: {len(day_anchors)}, якорей времени: {len(time_anchors)}, "
          f"строк контента: {len(content)}")

    sections = build_day_sections(day_anchors)
    global_rows = assign_time_anchors(time_anchors, sections)
    slots = assign_content(content, global_rows)
    schedule = collect(slots)

    total = sum(len(s["lessons"]) for d in schedule.values() for s in d["slots"])
    print(f"Занятий извлечено: {total}")

    print("\n=== Контрольная сверка с layout-текстом (метод B) ===")
    problems = cross_check(schedule, layout_text)
    if problems:
        for p in problems:
            print(f"  [B] {p}")
    else:
        print("  все занятия подтверждены независимой выгрузкой")

    print("\n=== Sanity-чеки ===")
    sproblems = sanity_checks(schedule)
    if sproblems:
        for p in sproblems:
            print(f"  [S] {p}")
    else:
        print("  отклонений нет")

    if WARNINGS:
        print(f"\nПредупреждений парсера: {len(WARNINGS)}")

    DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "group": "БА-231",
        "semester": "7 семестр 2026/2027",
        "semester_start": SEMESTER_START.isoformat(),
        "semester_end": SEMESTER_END.isoformat(),
        "schedule": schedule,
    }
    out_json = DATA_DIR / "schedule.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON: {out_json}")

    gen = ROOT / "schedule_data.py"
    gen.write_text(
        '"""\nСГЕНЕРИРОВАНО scripts/parse_pdf.py — руками не править.\n'
        f'Источник: {pdf_path.name}\n"""\n\n'
        "import json\nfrom pathlib import Path\n\n"
        "_data = json.loads((Path(__file__).parent / 'data' / 'schedule.json')"
        ".read_text(encoding='utf-8'))\n\n"
        "SCHEDULE = _data[\"schedule\"]\n"
        f"DAY_ORDER = {DAY_ORDER!r}\n"
        f"DAY_NAMES_RU = {json.dumps(DAY_NAMES_RU, ensure_ascii=False)}\n"
        "SEMESTER_START = _data[\"semester_start\"]\n"
        "SEMESTER_END = _data[\"semester_end\"]\n",
        encoding="utf-8",
    )
    print(f"Модуль: {gen}")

    print("\n=== Сводка для ручной проверки ===")
    for day in DAY_ORDER:
        cnt = sum(len(s["lessons"]) for s in schedule[day]["slots"])
        print(f"{schedule[day]['name']}: {cnt} занятий")
        for s in schedule[day]["slots"]:
            for l in s["lessons"]:
                dates = ", ".join([f"{r[0]}..{r[1]}" for r in l["ranges"]]
                                  + l["exact_dates"])
                print(f"  {s['time']} [{l['kind']}] {l['subject'][:44]:44} "
                      f"{l['teacher']:15} ауд.{l['room']:9} {dates}")


if __name__ == "__main__":
    main()
