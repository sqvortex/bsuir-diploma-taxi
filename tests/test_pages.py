"""Проверки страниц этапа 2: регистрация, вход, кабинеты по ролям, поиск."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.permissions import role_required
from bookings.models import Booking
from transport.search import find_trips, free_seats

pytestmark = pytest.mark.django_db


# --- Регистрация и вход (ФТ-1) ---

def test_home_page_opens(client):
    response = client.get(reverse("core:home"))
    assert response.status_code == 200
    assert "Найти" in response.content.decode()


def test_registration_creates_passenger_and_logs_in(client):
    response = client.post(reverse("accounts:register"), {
        "phone": "+375297777777", "first_name": "Олег", "last_name": "", "email": "",
        "password1": "Strong-pass-42", "password2": "Strong-pass-42",
    })
    assert response.status_code == 302
    user = User.objects.get(phone="+375297777777")
    assert user.role == User.Role.PASSENGER
    assert client.get(reverse("core:cabinet")).status_code == 200


def test_registration_rejects_wrong_phone(client):
    response = client.post(reverse("accounts:register"), {
        "phone": "80297777777", "first_name": "Олег",
        "password1": "Strong-pass-42", "password2": "Strong-pass-42",
    })
    assert response.status_code == 200
    assert not User.objects.exists()


def test_login_by_phone(client):
    User.objects.create_user("+375298888888", "Strong-pass-42")
    response = client.post(reverse("accounts:login"), {
        "username": "+375298888888", "password": "Strong-pass-42",
    })
    assert response.status_code == 302
    assert response.url == reverse("core:cabinet")


# --- Кабинеты и права доступа (ФТ-16) ---

def test_cabinet_requires_login(client):
    response = client.get(reverse("core:cabinet"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


@pytest.mark.parametrize("role, title", [
    (User.Role.PASSENGER, "Мои поездки"),
    (User.Role.DRIVER, "Мои рейсы сегодня"),
    (User.Role.DISPATCHER, "Панель диспетчера"),
    (User.Role.ADMIN, "Панель администратора"),
])
def test_cabinet_depends_on_role(client, role, title):
    user = User.objects.create_user("+375290000001", "Strong-pass-42", role=role)
    client.force_login(user)
    assert title in client.get(reverse("core:cabinet")).content.decode()


def test_role_required_blocks_other_roles():
    @role_required(User.Role.DISPATCHER)
    def dispatcher_only(request):
        return HttpResponse("ok")

    request = RequestFactory().get("/")
    request.user = User.objects.create_user("+375290000002", "x", role=User.Role.PASSENGER)
    with pytest.raises(PermissionDenied):
        dispatcher_only(request)

    request.user = User.objects.create_user("+375290000003", "x", role=User.Role.DISPATCHER)
    assert dispatcher_only(request).status_code == 200


# --- Поиск рейсов и места по участкам (алгоритмы 1 и 2) ---

def book(trip, from_stop, to_stop, seats):
    return Booking.objects.create(
        trip=trip, passenger_name="Тест", passenger_phone="+375295555555",
        from_stop=from_stop, to_stop=to_stop, seats_count=seats, price=0,
    )


def test_search_finds_trip_by_intermediate_stop(trip):
    day = timezone.localdate(trip.departure_at)
    offers = find_trips("Бобруйск", "Гомель", day)
    assert len(offers) == 1
    assert offers[0].price == 17
    assert offers[0].departure == trip.departure_at + timedelta(minutes=120)


def test_search_ignores_wrong_direction(trip):
    day = timezone.localdate(trip.departure_at)
    assert find_trips("Гомель", "Минск", day) == []


def test_seat_on_non_overlapping_segments_can_be_sold_twice(trip, stops):
    minsk, bobruisk, gomel = stops
    book(trip, minsk, bobruisk, seats=18)          # вся машина занята до Бобруйска
    assert free_seats(trip, minsk, bobruisk) == 0
    assert free_seats(trip, bobruisk, gomel) == 18  # после Бобруйска снова свободно
    assert free_seats(trip, minsk, gomel) == 0


def test_cancelled_booking_frees_seats(trip, stops):
    booking = book(trip, stops[0], stops[2], seats=3)
    assert free_seats(trip, stops[0], stops[2]) == 15
    booking.status = Booking.Status.CANCELLED
    booking.save()
    assert free_seats(trip, stops[0], stops[2]) == 18


def test_search_page_shows_results(client, trip):
    day = timezone.localdate(trip.departure_at)
    response = client.get(reverse("core:search"), {
        "from_city": "Минск", "to_city": "Гомель", "date": day.isoformat(),
    })
    assert response.status_code == 200
    page = response.content.decode()
    assert "07:30" in page and "35,00" in page and "свободно 18" in page
