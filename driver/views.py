"""
Кабинет водителя (ФТ-8, ФТ-9, ФТ-10).

Список рейсов на день находится в общем кабинете (core/views.py, driver_cabinet).
Здесь посадочная ведомость рейса и отметки «сел» / «не явился».
Страницы открывает водитель этого рейса, а также диспетчер и администратор.
"""

from dataclasses import dataclass, field

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from bookings.models import Booking
from bookings.services import BookingError, complete_trip, mark_booking
from transport.models import Trip


@dataclass
class StopRow:
    """Строка ведомости: остановка, кто на ней садится и кто выходит."""

    route_stop: object
    time: object
    boarding: list = field(default_factory=list)
    leaving: list = field(default_factory=list)
    on_board: int = 0  # сколько мест занято после отправления с этой остановки


def build_manifest(trip):
    """
    Посадочная ведомость (ФТ-9): остановки по порядку, у каждой —
    кто садится, кто выходит и сколько людей в салоне после неё.
    Отменённые брони в ведомость не попадают.
    """
    bookings = list(
        trip.bookings.exclude(status=Booking.Status.CANCELLED)
        .select_related("from_stop__stop", "to_stop__stop")
        .order_by("passenger_name")
    )
    rows = []
    for route_stop in trip.route.ordered_stops():
        row = StopRow(route_stop=route_stop, time=trip.time_at(route_stop))
        row.boarding = [b for b in bookings if b.from_stop_id == route_stop.pk]
        # Кто не явился, тот и не выходит.
        row.leaving = [b for b in bookings
                       if b.to_stop_id == route_stop.pk and b.status != Booking.Status.NO_SHOW]
        row.on_board = sum(
            b.seats_count for b in bookings
            if b.occupies_seats and b.from_stop.order <= route_stop.order < b.to_stop.order
        )
        rows.append(row)

    def seats(*statuses):
        return sum(b.seats_count for b in bookings if b.status in statuses)

    def money(*statuses):
        return sum(b.price for b in bookings if b.status in statuses)

    summary = {
        "expected": seats(Booking.Status.ACTIVE),      # ещё не отмечены
        "boarded": seats(Booking.Status.BOARDED),
        "no_show": seats(Booking.Status.NO_SHOW),
        "collected": money(Booking.Status.BOARDED),  # оплата водителю при посадке
        "to_collect": money(Booking.Status.ACTIVE, Booking.Status.BOARDED),
    }
    return rows, summary


def get_managed_trip(request, pk):
    trip = get_object_or_404(Trip.objects.select_related("route", "vehicle", "driver"), pk=pk)
    if not trip.can_be_managed_by(request.user):
        raise Http404  # чужие рейсы водитель не видит
    return trip


@login_required
def manifest(request, pk):
    trip = get_managed_trip(request, pk)
    rows, summary = build_manifest(trip)
    return render(request, "driver/manifest.html", {
        "trip": trip,
        "rows": rows,
        "summary": summary,
    })


@login_required
@require_POST
def mark(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("trip"), pk=pk)
    if not booking.trip.can_be_managed_by(request.user):
        raise Http404
    try:
        mark_booking(booking, request.POST.get("status"), request.user)
    except BookingError as error:
        messages.error(request, str(error))
    # Возвращаемся к той же карточке пассажира, чтобы не листать ведомость заново.
    return redirect(f"{reverse('driver:manifest', args=[booking.trip_id])}#b{booking.pk}")


@login_required
@require_POST
def complete(request, pk):
    trip = get_managed_trip(request, pk)
    try:
        no_show = complete_trip(trip, request.user)
    except BookingError as error:
        messages.error(request, str(error))
    else:
        text = "Рейс завершён."
        if no_show:
            text += f" Без отметки остались брони: {no_show}, они записаны как «не явился»."
        messages.success(request, text)
    return redirect("driver:manifest", pk=trip.pk)
