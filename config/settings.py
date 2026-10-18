"""
Настройки проекта Viago.

Секретные и зависящие от сервера значения берутся из переменных окружения,
чтобы не хранить их в коде. Для локальной разработки всё работает
без настройки: база SQLite в файле db.sqlite3.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Ключ для подписи сессий и CSRF-токенов. На сервере задаётся через окружение.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-only-insecure-key-change-me",
)

# Режим отладки включён только при разработке.
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Приложения проекта
    "accounts",   # пользователи и роли
    "transport",  # остановки, маршруты, автопарк, расписание и рейсы
    "bookings",   # бронирования мест
    "core",       # общие страницы: главная, поиск, кабинеты
    "dispatch",   # панель диспетчера: маршруты, автопарк, расписание, рейсы
    "driver",     # кабинет водителя: посадочная ведомость
    "forecast",   # прогноз свободных мест и рекомендации
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# База данных.
# Если задана переменная POSTGRES_DB, подключаемся к PostgreSQL,
# иначе используем файл SQLite (удобно для первых шагов).
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# Своя модель пользователя: вход по номеру телефона, у каждого есть роль.
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Язык и время: интерфейс на русском, часовой пояс Беларуси.
LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Minsk"
USE_I18N = True
USE_TZ = True


STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Правила бронирования (ФТ-5): за сколько часов до отправления ещё можно отменить бронь.
BOOKING_CANCEL_HOURS = 2
# Сколько мест можно взять в одной брони.
BOOKING_MAX_SEATS = 5


# Вход и выход: куда отправлять пользователя.
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:cabinet"
LOGOUT_REDIRECT_URL = "core:home"


# Название сервиса. Меняется здесь одной строкой и подставляется на всех страницах.
# Цвета сайта лежат в одном месте: static/css/theme.css (блок :root).
SITE_NAME = os.environ.get("SITE_NAME", "Viago")
SITE_TAGLINE = "Твой путь по Беларуси"
# Окончание названия, которое в логотипе выделяется цветом (Via + go). Пустая строка: без выделения.
SITE_LOGO_ACCENT = "go"

# Файл обученной модели прогноза (создаётся командой python manage.py train_forecast).
FORECAST_MODEL_PATH = BASE_DIR / "var" / "forecast_model.joblib"
