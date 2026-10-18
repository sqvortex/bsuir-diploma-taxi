"""
Рекомендации диспетчеру по прогнозу загрузки (алгоритм 5 из ТЗ).

* Прогноз (с учётом возможной ошибки) больше вместимости — пассажирам может
  не хватить мест: предлагаем добавить рейс или поставить машину побольше.
* Загрузка ниже 30% — машина едет полупустой: предлагаем совместить рейс
  с соседним рейсом того же маршрута в этот день, если всем хватит мест,
  или поставить машину поменьше.
"""

import math
from dataclasses import dataclass

from django.utils import timezone

from transport.models import Vehicle

LOW_LOAD_PERCENT = 30


@dataclass
class Recommendation:
    trip: object
    kind: str   # "full" — мест не хватит, "low" — низкая загрузка
    text: str


def time_of(trip):
    return f"{timezone.localtime(trip.departure_at):%H:%M}"


def recommend(trips, forecasts):
    """trips — рейсы по времени отправления, forecasts — {id рейса: TripForecast}."""
    biggest = Vehicle.objects.filter(is_active=True).order_by("-seats").first()
    result = []
    for trip in trips:
        forecast = forecasts.get(trip.pk)
        if not forecast or not forecast.capacity:
            continue
        peak = forecast.peak()
        demand = math.ceil(peak.high)  # сколько пассажиров может прийти при неудачном раскладе
        if demand > forecast.capacity:
            text = (f"Может прийти до {demand} пассажиров при {forecast.capacity} местах. "
                    "Добавьте рейс")
            if biggest and biggest.seats > forecast.capacity:
                text += f" или поставьте машину побольше ({biggest.brand}, {biggest.seats} мест)"
            result.append(Recommendation(trip, "full", text + "."))
        elif forecast.load_percent < LOW_LOAD_PERCENT:
            neighbour = find_neighbour(trip, trips, forecasts)
            if neighbour:
                together = round(forecast.expected_load + forecasts[neighbour.pk].expected_load)
                text = (f"Загрузка около {forecast.load_percent}%. Можно совместить с рейсом "
                        f"в {time_of(neighbour)}: вместе около {together} пассажиров "
                        f"при {neighbour.capacity} местах.")
            else:
                text = f"Загрузка около {forecast.load_percent}%. Можно поставить машину поменьше."
            result.append(Recommendation(trip, "low", text))
    return result


def find_neighbour(trip, trips, forecasts):
    """Ближайший по времени рейс того же маршрута в тот же день, куда поместятся все пассажиры."""
    day = timezone.localdate(trip.departure_at)
    own = forecasts[trip.pk]
    candidates = [
        other for other in trips
        if other.pk != trip.pk and other.route_id == trip.route_id
        and timezone.localdate(other.departure_at) == day and other.pk in forecasts
        and own.peak().high + forecasts[other.pk].peak().expected <= other.capacity
    ]
    return min(candidates, key=lambda other: abs(other.departure_at - trip.departure_at), default=None)
