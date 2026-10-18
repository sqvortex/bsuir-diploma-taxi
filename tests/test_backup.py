"""Тесты резервного копирования базы (раздел 4.3 ТЗ)."""

import sqlite3
import subprocess

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.mark.skipif(connection.vendor != "sqlite", reason="копия файла SQLite проверяется на SQLite")
def test_sqlite_backup_is_restorable(tmp_path, settings, transactional_db):
    User.objects.create_user("+375291234567", "pass12345")
    call_command("backup_db", dir=str(tmp_path), stdout=None)
    [copy] = list(tmp_path.glob("viago-*.sqlite3"))
    restored = sqlite3.connect(copy)
    assert restored.execute("select count(*) from accounts_user").fetchone()[0] == 1
    restored.close()


def test_old_backups_are_removed(tmp_path):
    for day in range(1, 6):
        (tmp_path / f"viago-2026010{day}-030000.sqlite3").write_text("x")
    if connection.vendor == "sqlite":
        call_command("backup_db", dir=str(tmp_path), keep=3, stdout=None)
        names = sorted(path.name for path in tmp_path.glob("viago-*"))
        assert len(names) == 3 and "viago-20260101-030000.sqlite3" not in names
    else:
        from core.management.commands.backup_db import Command
        assert Command().remove_old(tmp_path, 3) == 2


@pytest.mark.skipif(connection.vendor != "postgresql", reason="проверка pg_dump только для PostgreSQL")
def test_postgres_backup_calls_pg_dump(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["env"]["PGPASSWORD"]))
        open(command[command.index("--file") + 1], "wb").write(b"dump")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    call_command("backup_db", dir=str(tmp_path), stdout=None)
    [(command, _)] = calls
    assert command[0] == "pg_dump" and "--format=custom" in command
    assert len(list(tmp_path.glob("viago-*.dump"))) == 1


@pytest.mark.skipif(connection.vendor != "postgresql", reason="проверка pg_dump только для PostgreSQL")
def test_missing_pg_dump_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PG_DUMP", "no-such-program")
    with pytest.raises(CommandError, match="pg_dump"):
        call_command("backup_db", dir=str(tmp_path), stdout=None)
