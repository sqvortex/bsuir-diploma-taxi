"""
Письма пассажирам (ФТ-7): подтверждение брони и напоминание за день до поездки.

Письмо уходит на почту из аккаунта пассажира. Если аккаунта или почты нет
(например, диспетчер бронировал по звонку), письмо просто не отправляется.
Ошибка почты никогда не ломает бронь: она пишется в журнал.
"""

import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from transport.models import Trip

from .models import Booking

logger = logging.getLogger(__name__)


def recipient(booking):
    """Адрес пассажира или None, если писать некуда."""
    if booking.passenger_id and booking.passenger.email:
        return booking.passenger.email
    return None


def ticket_text(booking):
    """Одинаковый для обоих писем блок: маршрут, время, места, цена и ссылка на билет."""
    departure = timezone.localtime(booking.departure)
    link = settings.SITE_URL.rstrip("/") + reverse("bookings:detail", args=[booking.pk])
    return (
        f"Бронь {booking.code}\n"
        f"Рейс: {booking.trip.route}\n"
        f"Посадка: {booking.from_stop.stop} — {departure:%d.%m.%Y в %H:%M}\n"
        f"Высадка: {booking.to_stop.stop} — {timezone.localtime(booking.arrival):%H:%M}\n"
        f"Мест: {booking.seats_count}\n"
        f"Стоимость: {booking.price} BYN (оплата водителю при посадке)\n"
        f"Билет: {link}\n"
    )


def send_booking_confirmation(booking):
    """Письмо «бронь оформлена». Возвращает True, если письмо отправлено."""
    address = recipient(booking)
    if not address:
        return False
    cancel_hours = settings.BOOKING_CANCEL_HOURS
    body = (
        f"Здравствуйте, {booking.passenger_name}!\n\n"
        "Ваша бронь оформлена.\n\n"
        f"{ticket_text(booking)}\n"
        f"Отменить бронь можно на сайте не позже чем за {cancel_hours} ч до посадки.\n\n"
        f"{settings.SITE_NAME}"
    )
    return deliver(f"Бронь {booking.code} оформлена", body, address)


def send_reminder(booking):
    """Письмо-напоминание о завтрашней поездке."""
    address = recipient(booking)
    if not address:
        return False
    body = (
        f"Здравствуйте, {booking.passenger_name}!\n\n"
        "Напоминаем: завтра у вас поездка.\n\n"
        f"{ticket_text(booking)}\n"
        "Если планы изменились, отмените бронь на сайте, чтобы место смог занять другой пассажир.\n\n"
        f"{settings.SITE_NAME}"
    )
    return deliver(f"Напоминание: завтра поездка {booking.code}", body, address)


def deliver(subject, body, address):
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [address])
    except Exception:  # почта недоступна: пассажир всё равно видит бронь на сайте
        logger.exception("Не удалось отправить письмо на %s", address)
        return False
    return True


def bookings_to_remind(now=None):
    """Активные брони на завтра, о которых ещё не напоминали."""
    now = now or timezone.now()
    tomorrow = timezone.localdate(now) + timedelta(days=1)
    start = timezone.make_aware(datetime.combine(tomorrow, time.min))
    end = start + timedelta(days=1)
    candidates = Booking.objects.filter(
        status=Booking.Status.ACTIVE, reminded_at__isnull=True,
        trip__status=Trip.Status.SCHEDULED, passenger__email__gt="",
    ).select_related("passenger", "trip__route", "from_stop__stop", "to_stop__stop")
    # Время посадки зависит от остановки (рейс + минуты в пути), поэтому проверяем в коде.
    return [b for b in candidates if start <= b.departure < end]


def send_reminders(now=None):
    """Рассылает напоминания и отмечает, кому отправлено. Возвращает число писем."""
    sent = 0
    for booking in bookings_to_remind(now):
        if send_reminder(booking):
            booking.reminded_at = timezone.now()
            booking.save(update_fields=["reminded_at"])
            sent += 1
    return sent
