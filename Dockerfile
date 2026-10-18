# Образ сайта Viago: Python и библиотеки из requirements.txt.
FROM python:3.12-slim

# Python не пишет .pyc-файлы и сразу выводит логи в консоль.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Клиент PostgreSQL 16 (той же версии, что и база): нужен команде backup_db, она вызывает pg_dump.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-common \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

# Сначала ставим библиотеки: этот шаг кешируется и не повторяется, если менялся только код.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
