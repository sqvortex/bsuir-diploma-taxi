"""Тесты прогноза: праздники, обучающая таблица, обучение модели, рекомендации, страницы."""

import math
from datetime import date, datetime, time, timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking
from forecast import model
from forecast.dataset import training_table
from forecast.holidays import is_holiday, is_pre_holiday, orthodox_easter
from forecast.model import LegForecast, TripForecast
from forecast.recommend import recommend
from transport.models import ScheduleTemplate, Trip, Vehicle
from transport.search import seats_word

pytestmark = pytest.mark.django_db


# ---------- Праздники ----------

def test_orthodox_easter_and_radunitsa():
    assert orthodox_easter(2026) == date(2026, 4, 12)
    assert orthodox_easter(2027) == date(2027, 5, 2)
    assert is_holiday(date(2026, 4, 21))       # Радуница: 9-й день после Пасхи
    assert is_holiday(date(2026, 7, 3))        # День Независимости
    assert is_pre_holiday(date(2026, 7, 2))
    assert not is_pre_holiday(date(2026, 1, 1))  # 1 января сам праздник


def test_seats_word():
    assert [seats_word(n) for n in (0, 1, 2, 5, 11, 21, 22)] == [
        "мест", "место", "места", "мест", "мест", "место", "места",
    ]


# ---------- Обучающая таблица ----------

def test_training_table_counts_sold_seats_by_day(route, stops, driver):
    """Продано к моменту «за d дней» учитывает время брони и время отмены."""
    minsk, bobruisk, gomel = stops
    vehicle = Vehicle.objects.create(brand="Sprinter", plate_number="AB 0001-7", seats=18)
    departure = timezone.now() - timedelta(days=30)
    trip = Trip.objects.create(route=route, vehicle=vehicle, departure_at=departure,
                               status=Trip.Status.COMPLETED)

    def add(from_stop, to_stop, seats, created_days, cancelled_days=None):
        Booking.objects.create(
            trip=trip, from_stop=from_stop, to_stop=to_stop, seats_count=seats, price=0,
            passenger_name="Тест", passenger_phone="+375291234567",
            created_at=departure - timedelta(days=created_days),
            cancelled_at=departure - timedelta(days=cancelled_days) if cancelled_days else None,
            status=Booking.Status.CANCELLED if cancelled_days else Booking.Status.BOARDED,
        )

    add(minsk, gomel, 2, created_days=5)
    add(minsk, bobruisk, 1, created_days=1.05)
    add(bobruisk, gomel, 1, created_days=10, cancelled_days=3)

    table = training_table(Trip.objects.filter(pk=trip.pk)).set_index(["leg", "days_before"])
    sold = lambda leg, days: table.loc[(leg, days), "sold"]  # noqa: E731
    # Перегон 1 — Минск → Бобруйск, перегон 2 — Бобруйск → Гомель.
    assert table.loc[(1, 0), "target"] == 3 and table.loc[(2, 0), "target"] == 2
    assert (sold(1, 0), sold(2, 0)) == (3, 2)
    assert (sold(1, 2), sold(2, 2)) == (2, 2)   # отменённая бронь уже не считается
    assert (sold(1, 4), sold(2, 4)) == (2, 3)   # а за 4 дня она ещё была
    assert (sold(1, 7), sold(2, 7)) == (0, 1)
    assert (sold(1, 14), sold(2, 14)) == (0, 0)


# ---------- Обучение и прогноз ----------

@pytest.fixture
def trained(route, stops, driver, settings, tmp_path):
    """История за 120 дней по одному шаблону и обученная на ней модель."""
    settings.FORECAST_MODEL_PATH = tmp_path / "model.joblib"
    vehicle = Vehicle.objects.create(brand="Sprinter", plate_number="AB 0001-7", seats=18)
    template = ScheduleTemplate.objects.create(
        route=route, departure_time=time(7, 30), valid_from=timezone.localdate(),
        default_vehicle=vehicle, default_driver=driver,
    )
    call_command("generate_history", days=120, stdout=None)
    result = model.train(test_days=30)
    model.save(result.bundle)
    future = Trip.objects.create(
        route=route, template=template, vehicle=vehicle, driver=driver,
        departure_at=template.departure_on(timezone.localdate() + timedelta(days=3)),
    )
    return result, future


def test_history_is_realistic(trained, route):
    trips = Trip.objects.filter(status=Trip.Status.COMPLETED)
    assert trips.count() == 120
    bookings = Booking.objects.filter(trip__in=trips)
    assert bookings.filter(created_at__gt=timezone.now()).count() == 0
    assert bookings.filter(status=Booking.Status.CANCELLED, cancelled_at__isnull=True).count() == 0
    # Ни на одном перегоне не продано больше мест, чем в машине.
    table = training_table(trips)
    assert (table["target"] <= table["capacity"]).all()


def test_train_report_and_prediction(trained, stops):
    result, future = trained
    report = result.report
    assert report["test_trips"] > 0 and report["train_trips"] > 0
    assert report["model"]["mae"] >= 0 and report["baseline"]["mae"] >= 0
    assert set(report["by_horizon"]) == {0, 1, 3, 7, 14}

    minsk, _, gomel = stops
    Booking.objects.create(
        trip=future, from_stop=minsk, to_stop=gomel, seats_count=2, price=70,
        passenger_name="Анна", passenger_phone="+375291234567",
    )
    now = timezone.now()
    forecast = model.predict(Trip.objects.filter(pk=future.pk), now=now)[future.pk]
    # Дни округляются вверх: рейс через 2 дня 20 часов — это «3 дня», через 3 дня 5 часов — «4 дня».
    assert forecast.days_before == math.ceil((future.departure_at - now).total_seconds() / 86400)
    assert [leg.sold for leg in forecast.legs] == [2, 2]
    for leg in forecast.legs:
        assert leg.sold <= leg.expected <= 18
    low, high = forecast.free_range()
    assert 0 <= low <= high <= 16  # свободных мест не больше, чем свободно сейчас


# ---------- Рекомендации (алгоритм 5) ----------

def fake_forecast(trip, expected, spread=1):
    legs = [LegForecast(leg=1, sold=0, expected=expected, low=max(expected - spread, 0), high=expected + spread)]
    return TripForecast(trip_id=trip.pk, capacity=trip.capacity, days_before=3, legs=legs)


def test_recommendations(trip, route):
    day = timezone.localdate(trip.departure_at)
    evening = Trip.objects.create(
        route=route, vehicle=trip.vehicle,
        departure_at=timezone.make_aware(datetime.combine(day, time(17, 45))),
    )
    Vehicle.objects.create(brand="Большой автобус", plate_number="AA 0000-7", seats=30)

    # Утром почти пусто (3 из 18), вечером 9 из 18: утренний рейс можно совместить с вечерним.
    forecasts = {trip.pk: fake_forecast(trip, 3), evening.pk: fake_forecast(evening, 9)}
    [low] = recommend([trip, evening], forecasts)
    assert low.kind == "low" and low.trip == trip and "17:45" in low.text

    # Вечером ожидается под завязку: может не хватить мест.
    forecasts[evening.pk] = fake_forecast(evening, 18, spread=2)
    kinds = {rec.trip.pk: rec for rec in recommend([trip, evening], forecasts)}
    assert kinds[evening.pk].kind == "full"
    assert "Большой автобус" in kinds[evening.pk].text


# ---------- Страницы ----------

def test_forecast_page_without_model(client, settings, tmp_path):
    settings.FORECAST_MODEL_PATH = tmp_path / "missing.joblib"
    client.force_login(User.objects.create_user("+375292222222", "pass12345", role=User.Role.DISPATCHER))
    response = client.get(reverse("forecast:overview"))
    assert response.status_code == 200
    assert "ещё не обучена" in response.content.decode()


def test_forecast_page_and_search_with_model(client, trained):
    _, future = trained
    client.force_login(User.objects.create_user("+375292222222", "pass12345", role=User.Role.DISPATCHER))
    page = client.get(reverse("forecast:overview"), {"date": timezone.localdate(future.departure_at)})
    assert page.status_code == 200
    assert "ошибка модели" in page.content.decode()
    assert "forecast-chart" in page.content.decode()

    search = client.get(reverse("core:search"), {
        "from_city": "Минск", "to_city": "Гомель",
        "date": timezone.localdate(future.departure_at).isoformat(),
    })
    assert "к отправлению останется" in search.content.decode()


def test_forecast_page_only_for_staff(client):
    client.force_login(User.objects.create_user("+375293333333", "pass12345"))
    assert client.get(reverse("forecast:overview")).status_code == 403
