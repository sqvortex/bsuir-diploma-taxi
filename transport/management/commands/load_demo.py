"""
Заполняет базу примером данных, чтобы было что посмотреть на сайте и в админке.

Запуск:  python manage.py load_demo
Команду можно запускать повторно: уже созданные записи не дублируются.

Создаются пользователи всех ролей (пароль у всех demo12345):
    +375291111111, +375291111112, +375291111113  водители
    +375292222222  диспетчер
    +375293333333  пассажир
"""

import random
from datetime import time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking
from transport.models import Route, RouteStop, ScheduleTemplate, Stop, Vehicle
from transport.schedule import generate_trips

DEMO_PASSWORD = "demo12345"

# Маршруты: название и остановки (город, остановка, минут от начала, цена от начала в BYN)
ROUTES = {
    "Минск – Гомель": [
        ("Минск", "Автовокзал Восточный", 0, "0"),
        ("Бобруйск", "Автовокзал", 120, "18"),
        ("Жлобин", "Автостанция", 180, "25"),
        ("Гомель", "Автовокзал", 270, "35"),
    ],
    "Минск – Пинск": [
        ("Минск", "Автовокзал Центральный", 0, "0"),
        ("Барановичи", "Автовокзал", 110, "17"),
        ("Ивацевичи", "Автостанция", 165, "24"),
        ("Пинск", "Автовокзал", 240, "32"),
    ],
    "Минск – Могилёв": [
        ("Минск", "Автовокзал Восточный", 0, "0"),
        ("Березино", "Автостанция", 75, "11"),
        ("Могилёв", "Автовокзал", 165, "22"),
    ],
}

# Время отправления рейсов каждого маршрута
DEPARTURES = [time(7, 30), time(12, 0), time(17, 45)]

VEHICLES = [
    ("Mercedes Sprinter", "AB 1234-7", 18),
    ("Volkswagen Crafter", "AE 5678-7", 16),
    ("Ford Transit", "AK 9012-7", 14),
]

PASSENGER_NAMES = ["Анна", "Дмитрий", "Ольга", "Сергей", "Мария", "Алексей", "Елена", "Павел"]


class Command(BaseCommand):
    help = "Создаёт демо-данные: маршруты, автопарк, пользователей всех ролей, рейсы на неделю и брони"

    def get_user(self, phone, first_name, last_name, role):
        user, _ = User.objects.update_or_create(
            phone=phone,
            defaults={"first_name": first_name, "last_name": last_name, "role": role},
        )
        user.set_password(DEMO_PASSWORD)  # у демо-пользователей всегда один и тот же пароль
        user.save()
        return user

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(42)  # одинаковые «случайные» брони при каждом запуске

        # У каждого маршрута свой водитель, чтобы рейсы одного водителя не пересекались по времени.
        drivers = [
            self.get_user("+375291111111", "Иван", "Петров", User.Role.DRIVER),
            self.get_user("+375291111112", "Олег", "Козлов", User.Role.DRIVER),
            self.get_user("+375291111113", "Пётр", "Новиков", User.Role.DRIVER),
        ]
        self.get_user("+375292222222", "Наталья", "Сидорова", User.Role.DISPATCHER)
        passenger = self.get_user("+375293333333", "Анна", "Ковалёва", User.Role.PASSENGER)

        vehicles = [
            Vehicle.objects.get_or_create(
                plate_number=plate, defaults={"brand": brand, "seats": seats}
            )[0]
            for brand, plate, seats in VEHICLES
        ]

        trips_created = bookings_created = 0
        for route_index, (route_name, stops) in enumerate(ROUTES.items()):
            route, _ = Route.objects.get_or_create(name=route_name)
            for order, (city, name, minutes, price) in enumerate(stops, start=1):
                stop, _ = Stop.objects.get_or_create(city=city, name=name)
                RouteStop.objects.get_or_create(
                    route=route, order=order,
                    defaults={"stop": stop, "minutes_from_start": minutes,
                              "price_from_start": Decimal(price)},
                )
            route_stops = list(route.ordered_stops())
            vehicle = vehicles[route_index % len(vehicles)]
            driver = drivers[route_index % len(drivers)]

            for departure_time in DEPARTURES:
                template, _ = ScheduleTemplate.objects.get_or_create(
                    route=route, departure_time=departure_time,
                    defaults={"weekdays": "1234567", "valid_from": timezone.localdate()},
                )
                # Машина и водитель обновляются и у уже созданных шаблонов и рейсов,
                # чтобы повторный запуск исправлял старые демо-данные.
                template.default_vehicle, template.default_driver = vehicle, driver
                template.save()
                template.trips.update(vehicle=vehicle, driver=driver)
                # Рейсы на неделю вперёд создаём так же, как это делает диспетчер.
                result = generate_trips(timezone.localdate(), timezone.localdate() + timedelta(days=6), [template])
                trips_created += result.created
                for trip in template.trips.filter(departure_at__date__gte=timezone.localdate()):
                    shift = (timezone.localdate(trip.departure_at) - timezone.localdate()).days
                    if not trip.bookings.exists():
                        # Демо-пассажир едет Минск – Гомель утренним рейсом завтра и через 4 дня.
                        rider = passenger if (route_index == 0 and departure_time == DEPARTURES[0]
                                              and shift in (1, 4)) else None
                        bookings_created += self.add_bookings(trip, route_stops, rider)

        self.stdout.write(self.style.SUCCESS(
            f"Готово: маршрутов {len(ROUTES)}, новых рейсов {trips_created}, "
            f"новых броней {bookings_created}. Пароль демо-пользователей: {DEMO_PASSWORD}"
        ))

    def add_bookings(self, trip, route_stops, passenger):
        """Несколько броней на рейс, чтобы загрузка выглядела реалистично (+ бронь passenger, если он передан)."""
        count = 0
        free = trip.capacity
        for _ in range(random.randint(2, 7)):
            start = random.randint(0, len(route_stops) - 2)
            end = random.randint(start + 1, len(route_stops) - 1)
            seats = random.choice([1, 1, 1, 2])
            if seats > free:
                break
            booking = Booking(
                trip=trip,
                passenger_name=random.choice(PASSENGER_NAMES),
                passenger_phone=f"+37529{random.randint(1000000, 9999999)}",
                from_stop=route_stops[start], to_stop=route_stops[end],
                seats_count=seats, price=0,
            )
            booking.price = booking.calculate_price()
            booking.save()
            free -= seats
            count += 1
        # Бронь демо-пассажира, чтобы в его кабинете были поездки.
        if passenger and free:
            booking = Booking(
                trip=trip, passenger=passenger,
                passenger_name=passenger.first_name, passenger_phone=passenger.phone,
                from_stop=route_stops[0], to_stop=route_stops[-1], seats_count=1, price=0,
            )
            booking.price = booking.calculate_price()
            booking.save()
            count += 1
        return count
