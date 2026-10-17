"""
Создаёт рейсы по шаблонам расписания на несколько дней вперёд.

Запуск:  python manage.py generate_trips            (на 14 дней)
         python manage.py generate_trips --days 30

На сервере эту команду можно ставить в планировщик раз в сутки,
тогда расписание всегда будет заполнено на две недели вперёд.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from transport.schedule import generate_trips


class Command(BaseCommand):
    help = "Создаёт рейсы по шаблонам расписания на N дней вперёд"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=14, help="на сколько дней вперёд (по умолчанию 14)")

    def handle(self, *args, **options):
        today = timezone.localdate()
        result = generate_trips(today, today + timedelta(days=options["days"] - 1))
        self.stdout.write(self.style.SUCCESS(
            f"Создано рейсов: {result.created}, уже были: {result.existing}."
        ))
