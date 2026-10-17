"""Проверки этапа 3: расписание, маршруты, автопарк и назначение на рейсы."""

from datetime import date, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking
from transport.models import Route, ScheduleTemplate, Stop, Trip, Vehicle
from transport.schedule import generate_trips

pytestmark = pytest.mark.django_db


@pytest.fixture
def dispatcher_client(client):
    user = User.objects.create_user("+375292222222", "pass12345", role=User.Role.DISPATCHER)
    client.force_login(user)
    return client


# --- Создание рейсов по шаблонам (ФТ-12) ---

def test_generate_trips_by_weekdays(route):
    monday = date(2026, 11, 2)
    template = ScheduleTemplate.objects.create(
        route=route, departure_time=time(8, 0), weekdays="135", valid_from=monday
    )
    result = generate_trips(monday, monday + timedelta(days=6))  # пн–вс
    assert result.created == 3  # пн, ср, пт
    days = sorted(timezone.localdate(t.departure_at).isoweekday() for t in template.trips.all())
    assert days == [1, 3, 5]


def test_generate_trips_twice_does_not_duplicate(route):
    start = date(2026, 11, 2)
    ScheduleTemplate.objects.create(route=route, departure_time=time(8, 0), valid_from=start)
    generate_trips(start, start + timedelta(days=6))
    again = generate_trips(start, start + timedelta(days=6))
    assert again.created == 0 and again.existing == 7
    assert Trip.objects.count() == 7


def test_generate_trips_uses_default_vehicle_and_driver(route, driver):
    vehicle = Vehicle.objects.create(brand="Crafter", plate_number="AE 1-7", seats=16)
    start = date(2026, 11, 2)
    ScheduleTemplate.objects.create(
        route=route, departure_time=time(8, 0), valid_from=start,
        default_vehicle=vehicle, default_driver=driver,
    )
    generate_trips(start, start)
    trip = Trip.objects.get()
    assert trip.vehicle == vehicle and trip.driver == driver


def test_generate_trips_skips_inactive_route(route):
    start = date(2026, 11, 2)
    ScheduleTemplate.objects.create(route=route, departure_time=time(8, 0), valid_from=start)
    route.is_active = False
    route.save()
    assert generate_trips(start, start + timedelta(days=6)).created == 0


def test_generate_button(dispatcher_client, route):
    ScheduleTemplate.objects.create(
        route=route, departure_time=time(8, 0), valid_from=timezone.localdate()
    )
    response = dispatcher_client.post(reverse("dispatch:trips_generate"), {"days": 3})
    assert response.status_code == 302
    assert Trip.objects.count() == 3


# --- Доступ ---

def test_passenger_cannot_open_dispatch(client):
    client.force_login(User.objects.create_user("+375293333333", "pass12345"))
    assert client.get(reverse("dispatch:trips")).status_code == 403


def test_dispatcher_cannot_add_vehicle_but_admin_can(dispatcher_client, client):
    assert dispatcher_client.get(reverse("dispatch:vehicle_new")).status_code == 403
    admin = User.objects.create_user("+375290000009", "pass12345", role=User.Role.ADMIN)
    client.force_login(admin)
    response = client.post(reverse("dispatch:vehicle_new"), {
        "brand": "Sprinter", "plate_number": "AB 7777-7", "seats": 18, "is_active": "on",
    })
    assert response.status_code == 302
    assert Vehicle.objects.filter(plate_number="AB 7777-7").exists()


@pytest.mark.parametrize("name", ["trips", "templates", "routes", "stops", "vehicles", "route_new", "stop_new", "template_new"])
def test_dispatch_pages_open(dispatcher_client, trip, name):
    assert dispatcher_client.get(reverse(f"dispatch:{name}")).status_code == 200


# --- Маршрут с остановками (ФТ-11) ---

def route_post(stops, name="Минск – Слуцк"):
    """Данные формы маршрута: stops — список (stop_id, номер, минут, цена)."""
    data = {
        "name": name, "is_active": "on",
        "stops-TOTAL_FORMS": str(len(stops)), "stops-INITIAL_FORMS": "0",
        "stops-MIN_NUM_FORMS": "0", "stops-MAX_NUM_FORMS": "1000",
    }
    for i, (stop_id, order, minutes, price) in enumerate(stops):
        data.update({
            f"stops-{i}-stop": stop_id, f"stops-{i}-order": order,
            f"stops-{i}-minutes_from_start": minutes, f"stops-{i}-price_from_start": price,
        })
    return data


def test_create_route_with_stops(dispatcher_client):
    minsk = Stop.objects.create(city="Минск", name="Юго-Запад")
    slutsk = Stop.objects.create(city="Слуцк", name="Автовокзал")
    response = dispatcher_client.post(
        reverse("dispatch:route_new"),
        route_post([(minsk.pk, 1, 0, "0"), (slutsk.pk, 2, 100, "14")]),
    )
    assert response.status_code == 302
    route = Route.objects.get(name="Минск – Слуцк")
    assert [rs.stop.city for rs in route.ordered_stops()] == ["Минск", "Слуцк"]


def test_route_rejects_decreasing_time(dispatcher_client):
    a = Stop.objects.create(city="А", name="1")
    b = Stop.objects.create(city="Б", name="1")
    c = Stop.objects.create(city="В", name="1")
    response = dispatcher_client.post(
        reverse("dispatch:route_new"),
        route_post([(a.pk, 1, 0, "0"), (b.pk, 2, 90, "10"), (c.pk, 3, 60, "15")]),
    )
    assert response.status_code == 200  # форма показана снова с ошибкой
    assert not Route.objects.filter(name="Минск – Слуцк").exists()
    assert "должно быть больше" in response.content.decode()


def test_reorder_route_stops(dispatcher_client, route, stops):
    """Можно поменять остановки местами, хотя номер уникален внутри маршрута."""
    minsk, bobruisk, gomel = stops
    data = route_post([], name=route.name)
    data.update({"stops-TOTAL_FORMS": "3", "stops-INITIAL_FORMS": "3"})
    rows = [(minsk, 1, 0, "0"), (gomel, 2, 100, "20"), (bobruisk, 3, 270, "35")]
    for i, (rs, order, minutes, price) in enumerate(rows):
        data.update({
            f"stops-{i}-id": rs.pk, f"stops-{i}-route": route.pk, f"stops-{i}-stop": rs.stop_id,
            f"stops-{i}-order": order, f"stops-{i}-minutes_from_start": minutes,
            f"stops-{i}-price_from_start": price,
        })
    response = dispatcher_client.post(reverse("dispatch:route_edit", args=[route.pk]), data)
    assert response.status_code == 302
    assert [rs.stop.city for rs in route.ordered_stops()] == ["Минск", "Гомель", "Бобруйск"]


# --- Назначение машины и водителя (ФТ-13) ---

def test_assign_vehicle_and_driver(dispatcher_client, trip, driver):
    other = Vehicle.objects.create(brand="Transit", plate_number="AK 1-7", seats=14)
    response = dispatcher_client.post(reverse("dispatch:trip_edit", args=[trip.pk]), {
        "vehicle": other.pk, "driver": driver.pk, "status": "scheduled",
    })
    assert response.status_code == 302
    trip.refresh_from_db()
    assert trip.vehicle == other


def test_vehicle_busy_on_overlapping_trip(dispatcher_client, trip, driver):
    second = Trip.objects.create(
        route=trip.route, departure_at=trip.departure_at + timedelta(hours=2)
    )
    # Первый рейс едет 4,5 часа, значит через 2 часа машина ещё в пути.
    response = dispatcher_client.post(reverse("dispatch:trip_edit", args=[second.pk]), {
        "vehicle": trip.vehicle.pk, "driver": "", "status": "scheduled",
    })
    assert response.status_code == 200
    assert "Машина уже занята" in response.content.decode()


def test_vehicle_too_small_for_sold_seats(dispatcher_client, trip, stops):
    Booking.objects.create(
        trip=trip, passenger_name="Тест", passenger_phone="+375295555555",
        from_stop=stops[0], to_stop=stops[2], seats_count=15, price=0,
    )
    small = Vehicle.objects.create(brand="Транзит", plate_number="AK 2-7", seats=14)
    response = dispatcher_client.post(reverse("dispatch:trip_edit", args=[trip.pk]), {
        "vehicle": small.pk, "driver": "", "status": "scheduled",
    })
    assert response.status_code == 200
    assert "продано уже 15" in response.content.decode()
