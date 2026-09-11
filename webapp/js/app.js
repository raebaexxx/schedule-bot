/*
 * app.js — Mini App «Расписание БА-231».
 * Данные: data/schedule.json (артефакт scripts/parse_pdf.py).
 * Всё рендерится на клиенте; время расписания — Europe/Moscow.
 */
(function () {
  "use strict";

  /* ---------- Telegram / демо-режим ---------- */

  var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

  function applyTheme() {
    var dark = tg
      ? tg.colorScheme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.body.classList.toggle("dark", dark);
  }

  if (tg) {
    tg.ready();
    tg.expand();
    if (tg.setHeaderColor) tg.setHeaderColor("bg_color");
    applyTheme();
    tg.onEvent("themeChanged", applyTheme);
  } else {
    applyTheme();
    var banner = document.createElement("div");
    banner.className = "banner";
    banner.textContent = "Демо-режим в браузере — открой бота в Telegram для полного вида";
    document.getElementById("app").prepend(banner);
  }

  function haptic(kind) {
    if (tg && tg.HapticFeedback) {
      try { tg.HapticFeedback.impactOccurred(kind || "light"); } catch (e) { /* noop */ }
    }
  }

  /* ---------- время МСК ---------- */

  var DAY_KEYS = ["sunday", "monday", "tuesday", "wednesday", "thursday",
                  "friday", "saturday"];
  var DW_SHORT = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

  function mskTodayISO() {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Moscow",
      year: "numeric", month: "2-digit", day: "2-digit"
    }).format(new Date());
  }

  function mskISO(offsetDays) {
    var d = new Date(Date.now() + (offsetDays || 0) * 86400000);
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Moscow",
      year: "numeric", month: "2-digit", day: "2-digit"
    }).format(d);
  }

  function weekdayOfISO(iso) {
    return new Date(iso + "T12:00:00+03:00").getUTCDay(); // 0 = воскресенье
  }

  function fmtDateHuman(iso) {
    var d = new Date(iso + "T12:00:00+03:00");
    var months = ["января", "февраля", "марта", "апреля", "мая", "июня",
                  "июля", "августа", "сентября", "октября", "ноября", "декабря"];
    return d.getUTCDate() + " " + months[d.getUTCMonth()];
  }

  function slotDate(iso, hm) {
    return new Date(iso + "T" + hm + ":00+03:00");
  }

  /* ---------- состояние ---------- */

  var state = {
    data: null,           // {courses: ...} либо одиночное расписание (legacy)
    view: "day",          // day | week | date | picker
    selected: mskTodayISO(),
    course: null,
    group: null
  };

  try {
    var saved = JSON.parse(localStorage.getItem("group") || "null");
    if (saved && saved.course && saved.group) {
      state.course = saved.course;
      state.group = saved.group;
    }
  } catch (e) { /* noop */ }

  var content = document.getElementById("content");
  var footer = document.getElementById("footer");

  function currentGroup() {
    if (!state.data || !state.data.courses) return null;
    if (!state.course || !state.group ||
        !state.data.courses[state.course] ||
        !state.data.courses[state.course].groups[state.group]) {
      return null;
    }
    var c = state.data.courses[state.course];
    return {
      course: state.course,
      id: state.group,
      display: c.groups[state.group].display || state.group,
      semester: c.semester,
      days: c.groups[state.group].days
    };
  }

  function saveGroup() {
    if (state.course && state.group) {
      localStorage.setItem("group",
        JSON.stringify({course: state.course, group: state.group}));
    }
  }

  function pluralPairs(n) {
    if (n === 1) return "1 пара";
    if (n >= 2 && n <= 4) return n + " пары";
    return n + " пар";
  }

  /* ---------- данные ---------- */

  function lessonsForDate(iso) {
    var g = currentGroup();
    if (!g) return [];
    var wd = weekdayOfISO(iso);
    var dayKey = DAY_KEYS[wd];
    var day = (g.days && g.days[dayKey]) || null;
    if (!day) return [];
    return day.slots.map(function (slot) {
      var lessons = slot.lessons.filter(function (l) { return isActive(l, iso); });
      return { time: slot.time, pair: slot.pair, lessons: lessons };
    }).filter(function (slot) { return slot.lessons.length > 0; });
  }

  function isActive(lesson, iso) {
    var ranges = lesson.ranges || [];
    for (var i = 0; i < ranges.length; i++) {
      if (iso >= ranges[i][0] && iso <= ranges[i][1]) return true;
    }
    return (lesson.exact_dates || []).indexOf(iso) !== -1;
  }

  function safeHref(url) {
    return /^https?:\/\//i.test(url || "") ? url : null;
  }

  function countLessons(slots) {
    return slots.reduce(function (acc, s) { return acc + s.lessons.length; }, 0);
  }

  /* текущая и следующая пара (только если выбран сегодняшний день) */
  function liveStatus(slots, iso) {
    var now = Date.now();
    var result = { live: null, next: null, minutesToNext: null, liveLeft: null };
    for (var i = 0; i < slots.length; i++) {
      var parts = slots[i].time.split("-");
      var start = slotDate(iso, parts[0].replace(".", ":"));
      var end = slotDate(iso, parts[1].replace(".", ":"));
      if (now >= start && now < end) {
        result.live = { slot: slots[i], left: Math.max(1, Math.round((end - now) / 60000)) };
      } else if (now < start && !result.next) {
        result.next = { slot: slots[i], inMin: Math.round((start - now) / 60000) };
      }
    }
    return result;
  }

  function humanMinutes(total) {
    if (total < 60) return total + " мин";
    return Math.floor(total / 60) + " ч " + (total % 60) + " мин";
  }

  /* ---------- рендер ---------- */

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function glassCard(cls) {
    var card = el("div", "glass glass--soft " + (cls || ""));
    card.appendChild(el("i", "glass-stroke"));
    return card;
  }

  function renderLessonCard(slot) {
    var lesson = slot.lessons.length === 1 ? slot.lessons[0] : null;
    var card = glassCard("lesson");

    var timeCol = el("div", "lesson__time");
    timeCol.appendChild(el("div", "pair-num", String(slot.pair || "?")));
    timeCol.appendChild(el("time", null, slot.time));
    card.appendChild(timeCol);

    var body = el("div", "lesson__body");

      if (lesson) {
        body.appendChild(el("div", "lesson__subject", lesson.subject));
        body.appendChild(el("span", "lesson__kind", lesson.kind));
        var meta = el("div", "lesson__meta");
        if (lesson.teacher) {
          var t = el("span", null, lesson.teacher);
          meta.appendChild(t);
        }
        var room = el("span", null);
        room.appendChild(document.createTextNode("ауд. "));
        var rb = el("b", null, lesson.room || "—");
        room.appendChild(rb);
        meta.appendChild(room);
        body.appendChild(meta);
        var href = safeHref(lesson.link);
        if (href) {
          var a = el("a", "lesson__link", "Подключиться онлайн");
          a.href = href;
          a.target = "_blank";
          a.rel = "noopener";
          body.appendChild(a);
        }
      } else {
        /* несколько пар в одном слоте — раскрываем списком */
        slot.lessons.forEach(function (l) {
          var line = el("div", "lesson__subject", l.subject);
          body.appendChild(line);
          var meta = el("div", "lesson__meta");
          if (l.kind) meta.appendChild(el("span", null, l.kind));
          if (l.teacher) meta.appendChild(el("span", null, l.teacher));
          meta.appendChild(el("span", null, "ауд. " + (l.room || "—")));
          body.appendChild(meta);
          var href2 = safeHref(l.link);
          if (href2) {
            var a2 = el("a", "lesson__link", "Онлайн");
            a2.href = href2;
            a2.target = "_blank";
            a2.rel = "noopener";
            body.appendChild(a2);
          }
          body.appendChild(el("div", null, "\u00a0"));
        });
      }

    card.appendChild(body);
    return card;
  }

  function renderDay(iso) {
    content.innerHTML = "";
    var slots = lessonsForDate(iso);
    var isToday = iso === mskTodayISO();

    var title = el("div", "section-title");
    title.appendChild(el("span", null,
      DW_SHORT[weekdayOfISO(iso)].toUpperCase() + ", " + fmtDateHuman(iso) +
      (isToday ? " · сегодня" : "")));

    var nav = el("div", "date-nav");
    var prev = el("button", "nav-btn", "‹");
    var next = el("button", "nav-btn", "›");
    prev.addEventListener("click", function () { shiftDay(-1); });
    next.addEventListener("click", function () { shiftDay(1); });
    nav.appendChild(prev);
    nav.appendChild(next);
    title.appendChild(nav);
    content.appendChild(title);

    if (slots.length === 0) {
      var empty = glassCard("empty-card");
      empty.appendChild(el("div", "big", "Занятий нет"));
      empty.appendChild(el("div", null,
        weekdayOfISO(iso) === 0 ? "Воскресенье — отдыхаем" : "В этот день пар нет"));
      content.appendChild(empty);
      return;
    }

    var status = isToday ? liveStatus(slots, iso) : { live: null, next: null };

    slots.forEach(function (slot) {
      var card = renderLessonCard(slot);
      if (status.live && status.live.slot === slot) {
        card.classList.add("is-live");
        var badge = el("span", "badge badge--live");
        badge.appendChild(el("span", "dot"));
        badge.appendChild(document.createTextNode(
          "идёт · до конца " + status.live.left + " мин"));
        card.querySelector(".lesson__body").appendChild(badge);
      } else if (status.next && status.next.slot === slot) {
        card.classList.add("is-next");
        var nb = el("span", "badge badge--next",
          "через " + humanMinutes(status.next.inMin));
        card.querySelector(".lesson__body").appendChild(nb);
      }
      content.appendChild(card);
    });
  }

  function renderWeek(mondayISO) {
    content.innerHTML = "";
    var wd = weekdayOfISO(mondayISO);
    var mondayOffset = (wd === 0) ? -6 : 1 - wd;
    var monday = mskShiftISO(mondayISO, mondayOffset);

    var title = el("div", "section-title");
    title.appendChild(el("span", null, "Неделя"));
    var nav = el("div", "date-nav");
    var prev = el("button", "nav-btn", "‹");
    var next = el("button", "nav-btn", "›");
    prev.addEventListener("click", function () { state.selected = mskShiftISO(monday, -7); render(); });
    next.addEventListener("click", function () { state.selected = mskShiftISO(monday, 7); render(); });
    nav.appendChild(prev);
    nav.appendChild(next);
    title.appendChild(nav);
    content.appendChild(title);

    for (var i = 0; i < 6; i++) {
      var iso = mskShiftISO(monday, i);
      var slots = lessonsForDate(iso);
      var block = glassCard("day-block");
      var h3 = el("h3");
      h3.appendChild(el("span", null,
        DW_SHORT[weekdayOfISO(iso)].toUpperCase() + " · " + fmtDateHuman(iso)));
      h3.appendChild(el("span", "cnt",
        slots.length ? pluralPairs(countLessons(slots)) : ""));
      block.appendChild(h3);

      var ul = el("ul");
      if (!slots.length) {
        ul.appendChild(el("li", "empty", "—"));
      } else {
        slots.forEach(function (slot) {
          slot.lessons.forEach(function (l) {
            var li = el("li");
            li.appendChild(el("span", "t", slot.time.replace(".", ":")));
            var s = el("span", "s", l.subject);
            li.appendChild(s);
          });
        });
      }
      block.appendChild(ul);
      block.style.cursor = "pointer";
      (function (dateISO) {
        block.addEventListener("click", function () {
          haptic("light");
          state.view = "day";
          state.selected = dateISO;
          render();
        });
      })(iso);
      content.appendChild(block);
    }
  }

  function renderDatePicker() {
    content.innerHTML = "";

    var title = el("div", "section-title");
    title.appendChild(el("span", null, "Выбери день"));
    content.appendChild(title);

    var strip = el("div", "dates");
    for (var i = -3; i <= 10; i++) {
      var iso = mskISO(i);
      var chip = el("button", "date-chip" + (iso === state.selected ? " is-active" : ""));
      chip.appendChild(el("div", "dw", DW_SHORT[weekdayOfISO(iso)]));
      chip.appendChild(el("div", "dm", iso.slice(8) + "." + iso.slice(5, 7)));
      (function (dateISO) {
        chip.addEventListener("click", function () {
          haptic("light");
          state.selected = dateISO;
          render();
          var active = strip.querySelector(".is-active");
          if (active) active.scrollIntoView({ block: "nearest", inline: "center" });
        });
      })(iso);
      strip.appendChild(chip);
    }
    content.appendChild(strip);

    /* под лентой — выбранный день */
    var slots = lessonsForDate(state.selected);
    var subtitle = el("div", "section-title");
    subtitle.appendChild(el("span", null,
      DW_SHORT[weekdayOfISO(state.selected)].toUpperCase() + ", " +
      fmtDateHuman(state.selected) +
      (slots.length ? " — " + pluralPairs(countLessons(slots)) : "")));
    content.appendChild(subtitle);

    if (!slots.length) {
      var empty = glassCard("empty-card");
      empty.appendChild(el("div", "big", "Занятий нет"));
      content.appendChild(empty);
      return;
    }
    slots.forEach(function (slot) { content.appendChild(renderLessonCard(slot)); });
  }

  function shiftDay(delta) {
    haptic("light");
    state.selected = mskShiftISO(state.selected, delta);
    render();
  }

  function mskShiftISO(iso, days) {
    var d = new Date(iso + "T12:00:00+03:00");
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  }

  /* ---------- вкладки ---------- */

  function render() {
    var tabs = document.getElementById("tabs");
    if (tabs) tabs.style.display = (state.view === "picker") ? "none" : "";
    if (state.view === "picker" || !currentGroup()) {
      renderPicker();
      updateBackButton();
      return;
    }
    if (state.view === "week") {
      renderWeek(state.selected);
    } else if (state.view === "date") {
      renderDatePicker();
    } else {
      renderDay(state.selected);
    }
    updateBackButton();
    updateHeader();
  }

  /* ---------- пикер курса и группы ---------- */

  function renderNoData(message) {
    content.innerHTML = "";
    var card = glassCard("empty-card");
    card.appendChild(el("div", "big", message || "Расписание недоступно"));
    var retry = el("button", "nav-btn", "↻");
    retry.style.width = "auto";
    retry.style.padding = "8px 18px";
    retry.style.borderRadius = "999px";
    retry.addEventListener("click", load);
    card.appendChild(retry);
    content.appendChild(card);
  }

  function renderPicker() {
    content.innerHTML = "";
    if (!state.data || !state.data.courses ||
        !Object.keys(state.data.courses).length) {
      renderNoData("Расписание пока недоступно");
      return;
    }
    var card = glassCard("picker");
    var pickingCourse = !state.course || !state.data.courses[state.course];

    if (!pickingCourse) {
      /* смена группы: сразу показываем группы текущего курса */
      card.appendChild(el("div", "picker__title", "Смени группу"));
      var gRow = el("div", "group-list");
      var gids = Object.keys(state.data.courses[state.course].groups);
      gids.forEach(function (gid) {
        var gBtn = el("button", "date-chip group-chip"
                      + (state.group === gid ? " is-active" : ""),
                      state.data.courses[state.course].groups[gid].display);
        gBtn.addEventListener("click", function () {
          haptic("light");
          state.group = gid;
          saveGroup();
          setView("day");
          updateHeader();
          render();
        });
        gRow.appendChild(gBtn);
      });
      card.appendChild(gRow);

      var back = el("button", "banner", "← выбрать другой курс");
      back.style.marginTop = "10px";
      back.addEventListener("click", function () {
        state.course = null;
        state.group = null;
        render();
      });
      card.appendChild(back);
      content.appendChild(card);
      return;
    }

    /* первоначальный выбор: курс → группа */
    card.appendChild(el("div", "picker__title", "Выбери курс"));
    var courseRow = el("div", "course-row");
    Object.keys(state.data.courses).sort().forEach(function (course) {
      var btn = el("button", "date-chip");
      btn.appendChild(el("div", "dw", course + " курс"));
      btn.appendChild(el("div", "dm", course_title_short(course)));
      btn.addEventListener("click", function () {
        haptic("light");
        state.course = course;
        state.group = null;
        render();
      });
      courseRow.appendChild(btn);
    });
    card.appendChild(courseRow);

    if (state.course) {
      card.appendChild(el("div", "picker__title", "Выбери группу"));
      var gList = el("div", "group-list");
      Object.keys(state.data.courses[state.course].groups).forEach(function (gid) {
        var gBtn = el("button", "date-chip group-chip",
                      state.data.courses[state.course].groups[gid].display);
        gBtn.addEventListener("click", function () {
          haptic("light");
          state.group = gid;
          saveGroup();
          setView("day");
          updateHeader();
          render();
        });
        gList.appendChild(gBtn);
      });
      card.appendChild(gList);
    }
    content.appendChild(card);
  }

  function course_title_short(course) {
    var c = state.data.courses[course];
    var parts = c.semester ? c.semester.split("семестр") : [];
    return parts.length > 1 ? parts[0].trim() + " сем." : (c.semester || "");
  }

  function syncTabs() {
    document.querySelectorAll(".tab").forEach(function (b) {
      b.classList.toggle("is-active", b.dataset.tab === state.view);
    });
  }

  function setView(view) {
    state.view = view;
    syncTabs();
  }

  document.querySelectorAll(".tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (btn.classList.contains("is-active")) return;
      if (!state.data) return; // данные ещё грузятся — рендерить нечего
      haptic("light");
      setView(btn.dataset.tab);
      render();
    });
  });

  function updateBackButton() {
    if (!tg || !tg.BackButton) return;
    var hide = (state.view === "day" && state.selected === mskTodayISO()) ||
               (state.view === "picker" && !state.course);
    if (hide) {
      tg.BackButton.hide();
    } else {
      tg.BackButton.show();
    }
  }

  /* клик по чипу группы в шапке — открыть пикер */
  var groupChip = document.getElementById("groupChip");
  if (groupChip) {
    groupChip.style.cursor = "pointer";
    groupChip.addEventListener("click", function () {
      if (!state.data) return;
      haptic("light");
      setView((state.view === "picker") ? "day" : "picker");
      render();
    });
  }

  if (tg && tg.BackButton) {
    tg.BackButton.onClick(function () {
      haptic("light");
      if (!state.data) return;
      if (state.view !== "picker") {
        state.selected = mskTodayISO();
      }
      setView("day");
      render();
    });
  }

  /* ---------- загрузка данных ---------- */

  function showError() {
    content.innerHTML = "";
    var card = glassCard("empty-card");
    card.appendChild(el("div", "big", "Не удалось загрузить расписание"));
    var retry = el("button", "nav-btn", "↻");
    retry.style.width = "auto";
    retry.style.padding = "8px 18px";
    retry.style.borderRadius = "999px";
    retry.addEventListener("click", load);
    card.appendChild(retry);
    content.appendChild(card);
  }

  function load() {
    var urls = ["data/schedule_all.json", "../data/schedule_all.json"];
    var attempt = 0;

    function tryNext() {
      if (attempt >= urls.length) { showError(); return; }
      var url = urls[attempt++];
      var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
      var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 15000) : null;
      fetch(url, { cache: "no-store", signal: ctrl ? ctrl.signal : undefined })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          return r.json();
        })
        .then(function (json) {
          if (timer) clearTimeout(timer);
          state.data = json;
          if (state.data.courses && !currentGroup()) {
            setView("picker");
          }
          updateHeader();
          render();
        })
        .catch(function (err) {
          if (timer) clearTimeout(timer);
          tryNext();
        });
    }
    tryNext();
  }

  function updateHeader() {
    var g = currentGroup();
    var sub = document.getElementById("headerSub");
    if (g) {
      if (sub) sub.textContent = g.semester || "";
      var chip = document.getElementById("groupChip");
      if (chip) chip.textContent = g.display;
    } else if (sub) {
      sub.textContent = "Выберите группу";
    }
    if (footer) {
      var gen = (state.data && state.data.generated_at) || "";
      var m = gen.match(/(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
      footer.textContent = m ? ("расписание обновлено: " + m[3] + "." + m[2] +
        "." + m[1] + " в " + m[4] + ":" + m[5] + " МСК") : "";
    }
  }

  load();
})();
