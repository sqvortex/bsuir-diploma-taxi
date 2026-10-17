"""
Заполняет базу примером данных, чтобы было что посмотреть в админке.

Запуск:  python manage.py load_demo
Команду можно запускать повторно: уже созданные записи не дублируются.
"""

from datetime import date, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from transport.models import Route, RouteStop, ScheduleTemplate, Stop, Trip, Vehicle

# Маршрут Минск – Гомель через Бобруйск и Жлобин:
# (город, остановка, минут от начала, цена от начала в BYN)
MINSK_GOMEL = [
    ("Минск", "Автовокзал Восточный", 0, "0"),
    ("Бобруйск", "Автовокзал", 120, "18"),
    ("Жлобин", "Автостанция", 180, "25"),
    ("Гомель", "Автовокзал", 270, "35"),
]


class Command(BaseCommand):
    help = "Создаёт демонстрационные маршрут, машину, водителя, шаблон и рейсы на неделю"

    @transaction.atomic
    def handle(self, *args, **options):
        route, _ = Route.objects.get_or_create(name="Минск – Гомель")
        for order, (city, name, minutes, price) in enumerate(MINSK_GOMEL, start=1):
            stop, _ = Stop.objects.get_or_create(city=city, name=name)
            RouteStop.objects.get_or_create(
                route=route, order=order,
                defaults={"stop": stop, "minutes_from_start": minutes,
                          "price_from_start": Decimal(price)},
            )

        vehicle, _ = Vehicle.objects.get_or_create(
            plate_number="AB 1234-7", defaults={"brand": "Mercedes Sprinter", "seats": 18}
        )
        driver, created = User.objects.get_or_create(
            phone="+375291111111",
            defaults={"first_name": "Иван", "last_name": "Водитель", "role": User.Role.DRIVER},
        )
        if created:
            driver.set_password("driver12345")
            driver.save()

        template, _ = ScheduleTemplate.objects.get_or_create(
            route=route, departure_time=time(7, 30),
            defaults={"weekdays": "1234567", "valid_from": date.today(),
                      "default_vehicle": vehicle, "default_driver": driver},
        )

        # Пока генерации рейсов по шаблону нет (это следующий этап),
        # создаём рейсы на 7 дней вперёд прямо здесь.
        trips_created = 0
        for shift in range(7):
            day = date.today() + timedelta(days=shift)
            if template.runs_on(day):
                _, created = Trip.objects.get_or_create(
                    route=route, departure_at=template.departure_on(day),
                    defaults={"template": template, "vehicle": vehicle, "driver": driver},
                )
                trips_created += created

        self.stdout.write(self.style.SUCCESS(
            f"Готово: маршрут «{route}», новых рейсов: {trips_created}."
        ))
