"""Общие заготовки (фикстуры) для тестов: маршрут с остановками, машина, рейс."""

from datetime import date, time
from decimal import Decimal

import pytest

from accounts.models import User
from transport.models import Route, RouteStop, ScheduleTemplate, Stop, Trip, Vehicle


@pytest.fixture
def route():
    """Маршрут Минск – Бобруйск – Гомель."""
    route = Route.objects.create(name="Минск – Гомель")
    data = [("Минск", 0, "0"), ("Бобруйск", 120, "18"), ("Гомель", 270, "35")]
    for order, (city, minutes, price) in enumerate(data, start=1):
        stop = Stop.objects.create(city=city, name="Автовокзал")
        RouteStop.objects.create(
            route=route, stop=stop, order=order,
            minutes_from_start=minutes, price_from_start=Decimal(price),
        )
    return route


@pytest.fixture
def stops(route):
    """Остановки маршрута списком: [Минск, Бобруйск, Гомель]."""
    return list(route.ordered_stops())


@pytest.fixture
def driver():
    return User.objects.create_user("+375291111111", "pass12345", role=User.Role.DRIVER)


@pytest.fixture
def trip(route, driver):
    vehicle = Vehicle.objects.create(brand="Sprinter", plate_number="AB 1234-7", seats=18)
    template = ScheduleTemplate.objects.create(
        route=route, departure_time=time(7, 30), valid_from=date(2026, 1, 1)
    )
    return Trip.objects.create(
        route=route, template=template, vehicle=vehicle, driver=driver,
        departure_at=template.departure_on(date(2026, 11, 2)),
    )
