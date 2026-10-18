"""
Генерирует историю перевозок за прошлые дни: выполненные рейсы и брони по ним.
На этой истории обучается модель прогноза (этап 6). Правила спроса описаны
в forecast/simulation.py.

Запуск:  python manage.py generate_history --days 540
Повторный запуск не дублирует рейсы: дни, где рейс уже есть, пропускаются.
"""

import random
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from bookings.models import Booking
from forecast.simulation import simulate_bookings
from transport.models import ScheduleTemplate, Trip


class Command(BaseCommand):
    help = "Создаёт историю выполненных рейсов и броней за прошлые дни для обучения прогноза"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=540, help="за сколько прошлых дней (по умолчанию 540, это 1,5 года)")
        parser.add_argument("--seed", type=int, default=7, help="зерно случайных чисел, чтобы история повторялась")

    @transaction.atomic
    def handle(self, *args, days, seed, **options):
        rng = random.Random(seed)
        today = timezone.localdate()
        templates = list(
            ScheduleTemplate.objects.select_related("route", "default_vehicle", "default_driver")
            .filter(route__is_active=True, default_vehicle__isnull=False)
        )
        if not templates:
            self.stderr.write("Нет шаблонов расписания с машиной. Сначала запустите: python manage.py load_demo")
            return

        existing = set(Trip.objects.values_list("route_id", "departure_at"))
        trips_created = bookings_created = 0
        for template in templates:
            stops = list(template.route.ordered_stops())
            for shift in range(days, 0, -1):
                day = today - timedelta(days=shift)
                # Срок действия шаблона не проверяем: история старше самого шаблона.
                if str(day.isoweekday()) not in template.weekdays:
                    continue
                departure = timezone.make_aware(datetime.combine(day, template.departure_time))
                if (template.route_id, departure) in existing:
                    continue
                trip = Trip.objects.create(
                    route=template.route, template=template, departure_at=departure,
                    vehicle=template.default_vehicle, driver=template.default_driver,
                    status=Trip.Status.COMPLETED,
                )
                trips_created += 1
                bookings = simulate_bookings(rng, trip, stops)
                Booking.objects.bulk_create(bookings, batch_size=1000)
                bookings_created += len(bookings)

        self.stdout.write(self.style.SUCCESS(
            f"Готово: новых рейсов в истории {trips_created}, броней {bookings_created}."
        ))
