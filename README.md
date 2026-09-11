# schedule-bot

Telegram-бот расписания ЕТИ МГТУ «СТАНКИН» на основе официальных PDF:
**общий бот всех курсов** (`bot_all.py`) — 4 курса и 17 групп, включая
ускоренные группы `(у)`.

Возможности:

- расписание на сегодня / завтра / произвольную дату / неделю;
- **выбор группы**: `/start` → курс → группа, `/groups` — сменить
  (выбор запоминается);
- **Mini App (веб-приложение) в стиле iOS Liquid Glass**: `/webapp` или кнопка
  меню — живой интерфейс с подсветкой текущей пары и таймерами
  («идёт · до конца 25 мин», «через 40 мин»), пикер курса/группы
  (нажми на название группы в шапке);
- **фильтрация по датам**: видны только пары, которые идут именно в этот день
  (диапазоны «с 07.09 по 09.11», отдельные даты «16.11», «30.11 и 07.12»);
- **утренний дайджест**: сам присылает расписание дня в выбранное время
  (по умолчанию 07:00 МСК, настраивается в `/settings`);
- навигация ‹ › — листать дни и недели прямо под сообщением;
- **поиск** `/find` по предмету/преподавателю по всем курсам и группам;
- `/admin` — статистика, рассылка, статус, обновление PDF прямо из Telegram;
- уведомления об изменениях расписания: при обновлении JSON бот сам
  рассылает дифф («ПН 14:05: − … / + …») всем, кого это касается;
- номера пар (1–7), аудитории (включая виртуальные), преподаватели,
  ссылки на онлайн-пары;
- данные извлекаются **парсером из официальных PDF** расписания.

## Запуск

Нужны Python 3.11+ и `pdftotext` (poppler-utils).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # вписать BOT_TOKEN_ALL
.venv/bin/python bot_all.py
```

Лог: `bot_all.log` (ротация 1 МБ × 3).

## Обновление расписания (новый семестр)

```bash
.venv/bin/python scripts/parse_all.py /путь/к/папке_с_pdf
```

Парсер работает по координатам PDF (`pdftotext -bbox-layout`): колонки групп
детектируются автоматически, занятия раскладываются по строкам таблицы
DP-оптимизацией. Каждое занятие проверяется по независимой layout-выгрузке
(метод B) и sanity-чекам. Перед заменой данных сверьте сводку в выводе с PDF.

При смене семестра поправьте в `scripts/parse_pdf.py` (единый источник,
используется и `parse_all.py`): `SEMESTER_START`, `SEMESTER_END`; сетку
звонков — в `PAIR_NUMBERS`, сетку слотов — в `EXPECTED_SLOTS`.

## Тесты

```bash
.venv/bin/python -m unittest discover -s tests
```

61 тест: разбор дат/ФИО/аудиторий/ссылок (включая «сэндвич»-преподавателей,
виртуальные аудитории и slash-аудитории), раскладка якорей по дням (утечки,
суббота), чистка склеек subject, регрессия полного пайплайна по всем 4 курсам,
учебный год для /date, хранилище подписок и профилей, планировщик дайджеста.

## Развёртывание на VPS (systemd)

```bash
sudo apt update && sudo apt install -y python3-venv poppler-utils git
sudo adduser --disabled-password --gecos "" deployall || true
sudo git clone https://github.com/raebaexxx/schedule-bot.git /opt/schedule-all
cd /opt/schedule-all
sudo -u deployall python3 -m venv .venv
sudo -u deployall .venv/bin/pip install -r requirements.txt
sudo -u deployall cp .env.example .env   # вписать BOT_TOKEN_ALL

sudo cp schedule-all.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now schedule-all
journalctl -u schedule-all -f
```

Сервис перезапускает бота при падении (Restart=always с защитой от
крашлупа) и стартует при загрузке.

## Веб-версия без Telegram (GitHub Pages)

Расписание доступно как обычный сайт: **https://raebaexxx.github.io/schedule-bot/**

Это зеркало Mini App: тот же webapp + `data/schedule_all.json`, деплоится
автоматически workflow `pages.yml` при каждом пуше в main. Обновишь JSON —
пушишь, сайт обновляется. Работает из РФ без VPN.

## Mini App (веб-приложение)

Статика в `webapp/` (vanilla HTML/CSS/JS, без сборки): liquid glass на
`backdrop-filter` + SVG-рефракция для Chromium (Telegram Android), frost-фоллбэк
для iOS WebView. Данные — `data/schedule_all.json`, отдаются nginx'ом.

Развёртывание (пример для домена `app.example.com`):

1. DNS: A-запись `app` → IP сервера.
2. `sudo apt install -y nginx certbot python3-certbot-nginx`; **порядок
   важен**: если включаете ufw — сначала `ufw allow 22/tcp` (SSH!), затем
   `ufw allow 80,443/tcp` и только потом `ufw enable`. Если на сервере уже
   есть другие сервисы (например 3x-ui/xray) — проверьте их порты
   (`ss -tlnp`) и откройте их до включения firewall.
3. nginx-сайт: root → `/opt/schedule-all/webapp`, `/data/` → алиас на
   `/opt/schedule-all/data/` (`schedule_all.json` —
   Cache-Control: no-store).
4. `sudo certbot --nginx -d app.example.com`.
5. В `.env`: `WEBAPP_URL=https://app.example.com[:порт][/all/]`,
   restart — бот сам выставит кнопку меню (`set_chat_menu_button`).
6. (опционально) @BotFather → Bot Settings → Configure Mini App → включить
   Main Mini App с тем же URL.

## Структура

```
bot_all.py                 общий бот: точки входа, меню команд, Mini App-кнопка,
                           глобальный обработчик ошибок
handlers_all.py            команды, выбор курса/группы, навигация ‹ ›, /settings
handlers_admin.py          /admin: статистика, рассылка, статус, PDF-обновление
formatter.py               рендер с фильтрацией по датам, дайджест
search.py                  /find: поиск по предмету/преподавателю
scheduler.py               asyncio-планировщик утреннего дайджеста
notify.py / changes.py     уведомления об изменениях расписания
storage.py                 подписки и выбор групп (data/users_all.json),
                           атомарная JSON-запись
schedule_all.py            обёртка над data/schedule_all.json
data/schedule_all.json     данные: все курсы (артефакт parse_all.py)
data/pending_changes.json  очередь изменений (создаётся парсером,
                           рассылается и удаляется ботом)
scripts/parse_pdf.py       БИБЛИОТЕКА разбора занятия (исп. parse_all.py);
                           standalone-режим устарел
scripts/parse_all.py       парсер 4 PDF -> все курсы/группы
webapp/                    Mini App: liquid glass интерфейс, пикер групп
tests/                     unittest
PLAN.md / ANALYSIS.md      паспорт проекта, анализ парсинга
```
