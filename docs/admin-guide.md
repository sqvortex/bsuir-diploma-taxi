# Руководство администратора Viago

Как установить сайт, настроить его, запускать по расписанию служебные команды и восстанавливать данные.
Рекомендуемая система сервера: Linux (Ubuntu 22.04 или новее), 2 ядра, 2 ГБ памяти, 20 ГБ диска.

## 1. Установка

### Через Docker (проще всего)
Нужен [Docker](https://www.docker.com/) с Compose. В папке проекта:

```bash
docker compose up --build -d                          # сайт на http://127.0.0.1:8000/, база PostgreSQL 16
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py load_demo    # по желанию: демо-данные
docker compose exec web python manage.py generate_history   # по желанию: история для прогноза
docker compose exec web python manage.py train_forecast
```

Сайт внутри контейнера запускается через gunicorn (3 процесса), данные базы лежат в томе `pgdata` и переживают перезапуск.

### Без Docker
Нужны Python 3.12 или новее и PostgreSQL 16 (для проб подойдёт SQLite, тогда ничего настраивать не надо).

```bash
python -m venv .venv && source .venv/bin/activate     # в Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser                      # телефон +375XXXXXXXXX и пароль
gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 3  # рабочий запуск (в Windows и для разработки: python manage.py runserver)
```

`runserver` предназначен только для разработки: под нагрузкой он заметно медленнее (см. [испытания](test-cases.md)).

## 2. Настройки (переменные окружения)

| Переменная | Что делает | По умолчанию |
|------------|------------|--------------|
| `DJANGO_SECRET_KEY` | секретный ключ сайта; на рабочем сервере обязательно задать свой длинный случайный | небезопасный ключ для разработки |
| `DJANGO_DEBUG` | `0` выключает режим отладки; на рабочем сервере обязательно `0` | `1` |
| `DJANGO_ALLOWED_HOSTS` | адреса сайта через запятую, например `viago.example.by` | `localhost,127.0.0.1` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | подключение к PostgreSQL; пока `POSTGRES_DB` не задана, используется файл SQLite `db.sqlite3` | SQLite |
| `SITE_NAME` | название сервиса на страницах и в письмах | `Viago` |
| `SITE_URL` | адрес сайта для ссылок в письмах | `http://127.0.0.1:8000` |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | отправка писем; по умолчанию письма печатаются в консоль | консоль |

Для настоящей почты задайте `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, адрес и порт SMTP-сервера, логин, пароль и `EMAIL_USE_TLS=1`.

Правила бронирования меняются в `config/settings.py`: `BOOKING_CANCEL_HOURS` (за сколько часов можно отменить, по умолчанию 2), `BOOKING_MAX_SEATS` (мест в одной брони, по умолчанию 5), `FORECAST_CACHE_SECONDS` (сколько секунд помнить прогноз в поиске).

## 3. Что запускать по расписанию

Эти команды нужно запускать автоматически: в Linux через `cron` (`crontab -e`), в Windows через «Планировщик заданий».
Пример для cron (папка проекта `/srv/viago`, окружение `.venv`):

```cron
# каждую ночь в 03:00: резервная копия базы
0 3 * * *  cd /srv/viago && .venv/bin/python manage.py backup_db
# каждый день в 04:00: создать рейсы на ближайшие 14 дней по шаблонам расписания
0 4 * * *  cd /srv/viago && .venv/bin/python manage.py generate_trips --days 14
# каждый день в 18:00: напомнить пассажирам о завтрашних поездках
0 18 * * * cd /srv/viago && .venv/bin/python manage.py send_reminders
# раз в неделю, в воскресенье в 05:00: переобучить прогноз на свежих данных
0 5 * * 0  cd /srv/viago && .venv/bin/python manage.py train_forecast
```

В Docker перед каждой командой добавьте `docker compose exec -T web`.

## 4. Резервные копии и восстановление

Команда `python manage.py backup_db` кладёт копию базы в папку `backups/` с датой в названии и хранит последние 14 копий
(`--keep 30` хранит 30, `--dir D:\backups` меняет папку). Копируйте папку `backups/` ещё и на другой диск или сервер:
копия на том же диске не спасёт при поломке диска.

**SQLite.** Файл копии `viago-ДАТА.sqlite3` это обычная база. Чтобы восстановить, остановите сайт и замените `db.sqlite3` этим файлом.

**PostgreSQL без Docker.** Копия делается программой `pg_dump` (она должна быть установлена; другой путь задаётся переменной `PG_DUMP`).
Восстановление в чистую базу:

```bash
createdb -U postgres viago_restore
pg_restore -U postgres -d viago_restore --no-owner backups/viago-20261018-030000.dump
```

Проверьте данные в `viago_restore`, потом переключите сайт на неё (`POSTGRES_DB`) или замените рабочую базу.

**PostgreSQL в Docker.** Образ сайта не содержит `pg_dump`, поэтому копию делает контейнер базы:

```bash
docker compose exec -T db pg_dump -U viago --format=custom viago > backups/viago-$(date +%Y%m%d).dump
docker compose exec -T db pg_restore -U viago -d viago --clean --no-owner < backups/viago-20261018.dump   # восстановление
```

Проверено на практике: копия демо-базы (43 тысячи броней) восстановилась в новую базу, число броней совпало.

## 5. Прогноз свободных мест

- Пока модель не обучена, сайт работает как обычно, только без прогноза.
- `generate_history --days 540` создаёт искусственную историю рейсов и броней: нужна, пока нет настоящих данных. Когда накопится реальная статистика, историю лучше не создавать, а обучать модель на настоящих данных: `train_forecast`.
- `train_forecast` печатает таблицу ошибок модели и простого среднего и сохраняет модель в `var/forecast_model.joblib`. В Docker папка проекта подключена к контейнеру, поэтому `var/` и `backups/` остаются в ней и переживают пересоздание контейнера.
- После обучения перезапустите сайт (в gunicorn: `kill -HUP` мастер-процесса или `docker compose restart web`): он загружает модель при старте.

## 6. Пользователи и роли

Раздел «Администрирование» (адрес `/admin/`) доступен администратору:
- «Пользователи»: создать пользователя, выдать роль (пассажир, водитель, диспетчер, администратор), отключить доступ (снять «Активный»).
- Водителей и диспетчеров создаёт администратор: при самостоятельной регистрации человек всегда становится пассажиром.
- Пароли хранятся только в виде хеша, увидеть их нельзя, можно только задать новый.

## 7. Проверка работы

- `pytest` запускает все автоматические тесты (около ста). На SQLite один тест пропускается: одновременная покупка последнего места проверяется только на PostgreSQL.
- `python scripts/load_test.py --users 50` проверяет, что поиск рейсов отвечает не дольше 2 секунд при 50 одновременных пользователях. Сайт должен быть запущен через gunicorn, в базе демо-данные.
- Таблица испытаний по каждому требованию ТЗ: [docs/test-cases.md](test-cases.md).

## 8. Обновление

```bash
git pull
pip install -r requirements.txt     # в Docker: docker compose up --build -d
python manage.py migrate
```

Перед обновлением сделайте резервную копию (`backup_db`).
