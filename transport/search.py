"""
Поиск рейсов с учётом промежуточных остановок (алгоритм 1 из ТЗ)
и подсчёт свободных мест на участке (алгоритм 2).

Защита от двойной продажи (транзакция и блокировка рейса)
находится в bookings/services.py.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db.models import Sum

from .models import RouteStop, Trip


@dataclass
class TripOffer:
    """Один найденный вариант поездки: рейс и участок от посадки до высадки."""

    trip: Trip
    from_stop: RouteStop
    to_stop: RouteStop
    departure: datetime
    arrival: datetime
    price: Decimal
    free_seats: int

    @property
    def duration_minutes(self):
        return self.from_stop.minutes_to(self.to_stop)

    @property
    def duration_display(self):
        hours, minutes = divmod(self.duration_minutes, 60)
        return f"{hours} ч {minutes:02d} мин" if hours else f"{minutes} мин"


def free_seats(trip, from_stop, to_stop):
    """
    Сколько мест свободно на участке from_stop → to_stop.

    Бронь мешает, только если её участок пересекается с нашим:
    она начинается раньше, чем мы выходим, и заканчивается позже, чем мы садимся.
    Например, бронь Минск → Бобруйск не мешает поездке Бобруйск → Гомель.
    """
    from bookings.models import Booking  # импорт здесь, чтобы не было циклического импорта

    taken = (
        Booking.objects.filter(
            trip=trip,
            status__in=Booking.OCCUPYING_STATUSES,
            from_stop__order__lt=to_stop.order,
            to_stop__order__gt=from_stop.order,
        ).aggregate(total=Sum("seats_count"))["total"]
        or 0
    )
    return max(trip.capacity - taken, 0)


def free_seats_by_segment(trip, stops):
    """
    Свободные места для всех пар «посадка → высадка» рейса сразу.
    Нужно странице брони, чтобы при смене остановок число мест обновлялось без перезагрузки.
    Возвращает словарь {(id посадки, id высадки): свободно}.
    """
    from bookings.models import Booking

    taken = list(
        Booking.objects.filter(trip=trip, status__in=Booking.OCCUPYING_STATUSES)
        .values_list("from_stop__order", "to_stop__order", "seats_count")
    )
    result = {}
    for a in stops:
        for b in stops:
            if a.order < b.order:
                busy = sum(seats for start, end, seats in taken if start < b.order and end > a.order)
                result[(a.pk, b.pk)] = max(trip.capacity - busy, 0)
    return result


def find_trips(from_city, to_city, day):
    """
    Рейсы на дату day, которые проходят через from_city и затем через to_city.

    Рейс подходит, если на его маршруте есть остановка в городе отправления,
    а позже по порядку — остановка в городе прибытия.
    """
    trips = (
        Trip.objects.filter(
            departure_at__date=day,
            status=Trip.Status.SCHEDULED,
            route__is_active=True,
            route__route_stops__stop__city__iexact=from_city,
        )
        .filter(route__route_stops__stop__city__iexact=to_city)
        .select_related("route", "vehicle")
        .distinct()
        .order_by("departure_at")
    )

    offers = []
    for trip in trips:
        stops = list(trip.route.ordered_stops())
        boarding = next((s for s in stops if s.stop.city.lower() == from_city.lower()), None)
        if boarding is None:
            continue
        leaving = next(
            (s for s in stops if s.order > boarding.order and s.stop.city.lower() == to_city.lower()),
            None,
        )
        if leaving is None:
            continue  # город прибытия стоит раньше города отправления
        offers.append(TripOffer(
            trip=trip,
            from_stop=boarding,
            to_stop=leaving,
            departure=trip.time_at(boarding),
            arrival=trip.time_at(leaving),
            price=boarding.price_to(leaving),
            free_seats=free_seats(trip, boarding, leaving),
        ))
    return offers
