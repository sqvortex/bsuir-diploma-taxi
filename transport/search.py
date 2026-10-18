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
    forecast_free: tuple = None  # прогноз свободных мест к отправлению (от, до), если модель обучена

    @property
    def forecast_text(self):
        """Например: «к отправлению останется 0–2 места»."""
        if not self.forecast_free:
            return ""
        low, high = self.forecast_free
        amount = f"{low}" if low == high else f"{low}–{high}"
        return f"к отправлению останется {amount} {seats_word(high)}"

    @property
    def forecast_is_hot(self):
        """Мест к отправлению почти не останется: стоит бронировать заранее."""
        return bool(self.forecast_free) and self.forecast_free[0] <= 2

    @property
    def duration_minutes(self):
        return self.from_stop.minutes_to(self.to_stop)

    @property
    def duration_display(self):
        hours, minutes = divmod(self.duration_minutes, 60)
        return f"{hours} ч {minutes:02d} мин" if hours else f"{minutes} мин"


def seats_word(number):
    """Слово «место» в нужной форме: 1 место, 2 места, 5 мест."""
    if number % 10 == 1 and number % 100 != 11:
        return "место"
    if number % 10 in (2, 3, 4) and number % 100 not in (12, 13, 14):
        return "места"
    return "мест"


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

    trips = list(trips)
    stops_by_route = stops_of_routes({trip.route_id for trip in trips})
    taken_by_trip = occupied_segments({trip.pk for trip in trips})

    offers = []
    for trip in trips:
        stops = stops_by_route[trip.route_id]
        boarding = next((s for s in stops if s.stop.city.lower() == from_city.lower()), None)
        if boarding is None:
            continue
        leaving = next(
            (s for s in stops if s.order > boarding.order and s.stop.city.lower() == to_city.lower()),
            None,
        )
        if leaving is None:
            continue  # город прибытия стоит раньше города отправления
        busy = sum(
            seats for start, end, seats in taken_by_trip.get(trip.pk, [])
            if start < leaving.order and end > boarding.order
        )
        offers.append(TripOffer(
            trip=trip,
            from_stop=boarding,
            to_stop=leaving,
            departure=trip.time_at(boarding),
            arrival=trip.time_at(leaving),
            price=boarding.price_to(leaving),
            free_seats=max(trip.capacity - busy, 0),
        ))
    return offers


def stops_of_routes(route_ids):
    """Остановки сразу всех маршрутов одним запросом: {id маршрута: остановки по порядку}."""
    result = {route_id: [] for route_id in route_ids}
    for route_stop in RouteStop.objects.filter(route_id__in=route_ids).select_related("stop").order_by("order"):
        result[route_stop.route_id].append(route_stop)
    return result


def occupied_segments(trip_ids):
    """Занятые места сразу у всех рейсов одним запросом: {id рейса: [(с какой, по какую, мест)]}."""
    from bookings.models import Booking

    rows = Booking.objects.filter(trip_id__in=trip_ids, status__in=Booking.OCCUPYING_STATUSES).values_list(
        "trip_id", "from_stop__order", "to_stop__order", "seats_count"
    )
    result = {}
    for trip_id, start, end, seats in rows:
        result.setdefault(trip_id, []).append((start, end, seats))
    return result
