"""Тесты кабинета водителя: рейсы на день, посадочная ведомость, отметки (ФТ-8…ФТ-10)."""

from datetime import datetime, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking
from bookings.services import BookingError, complete_trip, mark_booking
from driver.views import build_manifest
from transport.models import Trip, Vehicle
from transport.search import free_seats

pytestmark = pytest.mark.django_db


@pytest.fixture
def today_trip(route, driver):
    """Рейс сегодня в 00:01: он уже отправился, значит его можно отмечать и завершать."""
    vehicle = Vehicle.objects.create(brand="Crafter", plate_number="AE 5678-7", seats=3)
    departure = timezone.make_aware(datetime.combine(timezone.localdate(), time(0, 1)))
    return Trip.objects.create(route=route, vehicle=vehicle, driver=driver, departure_at=departure)


def add_booking(trip, from_stop, to_stop, name="Анна", seats=1, status=Booking.Status.ACTIVE):
    return Booking.objects.create(
        trip=trip, from_stop=from_stop, to_stop=to_stop, seats_count=seats, status=status,
        passenger_name=name, passenger_phone="+375291234567",
        price=from_stop.price_to(to_stop) * seats,
    )


@pytest.fixture
def other_driver():
    return User.objects.create_user("+375291111112", "pass12345", role=User.Role.DRIVER)


# ---------- Рейсы на день (ФТ-8) ----------

def test_driver_sees_own_trips_for_day(client, driver, other_driver, trip):
    client.force_login(driver)
    day = timezone.localdate(trip.departure_at).isoformat()
    page = client.get(reverse("core:cabinet"), {"date": day}).content.decode()
    assert reverse("driver:manifest", args=[trip.pk]) in page

    client.force_login(other_driver)
    page = client.get(reverse("core:cabinet"), {"date": day}).content.decode()
    assert reverse("driver:manifest", args=[trip.pk]) not in page


# ---------- Посадочная ведомость (ФТ-9) ----------

def test_manifest_groups_passengers_by_stop(today_trip, stops):
    minsk, bobruisk, gomel = stops
    add_booking(today_trip, minsk, gomel, name="Ольга", seats=2)
    add_booking(today_trip, minsk, bobruisk, name="Павел")
    add_booking(today_trip, bobruisk, gomel, name="Мария")
    add_booking(today_trip, bobruisk, gomel, name="Отменил", status=Booking.Status.CANCELLED)
    add_booking(today_trip, minsk, bobruisk, name="Неявка", status=Booking.Status.NO_SHOW)

    rows, summary = build_manifest(today_trip)

    def names(bookings):
        return [b.passenger_name for b in bookings]

    assert names(rows[0].boarding) == ["Неявка", "Ольга", "Павел"]
    assert names(rows[1].boarding) == ["Мария"]       # отменённых в ведомости нет
    assert names(rows[1].leaving) == ["Павел"]         # кто не явился, тот не выходит
    assert names(rows[2].leaving) == ["Мария", "Ольга"]
    assert [row.on_board for row in rows] == [3, 3, 0]
    assert summary["expected"] == 4
    assert summary["no_show"] == 1
    assert summary["to_collect"] == 35 * 2 + 18 + 17


def test_manifest_access(client, today_trip, driver, other_driver):
    url = reverse("driver:manifest", args=[today_trip.pk])
    client.force_login(driver)
    assert client.get(url).status_code == 200
    client.force_login(other_driver)
    assert client.get(url).status_code == 404
    client.force_login(User.objects.create_user("+375293333333", "pass12345"))
    assert client.get(url).status_code == 404
    client.force_login(User.objects.create_user("+375292222222", "pass12345", role=User.Role.DISPATCHER))
    assert client.get(url).status_code == 200


# ---------- Отметки «сел» / «не явился» (ФТ-10) ----------

def test_mark_boarded_and_undo(client, today_trip, stops, driver):
    minsk, _, gomel = stops
    booking = add_booking(today_trip, minsk, gomel)
    client.force_login(driver)
    url = reverse("driver:mark", args=[booking.pk])

    response = client.post(url, {"status": "boarded"})
    assert response.url.endswith(f"#b{booking.pk}")
    booking.refresh_from_db()
    assert booking.status == Booking.Status.BOARDED

    client.post(url, {"status": "active"})  # водитель ошибся и снял отметку
    booking.refresh_from_db()
    assert booking.status == Booking.Status.ACTIVE


def test_no_show_frees_seat(today_trip, stops, driver):
    minsk, _, gomel = stops
    booking = add_booking(today_trip, minsk, gomel, seats=3)
    assert free_seats(today_trip, minsk, gomel) == 0
    mark_booking(booking, Booking.Status.NO_SHOW, driver)
    assert free_seats(today_trip, minsk, gomel) == 3


def test_cannot_undo_no_show_when_seat_resold(today_trip, stops, driver):
    minsk, bobruisk, gomel = stops
    booking = add_booking(today_trip, minsk, gomel, seats=3)
    mark_booking(booking, Booking.Status.NO_SHOW, driver)
    add_booking(today_trip, bobruisk, gomel, seats=1)  # место продали на участок
    with pytest.raises(BookingError, match="уже занято"):
        mark_booking(booking, Booking.Status.BOARDED, driver)


def test_marks_only_on_trip_day(trip, stops, driver):
    minsk, _, gomel = stops
    booking = add_booking(trip, minsk, gomel)  # рейс через неделю
    with pytest.raises(BookingError, match="в день рейса"):
        mark_booking(booking, Booking.Status.BOARDED, driver)


def test_other_driver_cannot_mark(client, today_trip, stops, other_driver):
    minsk, _, gomel = stops
    booking = add_booking(today_trip, minsk, gomel)
    client.force_login(other_driver)
    assert client.post(reverse("driver:mark", args=[booking.pk]), {"status": "boarded"}).status_code == 404
    booking.refresh_from_db()
    assert booking.status == Booking.Status.ACTIVE


def test_cancelled_booking_cannot_be_marked(today_trip, stops, driver):
    minsk, _, gomel = stops
    booking = add_booking(today_trip, minsk, gomel, status=Booking.Status.CANCELLED)
    with pytest.raises(BookingError, match="отменена"):
        mark_booking(booking, Booking.Status.BOARDED, driver)


# ---------- Завершение рейса ----------

def test_complete_trip_marks_rest_as_no_show(client, today_trip, stops, driver):
    minsk, _, gomel = stops
    boarded = add_booking(today_trip, minsk, gomel, status=Booking.Status.BOARDED)
    forgotten = add_booking(today_trip, minsk, gomel)
    client.force_login(driver)
    client.post(reverse("driver:complete", args=[today_trip.pk]))

    today_trip.refresh_from_db()
    boarded.refresh_from_db()
    forgotten.refresh_from_db()
    assert today_trip.status == Trip.Status.COMPLETED
    assert boarded.status == Booking.Status.BOARDED
    assert forgotten.status == Booking.Status.NO_SHOW
    # После завершения отмечать уже нельзя.
    with pytest.raises(BookingError):
        mark_booking(boarded, Booking.Status.ACTIVE, driver)


def test_cannot_complete_before_departure(today_trip, driver):
    today_trip.departure_at = timezone.now() + timedelta(hours=1)
    today_trip.save()
    with pytest.raises(BookingError, match="ещё не отправился"):
        complete_trip(today_trip, driver)
