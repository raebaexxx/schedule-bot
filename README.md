# schedule-bot

Telegram-бот с расписанием.

Возможности:

- расписание на сегодня / завтра / произвольную дату / неделю;
- **фильтрация по датам**: видны только пары, которые идут именно в этот день
  (диапазоны «с 07.09 по 09.11», отдельные даты «16.11», «30.11 и 07.12»);
- **утренний дайджест**: сам присылает расписание на день в выбранное время
  (по умолчанию 07:00 МСК, настраивается в `/settings`); если пар нет — не пишет;
- навигация ‹ › — листать дни и недели прямо под сообщением;
- номера пар (1–5), аудитории, преподаватели, ссылки на онлайн-пары;
- данные извлекаются **парсером из официального PDF** расписания.

## Запуск

Нужны Python 3.11+ и `pdftotext` (poppler-utils).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # вписать BOT_TOKEN от @BotFather
.venv/bin/python bot.py
```

Логи пишутся в `bot.log` (ротация 1 МБ × 3).

## Обновление расписания (новый семестр)

```bash
.venv/bin/python scripts/parse_pdf.py /путь/к/расписанию.pdf
```

Парсер извлекает колонку группы из PDF (координатный метод + DP-распределение
занятий по строкам таблицы), проверяет каждое занятие по независимой
layout-выгрузке и sanity-чекам, затем перегенерирует `data/schedule.json` и
`schedule_data.py`. Перед заменой данных сверьте сводку в выводе с PDF.

При смене семестра поправьте в `scripts/parse_pdf.py`: `SEMESTER_START`,
`SEMESTER_END` и при необходимости `EXPECTED_SLOTS` / `PAIR_NUMBERS`.

## Тесты

```bash
.venv/bin/python -m unittest discover -s tests
```

53 теста: разбор дат/ФИО/аудиторий/ссылок, регрессия полного пайплайна по
фикстурам из `data/`, фильтры дат, форматирование, хранилище подписок и
планировщик дайджеста.

## Развёртывание на VPS (systemd)

```bash
sudo apt update && sudo apt install -y python3-venv poppler-utils git
sudo adduser --disabled-password --gecos "" deploy || true
sudo git clone https://github.com/raebaexxx/schedule-bot.git /opt/schedule-bot
cd /opt/schedule-bot
sudo -u deploy python3 -m venv .venv
sudo -u deploy .venv/bin/pip install -r requirements.txt
sudo -u deploy cp .env.example .env   # вписать BOT_TOKEN
```

Установка сервиса (поправьте `User=` и пути в `schedule-bot.service` при необходимости):

```bash
sudo cp schedule-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now schedule-bot
journalctl -u schedule-bot -f
```

Сервис автоматически перезапускает бота при падении и стартует при загрузке.

## Локальный автозапуск (systemd, user-сервис)

```bash
mkdir -p ~/.config/systemd/user
cp schedule-bot.service ~/.config/systemd/user/   # поправьте пути: %h/...
systemctl --user daemon-reload
systemctl --user enable --now schedule-bot
journalctl --user -u schedule-bot -f
```

Чтобы сервис работал после выхода из системы: `sudo loginctl enable-linger $USER`.

## Структура

```
bot.py               входная точка, логирование, обработка ошибок
handlers.py          команды, inline-меню, навигация, /settings
formatter.py         рендер сообщений с фильтрацией по дате, дайджест
scheduler.py         asyncio-планировщик утреннего дайджеста
storage.py           подписки пользователей (data/users.json)
schedule_data.py     ГЕНЕРИРУЕТСЯ парсером — не править руками
data/schedule.json   данные расписания (артефакт парсера)
data/layout.txt,     выгрузки pdftotext (фикстуры для регрессионных тестов
data/bbox.xml         и контрольная сверка парсера)
scripts/parse_pdf.py парсер PDF -> schedule.json
tests/               unittest
```
