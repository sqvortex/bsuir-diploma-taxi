"""
Страницы бронирования: оформление брони, билет и отмена.

Пассажир бронирует себе (ФТ-4), диспетчер и администратор оформляют бронь
по телефонному звонку (ФТ-14) на той же странице. Водитель бронировать не может.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from transport.models import Trip
from transport.search import free_seats_by_segment

from .forms import BookingForm
from .models import Booking
from .services import BookingError, cancel_booking, create_booking, find_passenger


def is_staff_user(user):
    return user.is_dispatcher or user.is_admin_role


def segments_for_page(trip, stops):
    """Цена, время и свободные места по каждому участку: страница пересчитывает итог без перезагрузки."""
    by_pk = {stop.pk: stop for stop in stops}
    segments = {}
    for (from_pk, to_pk), seats in free_seats_by_segment(trip, stops).items():
        a, b = by_pk[from_pk], by_pk[to_pk]
        segments[f"{from_pk}-{to_pk}"] = {
            "free": seats,
            "price": str(a.price_to(b)),
            "departure": f"{timezone.localtime(trip.time_at(a)):%H:%M}",
            "arrival": f"{timezone.localtime(trip.time_at(b)):%H:%M}",
            "from": str(a.stop),
            "to": str(b.stop),
        }
    return segments


@login_required
def book(request, trip_pk):
    user = request.user
    if user.is_driver:
        raise PermissionDenied("Водитель не может оформлять брони.")
    trip = get_object_or_404(Trip.objects.select_related("route", "vehicle"), pk=trip_pk)
    stops = list(trip.route.ordered_stops())
    staff = is_staff_user(user)

    # Остановки, выбранные в поиске, приходят в адресе: /bookings/trip/5/?from=1&to=3
    initial = {"from_stop": request.GET.get("from") or stops[0].pk,
               "to_stop": request.GET.get("to") or stops[-1].pk,
               "seats_count": 1}
    if not staff:
        initial.update(passenger_name=user.get_full_name() or user.first_name,
                       passenger_phone=user.phone)

    form = BookingForm(request.POST or None, trip=trip, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            booking = create_booking(
                trip=trip,
                from_stop=data["from_stop"],
                to_stop=data["to_stop"],
                seats_count=data["seats_count"],
                passenger_name=data["passenger_name"],
                passenger_phone=data["passenger_phone"],
                # Диспетчер бронирует человеку по звонку: если у него есть аккаунт,
                # бронь появится и в его кабинете.
                passenger=find_passenger(data["passenger_phone"]) if staff else user,
                created_by=user,
            )
        except BookingError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, f"Бронь {booking.code} оформлена. Оплата водителю при посадке.")
            return redirect("bookings:detail", pk=booking.pk)

    return render(request, "bookings/book.html", {
        "trip": trip,
        "form": form,
        "staff": staff,
        "segments": segments_for_page(trip, stops),
        "is_open": trip.status == Trip.Status.SCHEDULED and trip.departure_at > timezone.now(),
    })


def get_visible_booking(request, pk):
    """Бронь видит её пассажир, тот, кто её оформил, и диспетчер с администратором."""
    booking = get_object_or_404(
        Booking.objects.select_related("trip__route", "trip__vehicle", "from_stop__stop", "to_stop__stop"),
        pk=pk,
    )
    user = request.user
    if not (is_staff_user(user) or booking.passenger_id == user.pk or booking.created_by_id == user.pk):
        raise Http404  # чужую бронь не показываем, даже не признаём, что она есть
    return booking


@login_required
def detail(request, pk):
    booking = get_visible_booking(request, pk)
    return render(request, "bookings/detail.html", {
        "booking": booking,
        "can_cancel": booking.can_cancel(request.user),
    })


@login_required
@require_POST
def cancel(request, pk):
    booking = get_visible_booking(request, pk)
    try:
        cancel_booking(booking, request.user)
    except BookingError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Бронь {booking.code} отменена, места снова свободны.")
    # Диспетчер возвращается к списку пассажиров рейса, пассажир — к билету.
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("bookings:detail", pk=booking.pk)
