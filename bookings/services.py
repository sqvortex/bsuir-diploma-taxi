"""
Создание и отмена броней (алгоритм 3 из ТЗ, ФТ-4, ФТ-5, ФТ-14).

Главная опасность при бронировании: два человека одновременно покупают
последнее место. Оба видят «свободно 1», оба нажимают «Забронировать»,
и место продаётся дважды.

Защита: перед проверкой мест мы блокируем строку рейса в базе
(SELECT ... FOR UPDATE). Второй покупатель ждёт, пока первый закончит,
и только потом считает свободные места, уже с учётом первой брони.
Блокировка снимается сама в конце транзакции.

На SQLite блокировки строк нет (там вся база блокируется на запись),
поэтому настоящая проверка одновременных броней делается на PostgreSQL.
"""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from transport.models import Trip
from transport.search import free_seats

from .models import Booking


class BookingError(Exception):
    """Бронь нельзя создать или отменить. Текст ошибки показываем пользователю."""


def create_booking(*, trip, from_stop, to_stop, seats_count, passenger_name,
                   passenger_phone, passenger=None, created_by=None):
    """
    Создаёт бронь, если на участке хватает мест. Иначе выбрасывает BookingError.

    passenger — аккаунт пассажира (пусто, если диспетчер бронирует человеку без аккаунта),
    created_by — кто оформил бронь (сам пассажир или диспетчер).
    """
    with transaction.atomic():
        # Блокируем рейс: пока транзакция не закончится, другие брони на этот рейс ждут.
        trip = Trip.objects.select_for_update().get(pk=trip.pk)

        if trip.status != Trip.Status.SCHEDULED:
            raise BookingError("Рейс отменён или уже выполнен.")
        if from_stop.route_id != trip.route_id or to_stop.route_id != trip.route_id:
            raise BookingError("Остановки не относятся к маршруту этого рейса.")
        if from_stop.order >= to_stop.order:
            raise BookingError("Остановка посадки должна быть раньше остановки высадки.")
        if trip.time_at(from_stop) <= timezone.now():
            raise BookingError("Машина уже отправилась с этой остановки.")
        if seats_count < 1:
            raise BookingError("Укажите хотя бы одно место.")

        available = free_seats(trip, from_stop, to_stop)
        if seats_count > available:
            if available == 0:
                raise BookingError("На этом участке мест больше нет.")
            raise BookingError(f"На этом участке осталось мест: {available}.")

        booking = Booking(
            trip=trip, from_stop=from_stop, to_stop=to_stop, seats_count=seats_count,
            passenger=passenger, passenger_name=passenger_name, passenger_phone=passenger_phone,
            created_by=created_by, price=0,
        )
        booking.price = booking.calculate_price()
        booking.full_clean()
        booking.save()
        return booking


def find_passenger(phone):
    """Аккаунт пассажира с таким телефоном, если он зарегистрирован (для брони по звонку)."""
    return User.objects.filter(phone=phone, role=User.Role.PASSENGER).first()


def cancel_booking(booking, user):
    """Отменяет бронь, если user имеет на это право (см. Booking.can_cancel)."""
    if not booking.can_cancel(user):
        if booking.status != Booking.Status.ACTIVE:
            raise BookingError("Эта бронь уже не активна.")
        raise BookingError(
            "Отменить бронь можно не позже чем за "
            f"{settings.BOOKING_CANCEL_HOURS} ч до отправления. Позвоните диспетчеру."
        )
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at"])
    return booking


# ---------- Отметки водителя (ФТ-10) ----------

MARK_STATUSES = [Booking.Status.BOARDED, Booking.Status.NO_SHOW, Booking.Status.ACTIVE]


def mark_booking(booking, status, user):
    """
    Отметка водителя: пассажир сел (BOARDED), не явился (NO_SHOW)
    или отметку нужно снять (снова ACTIVE, если водитель ошибся).
    """
    if status not in MARK_STATUSES:
        raise BookingError("Неизвестная отметка.")
    with transaction.atomic():
        # Блокируем рейс, как при бронировании: отметка может снова занять место.
        trip = Trip.objects.select_for_update().get(pk=booking.trip_id)
        booking = Booking.objects.select_related("from_stop", "to_stop").get(pk=booking.pk)
        if not trip.can_be_managed_by(user):
            raise BookingError("Это не ваш рейс.")
        if not trip.marks_open:
            raise BookingError("Отмечать пассажиров можно только в день рейса.")
        if booking.status == Booking.Status.CANCELLED:
            raise BookingError("Бронь отменена.")

        # Пассажир с отметкой «не явился» не занимает место, и его могли продать.
        # Перед тем как вернуть ему место, проверяем, что оно ещё свободно.
        was_free = booking.status == Booking.Status.NO_SHOW
        takes_seat = status in Booking.OCCUPYING_STATUSES
        if was_free and takes_seat:
            if free_seats(trip, booking.from_stop, booking.to_stop) < booking.seats_count:
                raise BookingError("Место пассажира уже занято, вернуть отметку нельзя.")

        booking.status = status
        booking.save(update_fields=["status"])
        return booking


def complete_trip(trip, user):
    """
    Водитель завершает рейс. Пассажиры без отметки считаются не явившимися:
    это важно для статистики и будущего прогноза загрузки.
    """
    if not trip.can_be_managed_by(user):
        raise BookingError("Это не ваш рейс.")
    if trip.status != Trip.Status.SCHEDULED:
        raise BookingError("Рейс уже завершён или отменён.")
    if trip.departure_at > timezone.now():
        raise BookingError("Рейс ещё не отправился.")
    with transaction.atomic():
        not_marked = trip.bookings.filter(status=Booking.Status.ACTIVE)
        no_show = not_marked.update(status=Booking.Status.NO_SHOW)
        trip.status = Trip.Status.COMPLETED
        trip.save(update_fields=["status"])
    return no_show
