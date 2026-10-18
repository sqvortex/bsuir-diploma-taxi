"""
Резервная копия базы данных (раздел 4.3 ТЗ: копирование раз в сутки).

    python manage.py backup_db              # копия в папку backups/, хранятся последние 14
    python manage.py backup_db --keep 30    # хранить 30 копий
    python manage.py backup_db --dir D:\\backups

SQLite: копируется файл базы средствами самой SQLite, это безопасно даже при работающем сайте.
PostgreSQL: вызывается pg_dump (должен быть установлен; другой путь задаётся переменной PG_DUMP).
Запускать раз в сутки планировщиком (cron в Linux, «Планировщик заданий» в Windows).
Как восстановить базу из копии, написано в docs/admin-guide.md.
"""

import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

PREFIX = "viago-"


class Command(BaseCommand):
    help = "Делает резервную копию базы данных и удаляет старые копии"

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=None, help="куда класть копии (по умолчанию settings.BACKUP_DIR)")
        parser.add_argument("--keep", type=int, default=14, help="сколько последних копий хранить (по умолчанию 14)")

    def handle(self, *args, dir, keep, **options):
        folder = Path(dir or settings.BACKUP_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        engine = connection.vendor

        if engine == "sqlite":
            target = folder / f"{PREFIX}{stamp}.sqlite3"
            self.backup_sqlite(target)
        elif engine == "postgresql":
            target = folder / f"{PREFIX}{stamp}.dump"
            self.backup_postgres(target)
        else:
            raise CommandError(f"Резервное копирование для базы «{engine}» не поддерживается.")

        removed = self.remove_old(folder, keep)
        size = target.stat().st_size / 1024
        self.stdout.write(self.style.SUCCESS(f"Копия сохранена: {target} ({size:.0f} КБ). Удалено старых копий: {removed}."))

    def backup_sqlite(self, target):
        # Копируем через уже открытое соединение Django: так работает и с файлом, и с базой в памяти (тесты).
        connection.ensure_connection()
        destination = sqlite3.connect(target)
        try:
            with destination:
                connection.connection.backup(destination)
        finally:
            destination.close()

    def backup_postgres(self, target):
        db = connection.settings_dict
        command = [
            os.environ.get("PG_DUMP", "pg_dump"), "--format=custom", "--file", str(target),
            "--host", db["HOST"] or "localhost", "--port", str(db["PORT"] or 5432),
            "--username", db["USER"], db["NAME"],
        ]
        env = {**os.environ, "PGPASSWORD": db["PASSWORD"] or ""}
        try:
            subprocess.run(command, env=env, check=True, capture_output=True, text=True)
        except FileNotFoundError:
            raise CommandError("Не найдена программа pg_dump. Установите клиент PostgreSQL или задайте путь в PG_DUMP.")
        except subprocess.CalledProcessError as error:
            target.unlink(missing_ok=True)
            raise CommandError(f"pg_dump завершился с ошибкой: {error.stderr.strip()}")

    def remove_old(self, folder, keep):
        copies = sorted(folder.glob(f"{PREFIX}*"), key=lambda path: path.name, reverse=True)
        old = copies[max(keep, 1):]
        for path in old:
            path.unlink()
        return len(old)
