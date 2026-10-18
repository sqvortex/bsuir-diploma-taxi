"""
Испытания по ТЗ, которые не вошли в тесты отдельных этапов: история поездок (ФТ-6),
защита форм (раздел 4.3) и число запросов к базе при поиске (раздел 4.4).
Таблица «требование → тест» лежит в docs/test-cases.md.
"""

from datetime import timedelta
from urllib.parse import quote

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking
from transport.models import Trip

pytestmark = pytest.mark.django_db


def test_history_and_repeat_trip(client, trip, stops):
    """ФТ-6: прошедшая поездка видна в истории, а «Повторить» ведёт в поиск с теми же городами."""
    minsk, _, gomel = stops
    anna = User.objects.create_user("+375293333333", "pass12345", first_name="Анна")
    Trip.objects.filter(pk=trip.pk).update(
        departure_at=timezone.now() - timedelta(days=3), status=Trip.Status.COMPLETED,
    )
    Booking.objects.create(
        trip=trip, passenger=anna, from_stop=minsk, to_stop=gomel, seats_count=1, price=35,
        status=Booking.Status.BOARDED, passenger_name="Анна", passenger_phone=anna.phone,
    )
    client.force_login(anna)
    page = client.get(reverse("core:cabinet")).content.decode()
    assert "История" in page and "Минск → Гомель" in page
    assert f"from_city={quote('Минск')}&to_city={quote('Гомель')}" in page


def test_post_without_csrf_token_is_rejected(trip, stops):
    """Раздел 4.3: форма без CSRF-токена не принимается (защита встроена в Django)."""
    anna = User.objects.create_user("+375293333333", "pass12345", first_name="Анна")
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(anna)
    response = strict.post(reverse("bookings:book", args=[trip.pk]), {"seats_count": 1})
    assert response.status_code == 403
    assert not Booking.objects.exists()


def test_user_input_is_escaped(client, trip, stops):
    """Раздел 4.3: имя пассажира с HTML-кодом выводится как текст (защита от XSS)."""
    minsk, _, gomel = stops
    anna = User.objects.create_user("+375293333333", "pass12345", first_name="Анна")
    booking = Booking.objects.create(
        trip=trip, passenger=anna, from_stop=minsk, to_stop=gomel, seats_count=1, price=35,
        passenger_name="<script>alert(1)</script>", passenger_phone=anna.phone,
    )
    client.force_login(anna)
    page = client.get(reverse("bookings:detail", args=[booking.pk])).content.decode()
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_passwords_are_not_stored_as_plain_text():
    """Раздел 4.3: в базе лежит только хеш пароля."""
    user = User.objects.create_user("+375293333333", "pass12345")
    assert "pass12345" not in user.password and user.password.startswith(("pbkdf2_", "argon2", "bcrypt"))


def test_search_does_not_query_database_per_trip(client, trip, django_capture_on_commit_callbacks):
    """Раздел 4.4: число запросов к базе при поиске не растёт вместе с числом рейсов."""
    day = timezone.localdate(trip.departure_at).isoformat()
    params = {"from_city": "Минск", "to_city": "Гомель", "date": day}

    def count_queries():
        with CaptureQueriesContext(connection) as queries:
            page = client.get(reverse("core:search"), params).content.decode()
        return len(queries), page.count("Выбрать")

    few, found = count_queries()
    assert found == 1
    for hour in range(8, 13):  # ещё пять рейсов в тот же день
        Trip.objects.create(route=trip.route, vehicle=trip.vehicle,
                            departure_at=trip.departure_at.replace(hour=hour, minute=5))
    many, found = count_queries()
    assert found == 6
    assert many == few
