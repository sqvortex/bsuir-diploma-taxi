"""
Модель спроса для демо-данных: по ней создаются история перевозок (generate_history)
и брони на ближайшие рейсы (load_demo). Настоящих данных перевозчика у нас нет,
поэтому спрос задаётся понятными правилами:

* в пятницу и воскресенье едут больше, во вторник и среду меньше;
* утренние и вечерние рейсы загружены сильнее дневных;
* летом и в декабре спрос выше, в январе–феврале ниже;
* накануне праздников спрос резко растёт, в сами праздники падает;
* большинство броней делают за 0–5 дней до поездки, часть заранее;
* около 8% броней отменяют, около 5% пассажиров не приходят.
"""

import math
from datetime import timedelta

from django.utils import timezone

from bookings.models import Booking

from .holidays import is_holiday, is_pre_holiday

WEEKDAY_FACTOR = {1: 0.9, 2: 0.75, 3: 0.75, 4: 0.9, 5: 1.3, 6: 0.95, 7: 1.25}
MONTH_FACTOR = {1: 0.8, 2: 0.85, 6: 1.15, 7: 1.2, 8: 1.15, 12: 1.1}
NAMES = ["Анна", "Дмитрий", "Ольга", "Сергей", "Мария", "Алексей", "Елена", "Павел",
         "Ирина", "Андрей", "Татьяна", "Николай", "Юлия", "Максим", "Светлана", "Артём"]


def time_factor(departure_time):
    if departure_time.hour < 10:
        return 1.1   # утром едут на работу и учёбу
    if departure_time.hour < 15:
        return 0.75  # днём свободнее
    return 1.15      # вечером возвращаются


def demand_factor(day, departure_time):
    factor = WEEKDAY_FACTOR[day.isoweekday()] * MONTH_FACTOR.get(day.month, 1.0)
    factor *= time_factor(departure_time)
    if is_pre_holiday(day):
        factor *= 1.5
    elif is_holiday(day):
        factor *= 0.7
    return factor


def expected_seats(trip):
    """Сколько мест в среднем хотят купить на этот рейс."""
    local = timezone.localtime(trip.departure_at)
    route_level = 0.45 + 0.1 * (trip.route_id % 3)  # маршруты немного отличаются по спросу
    return trip.capacity * route_level * demand_factor(local.date(), local.time())


def poisson(rng, mean):
    """Случайное число со средним mean (распределение Пуассона)."""
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p < limit:
            return k
        k += 1


def simulate_bookings(rng, trip, stops, now=None):
    """
    Брони одного рейса: случайные участки, время брони до отправления, отмены и неявки.

    Без now рейс считается выполненным: у броней итоговые статусы «сел», «не явился», «отменена».
    С now рейс ещё впереди: остаются только брони, сделанные до now, со статусом «активна»
    (или «отменена», если пассажир уже успел отменить).
    """
    capacity = trip.capacity
    legs = [0] * (len(stops) - 1)  # сколько мест занято на каждом перегоне
    requests = []
    # Каждая бронь в среднем на 1,2 места; примерно половина едет не до конечной.
    for _ in range(poisson(rng, expected_seats(trip))):
        if rng.random() < 0.55:
            start, end = 0, len(stops) - 1
        else:
            start = rng.randint(0, len(stops) - 2)
            end = rng.randint(start + 1, len(stops) - 1)
        seats = 2 if rng.random() < 0.2 else 1
        lead_days = min(rng.expovariate(1 / 2.5), 20)  # обычно бронируют за 0–5 дней
        created = trip.departure_at - timedelta(days=lead_days, minutes=rng.randint(10, 600))
        requests.append((created, start, end, seats))

    bookings = []
    for created, start, end, seats in sorted(requests):
        if now and created > now:
            break  # эту бронь ещё не сделали
        if any(legs[i] + seats > capacity for i in range(start, end)):
            continue  # мест на участке уже нет, человек поехал другим рейсом
        status, cancelled_at = Booking.Status.BOARDED, None
        roll = rng.random()
        if roll < 0.08:
            cancelled_at = created + (trip.departure_at - created) * rng.random()
            status = Booking.Status.CANCELLED
            if now and cancelled_at > now:
                status, cancelled_at = Booking.Status.ACTIVE, None  # ещё не отменили
        elif roll < 0.13:
            status = Booking.Status.NO_SHOW
        if now and status != Booking.Status.CANCELLED:
            status = Booking.Status.ACTIVE  # рейс впереди: о посадке пока ничего не известно
        if status != Booking.Status.CANCELLED:
            for i in range(start, end):
                legs[i] += seats
        from_stop, to_stop = stops[start], stops[end]
        bookings.append(Booking(
            trip=trip, from_stop=from_stop, to_stop=to_stop, seats_count=seats,
            price=from_stop.price_to(to_stop) * seats, status=status,
            passenger_name=rng.choice(NAMES),
            passenger_phone=f"+37529{rng.randint(1000000, 9999999)}",
            created_at=created, cancelled_at=cancelled_at,
        ))
    return bookings
