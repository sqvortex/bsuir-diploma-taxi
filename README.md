# МаршрутБай

Дипломный проект БГУИР: программное средство бронирования мест в межгородских
маршрутных такси по расписанию с прогнозированием свободных мест.

Стек: Python 3.12+, Django 5.2, PostgreSQL 16 (локально пока SQLite), pytest.
План этапов: [docs/plan.md](docs/plan.md).

## Как запустить у себя

```bash
# 1. Создать виртуальное окружение и установить библиотеки
python -m venv .venv
source .venv/bin/activate          # в Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Создать базу данных (файл db.sqlite3) по моделям
python manage.py migrate

# 3. Создать администратора (спросит телефон в формате +375XXXXXXXXX и пароль)
python manage.py createsuperuser

# 4. Загрузить пример: маршрут Минск – Гомель, машину, водителя и рейсы на неделю
python manage.py load_demo

# 5. Запустить сайт и открыть http://127.0.0.1:8000/admin/
python manage.py runserver
```

## Тесты

```bash
pytest
```

## Как устроен код

| Папка | Что внутри |
|-------|------------|
| `config/` | настройки проекта и адреса страниц |
| `accounts/` | пользователь с входом по телефону и ролями |
| `transport/` | остановки, маршруты, автопарк, шаблоны расписания, рейсы |
| `bookings/` | брони мест на участках маршрута |
| `tests/` | автоматические тесты (pytest) |
| `docs/` | план и заметки к пояснительной записке |

## PostgreSQL

Чтобы работать с PostgreSQL вместо SQLite, задайте переменные окружения
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`.
Если `POSTGRES_DB` не задана, используется SQLite.
