"""
Общие страницы сайта: главная, поиск рейсов и личный кабинет.

Личный кабинет один на всех (адрес /cabinet/), но показывает разное
в зависимости от роли пользователя.
"""

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.models import User
from bookings.models import Booking
from forecast import model as forecast_model
from transport.models import Route, Stop, Trip
from transport.search import find_trips

from .forms import SearchForm


def city_choices():
    """Список городов для подсказок в полях «Откуда» и «Куда»."""
    return Stop.objects.order_by("city").values_list("city", flat=True).distinct()


def popular_routes():
    """Маршруты для блока «Популярные направления»: откуда, куда и цена от начала до конца."""
    routes = []
    for route in Route.objects.filter(is_active=True).prefetch_related("route_stops__stop")[:6]:
        stops = list(route.ordered_stops())
        if len(stops) >= 2:
            routes.append({
                "route": route,
                "first": stops[0],
                "last": stops[-1],
                "price": stops[0].price_to(stops[-1]),
                "duration": stops[0].minutes_to(stops[-1]),
                "via": [s.stop.city for s in stops[1:-1]],
            })
    return routes


def home(request):
    form = SearchForm(initial={"date": timezone.localdate()})
    return render(request, "core/home.html", {
        "form": form,
        "cities": city_choices(),
        "routes": popular_routes(),
    })


def search(request):
    form = SearchForm(request.GET or None, initial={"date": timezone.localdate()})
    offers = None
    if form.is_valid():
        offers = find_trips(
            form.cleaned_data["from_city"].strip(),
            form.cleaned_data["to_city"].strip(),
            form.cleaned_data["date"],
        )
        add_forecast(offers)
    return render(request, "core/search.html", {
        "form": form,
        "offers": offers,
        "cities": city_choices(),
    })


def add_forecast(offers):
    """Прогноз свободных мест к отправлению для найденных рейсов (ФТ-3), если модель обучена."""
    upcoming = [offer for offer in offers if offer.departure > timezone.now() and offer.free_seats]
    forecasts = forecast_model.predict(Trip.objects.filter(pk__in=[o.trip.pk for o in upcoming]))
    for offer in upcoming:
        if offer.trip.pk in forecasts:
            offer.forecast_free = forecasts[offer.trip.pk].free_range(
                offer.from_stop.order, offer.to_stop.order
            )


@login_required
def cabinet(request):
    """Личный кабинет: выбираем содержимое по роли пользователя."""
    user = request.user
    if user.is_driver:
        return driver_cabinet(request)
    if user.is_dispatcher or user.is_admin_role:
        return staff_cabinet(request)
    return passenger_cabinet(request)


def passenger_cabinet(request):
    now = timezone.now()
    bookings = (
        Booking.objects.filter(passenger=request.user)
        .select_related("trip__route", "from_stop__stop", "to_stop__stop")
        .order_by("trip__departure_at")
    )
    upcoming = bookings.filter(trip__departure_at__gte=now, status=Booking.Status.ACTIVE)
    # История (ФТ-6): прошедшие поездки и отменённые брони, самые свежие сверху.
    history = bookings.exclude(pk__in=upcoming).order_by("-trip__departure_at")[:20]
    return render(request, "cabinet/passenger.html", {
        "upcoming": [(booking, booking.can_cancel(request.user)) for booking in upcoming],
        "history": history,
        "today": timezone.localdate(),
    })


def trips_with_load(trips):
    """Добавляет к каждому рейсу число занятых мест и процент загрузки для полосы на странице."""
    trips = trips.annotate(
        booked=Sum(
            "bookings__seats_count",
            filter=Q(bookings__status__in=Booking.OCCUPYING_STATUSES),
        ),
        bookings_count=Count(
            "bookings", filter=Q(bookings__status__in=Booking.OCCUPYING_STATUSES)
        ),
    ).select_related("route", "vehicle", "driver")
    result = []
    for trip in trips:
        trip.booked = trip.booked or 0
        trip.load_percent = round(100 * trip.booked / trip.capacity) if trip.capacity else 0
        result.append(trip)
    return result


def driver_cabinet(request):
    """Рейсы водителя на выбранный день (ФТ-8) и на неделю вперёд."""
    today = timezone.localdate()
    day = parse_date(request.GET.get("date", "")) or today
    trips = Trip.objects.filter(driver=request.user, departure_at__date=day).order_by("departure_at")
    upcoming = Trip.objects.filter(
        driver=request.user,
        departure_at__date__gt=day,
        departure_at__date__lte=day + timedelta(days=7),
    ).order_by("departure_at")
    return render(request, "cabinet/driver.html", {
        "today": today,
        "day": day,
        "prev_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1),
        "trips": trips_with_load(trips),
        "upcoming": trips_with_load(upcoming),
    })


def staff_cabinet(request):
    today = timezone.localdate()
    today_trips = trips_with_load(
        Trip.objects.filter(departure_at__date=today).order_by("departure_at")
    )
    week = Trip.objects.filter(
        departure_at__date__gte=today, departure_at__date__lt=today + timedelta(days=7)
    )
    active_bookings = Booking.objects.filter(
        status__in=Booking.OCCUPYING_STATUSES, trip__departure_at__gte=timezone.now()
    )
    stats = {
        "trips_today": len(today_trips),
        "trips_week": week.count(),
        "bookings_active": active_bookings.count(),
        "seats_sold": active_bookings.aggregate(s=Sum("seats_count"))["s"] or 0,
    }
    context = {"today": today, "trips": today_trips, "stats": stats}
    if request.user.is_admin_role:
        context["users_by_role"] = [
            (label, User.objects.filter(role=value).count())
            for value, label in User.Role.choices
        ]
    return render(request, "cabinet/staff.html", context)
