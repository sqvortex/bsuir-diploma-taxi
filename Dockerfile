# Образ сайта Viago: Python и библиотеки из requirements.txt.
FROM python:3.12-slim

# Python не пишет .pyc-файлы и сразу выводит логи в консоль.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала ставим библиотеки: этот шаг кешируется и не повторяется, если менялся только код.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
