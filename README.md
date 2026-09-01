# schedule-bot

Telegram-боты с расписанием ЕТИ МГТУ «СТАНКИН» на основе официальных PDF:

- **Бот группы БА-231** (`bot.py`) — личный бот, 7 семестр 2026/2027;
- **Общий бот всех курсов** (`bot_all.py`) — все 4 курса и 17 групп,
  включая ускоренные группы `(у)`.

Возможности:

- расписание на сегодня / завтра / произвольную дату / неделю;
- **выбор группы**: `/start` → курс → группа, `/groups` — сменить
  (в общем боте; выбор запоминается);
- **Mini App (веб-приложение) в стиле iOS Liquid Glass**: `/webapp` или кнопка
  меню — живой интерфейс с подсветкой текущей пары и таймерами
  («идёт · до конца 25 мин», «через 40 мин»), пикер курса/группы
  (нажми на название группы в шапке);
- **фильтрация по датам**: видны только пары, которые идут именно в этот день
  (диапазоны «с 07.09 по 09.11», отдельные даты «16.11», «30.11 и 07.12»);
- **утренний дайджест** (в боте группы): сам присылает расписание на день
  в выбранное время (по умолчанию 07:00 МСК, настраивается в `/settings`);
- навигация ‹ › — листать дни и недели прямо под сообщением;
- номера пар (1–7), аудитории (включая виртуальные), преподаватели,
  ссылки на онлайн-пары;
- данные извлекаются **парсером из официальных PDF** расписания.

## Запуск

Нужны Python 3.11+ и `pdftotext` (poppler-utils).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # вписать BOT_TOKEN и/или BOT_TOKEN_ALL
.venv/bin/python bot.py       # бот группы БА-231
.venv/bin/python bot_all.py   # общий бот (все курсы/группы)
```

Логи: `bot.log` и `bot_all.log` (ротация 1 МБ × 3).

## Обновление расписания (новый семестр)

```bash
# один PDF -> одна группа (бот БА-231)
.venv/bin/python scripts/parse_pdf.py /путь/к/расписанию.pdf

# все 4 PDF -> все курсы и группы (общий бот)
.venv/bin/python scripts/parse_all.py /путь/к/папке_с_pdf
```

Парсер работает по координатам PDF (`pdftotext -bbox-layout`): колонки групп
детектируются автоматически, занятия раскладываются по строкам таблицы
DP-оптимизацией. Каждое занятие проверяется по независимой layout-выгрузке
(метод B) и sanity-чекам. Перед заменой данных сверьте сводку в выводе с PDF.

При смене семестра поправьте в `scripts/parse_pdf.py` / `parse_all.py`:
`SEMESTER_START`, `SEMESTER_END`; сетку звонков смотрите в `PAIR_NUMBERS`.

## Тесты

```bash
.venv/bin/python -m unittest discover -s tests
```

67 тестов: разбор дат/ФИО/аудиторий/ссылок (включая «сэндвич»-преподавателей,
виртуальные аудитории и slash-аудитории), регрессия полного пайплайна по всем
4 курсам (636 занятий), фильтры дат, форматирование, хранилище подписок,
планировщик дайджеста.

## Развёртывание на VPS (systemd)

Оба бота работают на одном сервере из двух клонов репозитория.

```bash
sudo apt update && sudo apt install -y python3-venv poppler-utils git
sudo adduser --disabled-password --gecos "" deploy || true
sudo git clone https://github.com/raebaexxx/schedule-bot.git /opt/schedule-bot
cd /opt/schedule-bot
sudo -u deploy python3 -m venv .venv
sudo -u deploy .venv/bin/pip install -r requirements.txt
sudo -u deploy cp .env.example .env   # вписать BOT_TOKEN
```

Для общего бота — второй клон и свой токен:

```bash
sudo git clone https://github.com/raebaexxx/schedule-bot.git /opt/schedule-all
cd /opt/schedule-all && sudo python3 -m venv .venv && \
  sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env        # вписать BOT_TOKEN_ALL
```

Сервисы: `schedule-bot.service` (группа) и `schedule-all.service` (общий).
Пример установки:

```bash
sudo cp schedule-bot.service /etc/systemd/system/   # поправьте User= и пути
sudo systemctl daemon-reload
sudo systemctl enable --now schedule-bot
journalctl -u schedule-bot -f
```

Сервис автоматически перезапускает бота при падении и стартует при загрузке.

## Mini App (веб-приложение)

Статика в `webapp/` (vanilla HTML/CSS/JS, без сборки): liquid glass на
`backdrop-filter` + SVG-рефракция для Chromium (Telegram Android), frost-фоллбэк
для iOS WebView. Данные — `data/schedule.json` (одна группа) или
`data/schedule_all.json` (все курсы), отдаются nginx'ом.

Развёртывание (пример для домена `app.example.com`):

1. DNS: A-запись `app` → IP сервера.
2. `sudo apt install -y nginx certbot python3-certbot-nginx`; **порядок
   важен**: если включаете ufw — сначала `ufw allow 22/tcp` (SSH!), затем
   `ufw allow 80,443/tcp` и только потом `ufw enable`. Если на сервере уже
   есть другие сервисы (например 3x-ui/xray) — проверьте их порты
   (`ss -tlnp`) и откройте их до включения firewall.
3. nginx-сайт: root → `/opt/schedule-bot/webapp`, `/data/` → алиас на
   `/opt/schedule-bot/data/`, `/data/schedule_all.json` → алиас на
   `/opt/schedule-all/data/schedule_all.json` (Cache-Control: no-store).
4. `sudo certbot --nginx -d app.example.com`.
5. В `.env` каждого бота: `WEBAPP_URL=https://app.example.com[/all/]`,
   restart — бот сам выставит кнопку меню (`set_chat_menu_button`).
6. (опционально) @BotFather → Bot Settings → Configure Mini App → включить
   Main Mini App с тем же URL.

## Структура

```
bot.py                 бот группы БА-231 (личный)
bot_all.py             общий бот: все курсы и группы
handlers.py /          команды, меню, навигация, /settings (личный)
handlers_all.py        команды, выбор курса/группы (общий)
formatter.py /         рендер с фильтрацией по дате, дайджест
formatter_all.py       рендер по произвольной группе
scheduler.py           asyncio-планировщик утреннего дайджеста
storage.py             подписки (data/users.json) и выбор групп (users_all.json)
schedule_data.py       ГЕНЕРИРУЕТСЯ parse_pdf.py — не править руками
schedule_all.py        обёртка над data/schedule_all.json (генерируется)
data/schedule.json     данные: БА-231 (артефакт parse_pdf.py)
data/schedule_all.json данные: все курсы (артефакт parse_all.py)
data/layout.txt,       выгрузки pdftotext (фикстуры для регрессионных тестов
data/bbox.xml           и контрольная сверка парсеров)
scripts/parse_pdf.py   парсер одного PDF (одна группа)
scripts/parse_all.py   парсер 4 PDF (все курсы и группы)
webapp/                Mini App: liquid glass интерфейс, пикер групп
tests/                 unittest
```
