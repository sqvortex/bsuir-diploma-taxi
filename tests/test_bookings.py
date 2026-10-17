"""Тесты бронирования: создание, свободные места, отмена, бронь диспетчером, двойная продажа."""

import threading
import time
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from bookings import services
from bookings.models import Booking
from bookings.services import BookingError, cancel_booking, create_booking
from transport.models import Route, RouteStop, Stop, Trip, Vehicle
from transport.search import free_seats, free_seats_by_segment

pytestmark = pytest.mark.django_db


@pytest.fixture
def passenger():
    return User.objects.create_user(
        "+375293333333", "pass12345", role=User.Role.PASSENGER, first_name="Анна"
    )


@pytest.fixture
def dispatcher():
    return User.objects.create_user("+375292222222", "pass12345", role=User.Role.DISPATCHER)


def book(trip, from_stop, to_stop, seats=1, passenger=None):
    return create_booking(
        trip=trip, from_stop=from_stop, to_stop=to_stop, seats_count=seats,
        passenger_name="Тест", passenger_phone="+375291234567",
        passenger=passenger, created_by=passenger,
    )


# ---------- Создание брони и свободные места ----------

def test_booking_takes_seats_and_price(trip, stops, passenger):
    minsk, bobruisk, gomel = stops
    booking = book(trip, minsk, gomel, seats=2, passenger=passenger)
    assert booking.price == Decimal("70")  # 35 BYN × 2 места
    assert booking.status == Booking.Status.ACTIVE
    assert free_seats(trip, minsk, gomel) == 16


def test_same_seat_sold_on_separate_segments(trip, stops):
    """Одно место продаётся на Минск – Бобруйск и Бобруйск – Гомель (ФТ-4)."""
    minsk, bobruisk, gomel = stops
    trip.vehicle.seats = 1
    trip.vehicle.save()
    book(trip, minsk, bobruisk)
    book(trip, bobruisk, gomel)
    with pytest.raises(BookingError):
        book(trip, minsk, gomel)


def test_not_enough_seats(trip, stops):
    minsk, _, gomel = stops
    book(trip, minsk, gomel, seats=17)
    with pytest.raises(BookingError, match="осталось мест: 1"):
        book(trip, minsk, gomel, seats=2)


def test_cannot_book_cancelled_or_departed_trip(trip, stops):
    minsk, _, gomel = stops
    trip.status = Trip.Status.CANCELLED
    trip.save()
    with pytest.raises(BookingError, match="отменён"):
        book(trip, minsk, gomel)

    trip.status = Trip.Status.SCHEDULED
    trip.departure_at = timezone.now() - timedelta(minutes=5)
    trip.save()
    with pytest.raises(BookingError, match="отправилась"):
        book(trip, minsk, gomel)


def test_wrong_stop_order(trip, stops):
    minsk, _, gomel = stops
    with pytest.raises(BookingError):
        book(trip, gomel, minsk)


def test_free_seats_by_segment_matches_free_seats(trip, stops):
    minsk, bobruisk, gomel = stops
    book(trip, minsk, bobruisk, seats=3)
    by_segment = free_seats_by_segment(trip, stops)
    for a in stops:
        for b in stops:
            if a.order < b.order:
                assert by_segment[(a.pk, b.pk)] == free_seats(trip, a, b)


# ---------- Отмена (ФТ-5) ----------

def test_passenger_cancels_in_time(trip, stops, passenger):
    minsk, _, gomel = stops
    booking = book(trip, minsk, gomel, seats=3, passenger=passenger)
    cancel_booking(booking, passenger)
    booking.refresh_from_db()
    assert booking.status == Booking.Status.CANCELLED
    assert booking.cancelled_at is not None
    assert free_seats(trip, minsk, gomel) == 18  # места снова свободны


def test_passenger_cannot_cancel_close_to_departure(trip, stops, passenger, dispatcher):
    minsk, _, gomel = stops
    booking = book(trip, minsk, gomel, passenger=passenger)
    trip.departure_at = timezone.now() + timedelta(hours=1)  # меньше 2 часов до отправления
    trip.save()
    booking.refresh_from_db()
    with pytest.raises(BookingError, match="не позже чем за 2 ч"):
        cancel_booking(booking, passenger)
    # Диспетчер отменить может, например если пассажир позвонил.
    cancel_booking(booking, dispatcher)
    assert booking.status == Booking.Status.CANCELLED


def test_cannot_cancel_someone_elses_booking(trip, stops, passenger):
    minsk, _, gomel = stops
    other = User.objects.create_user("+375294444444", "pass12345")
    booking = book(trip, minsk, gomel, passenger=other)
    assert not booking.can_cancel(passenger)


# ---------- Страницы ----------

def test_search_has_book_link(client, trip):
    response = client.get(reverse("core:search"), {
        "from_city": "Бобруйск", "to_city": "Гомель",
        "date": timezone.localdate(trip.departure_at).isoformat(),
    })
    assert reverse("bookings:book", args=[trip.pk]) in response.content.decode()


def test_booking_page_requires_login(client, trip):
    response = client.get(reverse("bookings:book", args=[trip.pk]))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_driver_cannot_book(client, trip, driver):
    client.force_login(driver)
    assert client.get(reverse("bookings:book", args=[trip.pk])).status_code == 403


def test_passenger_books_through_page(client, trip, stops, passenger):
    minsk, bobruisk, _ = stops
    client.force_login(passenger)
    url = reverse("bookings:book", args=[trip.pk])
    assert client.get(url, {"from": minsk.pk, "to": bobruisk.pk}).status_code == 200

    response = client.post(url, {
        "from_stop": minsk.pk, "to_stop": bobruisk.pk, "seats_count": 2,
        "passenger_name": "Анна", "passenger_phone": "+375293333333",
    })
    booking = Booking.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("bookings:detail", args=[booking.pk])
    assert booking.passenger == passenger
    assert booking.price == Decimal("36")

    page = client.get(response.url).content.decode()
    assert booking.code in page
    assert "Отменить бронь" in page
    # Бронь видна в кабинете.
    assert booking.code in client.get(reverse("core:cabinet")).content.decode()


def test_page_shows_error_when_no_seats(client, trip, stops, passenger):
    minsk, _, gomel = stops
    book(trip, minsk, gomel, seats=18)
    client.force_login(passenger)
    response = client.post(reverse("bookings:book", args=[trip.pk]), {
        "from_stop": minsk.pk, "to_stop": gomel.pk, "seats_count": 1,
        "passenger_name": "Анна", "passenger_phone": "+375293333333",
    })
    assert response.status_code == 200
    assert "мест больше нет" in response.content.decode()
    assert Booking.objects.count() == 1


def test_other_passenger_cannot_see_booking(client, trip, stops, passenger):
    minsk, _, gomel = stops
    booking = book(trip, minsk, gomel, passenger=passenger)
    other = User.objects.create_user("+375294444444", "pass12345")
    client.force_login(other)
    assert client.get(reverse("bookings:detail", args=[booking.pk])).status_code == 404
    assert client.post(reverse("bookings:cancel", args=[booking.pk])).status_code == 404


def test_cancel_through_page(client, trip, stops, passenger):
    minsk, _, gomel = stops
    booking = book(trip, minsk, gomel, passenger=passenger)
    client.force_login(passenger)
    client.post(reverse("bookings:cancel", args=[booking.pk]))
    booking.refresh_from_db()
    assert booking.status == Booking.Status.CANCELLED


def test_dispatcher_phone_booking_links_existing_passenger(client, trip, stops, dispatcher, passenger):
    """ФТ-14: диспетчер бронирует по звонку; бронь попадает в кабинет пассажира с этим телефоном."""
    minsk, _, gomel = stops
    client.force_login(dispatcher)
    client.post(reverse("bookings:book", args=[trip.pk]), {
        "from_stop": minsk.pk, "to_stop": gomel.pk, "seats_count": 1,
        "passenger_name": "Анна", "passenger_phone": passenger.phone,
    })
    client.post(reverse("bookings:book", args=[trip.pk]), {
        "from_stop": minsk.pk, "to_stop": gomel.pk, "seats_count": 1,
        "passenger_name": "Без аккаунта", "passenger_phone": "+375447777777",
    })
    linked, anonymous = Booking.objects.order_by("pk")
    assert linked.passenger == passenger and linked.created_by == dispatcher
    assert anonymous.passenger is None

    page = client.get(reverse("dispatch:trip_bookings", args=[trip.pk])).content.decode()
    assert "Без аккаунта" in page and "по звонку" in page


# ---------- Одновременная покупка последнего места (алгоритм 3) ----------

@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="блокировки строк проверяются на PostgreSQL")
def test_last_seat_is_sold_once(monkeypatch):
    """
    Два покупателя одновременно берут последнее место.
    Подсчёт мест замедлен, чтобы покупки точно наложились по времени.
    Без блокировки рейса продались бы оба места, с блокировкой — одно.
    """
    route = Route.objects.create(name="Минск – Гомель")
    first = RouteStop.objects.create(
        route=route, stop=Stop.objects.create(city="Минск", name="АВ"), order=1,
    )
    last = RouteStop.objects.create(
        route=route, stop=Stop.objects.create(city="Гомель", name="АВ"), order=2,
        minutes_from_start=270, price_from_start=35,
    )
    vehicle = Vehicle.objects.create(brand="Sprinter", plate_number="AB 0001-7", seats=1)
    trip = Trip.objects.create(
        route=route, vehicle=vehicle, departure_at=timezone.now() + timedelta(days=1)
    )

    slow_free_seats = services.free_seats

    def slow(*args):
        result = slow_free_seats(*args)
        time.sleep(0.3)
        return result

    monkeypatch.setattr(services, "free_seats", slow)

    results = []
    start = threading.Barrier(2)

    def buyer():
        start.wait()
        try:
            book(trip, first, last)
            results.append("ok")
        except BookingError:
            results.append("нет мест")
        finally:
            connection.close()  # у каждого потока своё соединение с базой

    threads = [threading.Thread(target=buyer) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["ok", "нет мест"]
    assert Booking.objects.filter(trip=trip).count() == 1
