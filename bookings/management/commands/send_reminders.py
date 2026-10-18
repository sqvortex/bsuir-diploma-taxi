"""
Рассылает напоминания о завтрашних поездках (ФТ-7).
Запускать раз в сутки, например вечером:  python manage.py send_reminders
Повторный запуск никому не пишет дважды.
"""

from django.core.management.base import BaseCommand

from bookings.notifications import send_reminders


class Command(BaseCommand):
    help = "Отправляет пассажирам напоминание о поездке завтра"

    def handle(self, *args, **options):
        sent = send_reminders()
        self.stdout.write(self.style.SUCCESS(f"Отправлено напоминаний: {sent}."))
