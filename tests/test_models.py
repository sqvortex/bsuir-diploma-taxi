"""Проверки моделей данных: пользователи, маршруты, расписание, брони."""

from datetime import date, time
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from accounts.models import User
from bookings.models import Booking
from transport.models import Route, ScheduleTemplate

pytestmark = pytest.mark.django_db


# --- Пользователи (ФТ-1, ФТ-16) ---

def test_user_logs_in_by_phone_and_password_is_hashed():
    user = User.objects.create_user("+375297654321", "secret123")
    assert user.role == User.Role.PASSENGER
    assert user.password != "secret123"          # хранится только хеш
    assert user.check_password("secret123")


def test_phone_must_be_belarusian_format():
    user = User(phone="80291234567")
    with pytest.raises(ValidationError):
        user.full_clean()


def test_superuser_gets_admin_role():
    admin = User.objects.create_superuser("+375290000000", "admin12345")
    assert admin.is_admin_role and admin.is_staff


# --- Маршрут: цена и время по участку ---

def test_segment_price_and_time(stops):
    minsk, bobruisk, gomel = stops
    assert minsk.price_to(gomel) == Decimal("35")
    assert bobruisk.price_to(gomel) == Decimal("17")
    assert bobruisk.minutes_to(gomel) == 150


# --- Шаблон расписания (ФТ-12) ---

def test_template_runs_only_on_chosen_weekdays(route):
    template = ScheduleTemplate(
        route=route, departure_time=time(18, 0), weekdays="57", valid_from=date(2026, 1, 1)
    )
    assert template.runs_on(date(2026, 10, 16))       # пятница
    assert template.runs_on(date(2026, 10, 18))       # воскресенье
    assert not template.runs_on(date(2026, 10, 19))   # понедельник
    assert template.weekdays_display() == "пт, вс"


def test_template_respects_validity_period(route):
    template = ScheduleTemplate(
        route=route, departure_time=time(7, 0),
        valid_from=date(2026, 11, 1), valid_to=date(2026, 11, 30),
    )
    assert not template.runs_on(date(2026, 10, 31))
    assert template.runs_on(date(2026, 11, 15))
    assert not template.runs_on(date(2026, 12, 1))


# --- Рейс ---

def test_trip_capacity_and_arrival_time(trip, stops):
    assert trip.capacity == 18
    gomel = stops[2]
    assert (trip.time_at(gomel) - trip.departure_at).total_seconds() == 270 * 60


def test_only_driver_can_be_assigned_to_trip(trip):
    trip.driver = User.objects.create_user("+375293333333", "pass12345")  # пассажир
    with pytest.raises(ValidationError):
        trip.full_clean()


# --- Бронь (ФТ-4) ---

def make_booking(trip, from_stop, to_stop, seats=1):
    booking = Booking(
        trip=trip, passenger_name="Анна", passenger_phone="+375295555555",
        from_stop=from_stop, to_stop=to_stop, seats_count=seats, price=0,
    )
    booking.price = booking.calculate_price()
    return booking


def test_booking_price_for_segment_and_several_seats(trip, stops):
    booking = make_booking(trip, stops[1], stops[2], seats=2)
    booking.full_clean()
    assert booking.price == Decimal("34")


def test_booking_from_stop_must_be_before_to_stop(trip, stops):
    booking = make_booking(trip, stops[2], stops[0])
    with pytest.raises(ValidationError):
        booking.full_clean()


def test_booking_stops_must_belong_to_trip_route(trip, stops):
    other_route = Route.objects.create(name="Другой")
    foreign_stop = other_route.route_stops.create(stop=stops[0].stop, order=1)
    booking = make_booking(trip, foreign_stop, stops[2])
    with pytest.raises(ValidationError):
        booking.full_clean()
