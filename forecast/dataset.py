"""
Подготовка данных для прогноза (алгоритм 4 из ТЗ).

Прогноз строится не для рейса целиком, а для каждого перегона — участка между
соседними остановками. Перегон 1 — от 1-й до 2-й остановки, перегон 2 — от 2-й
до 3-й и так далее. Бронь Минск → Гомель занимает все перегоны, бронь Минск → Бобруйск
только первый. Свободных мест на поездке столько, сколько на самом загруженном
перегоне по пути.

Одна строка обучающей таблицы — «рейс, перегон, за сколько дней до отправления»:

    признаки:  маршрут, перегон, день недели, время отправления, месяц,
               праздник, канун праздника, дней до отправления,
               сколько мест на перегоне продано к этому моменту, вместимость
    ответ:     сколько мест на перегоне было занято к отправлению
"""

import math
from datetime import timedelta

import pandas as pd
from django.utils import timezone

from bookings.models import Booking
from transport.models import RouteStop

from .holidays import is_holiday, is_pre_holiday

HORIZON_DAYS = 14  # прогноз строим не дальше чем на 14 дней вперёд (ФТ-15)

FEATURES = [
    "route", "leg", "weekday", "minutes", "month", "holiday", "pre_holiday",
    "days_before", "sold", "capacity",
]


def legs_of_routes(route_ids):
    """Сколько перегонов на каждом маршруте: {маршрут: число остановок − 1}."""
    counts = {}
    for route_id in RouteStop.objects.filter(route_id__in=route_ids).values_list("route_id", flat=True):
        counts[route_id] = counts.get(route_id, 0) + 1
    return {route_id: count - 1 for route_id, count in counts.items()}


def trips_frame(trips):
    """Таблица рейсов: маршрут, время отправления по Минску, вместимость и календарные признаки."""
    rows = []
    for trip in trips.select_related("vehicle"):
        local = timezone.localtime(trip.departure_at)
        rows.append({
            "trip": trip.pk,
            "route": trip.route_id,
            "departure": trip.departure_at,
            "capacity": trip.capacity,
            "weekday": local.isoweekday(),
            "minutes": local.hour * 60 + local.minute,
            "month": local.month,
            "holiday": int(is_holiday(local.date())),
            "pre_holiday": int(is_pre_holiday(local.date())),
        })
    return pd.DataFrame(rows)


def bookings_frame(trip_ids):
    """Брони рейсов: участок (номера остановок), места, когда создана и когда отменена."""
    rows = Booking.objects.filter(trip_id__in=trip_ids).values_list(
        "trip_id", "from_stop__order", "to_stop__order", "seats_count",
        "created_at", "cancelled_at", "status",
    )
    columns = ["trip", "from_order", "to_order", "seats", "created_at", "cancelled_at", "status"]
    return pd.DataFrame(list(rows), columns=columns)


def expand_legs(frame, start_col, end_col):
    """Разворачивает участок «с остановки A по остановку B» в строки по перегонам A … B−1."""
    frame = frame.copy()
    frame["leg"] = [list(range(a, b)) for a, b in zip(frame[start_col], frame[end_col])]
    return frame.explode("leg").astype({"leg": int})


def grid(trips, legs_count, horizons):
    """Все сочетания «рейс × перегон × дней до отправления»."""
    rows = []
    for trip in trips.itertuples():
        for leg in range(1, legs_count.get(trip.route, 0) + 1):
            for days in horizons:
                rows.append((trip.trip, leg, days))
    frame = pd.DataFrame(rows, columns=["trip", "leg", "days_before"])
    return frame.merge(trips, on="trip")


def training_table(trips_qs):
    """
    Обучающая таблица по выполненным рейсам. Для каждого дня до отправления d
    считаем, сколько мест на перегоне было продано к моменту «отправление − d дней»:
    бронь уже создана и ещё не отменена.
    """
    trips = trips_frame(trips_qs)
    if trips.empty:
        return pd.DataFrame(columns=FEATURES + ["trip", "target"])
    legs_count = legs_of_routes(trips["route"].unique())
    table = grid(trips, legs_count, range(HORIZON_DAYS + 1))

    bookings = bookings_frame(trips["trip"].tolist())
    if bookings.empty:
        table["sold"] = 0
        table["target"] = 0
        return table
    per_leg = expand_legs(bookings, "from_order", "to_order")
    per_leg = per_leg.merge(trips[["trip", "departure"]], on="trip")

    # Ответ: места, не отменённые к отправлению (сели или не пришли — место всё равно было занято).
    final = (
        per_leg[per_leg["status"] != Booking.Status.CANCELLED]
        .groupby(["trip", "leg"])["seats"].sum().rename("target")
    )

    # Продано к моменту «за d дней до отправления»
    sold_parts = []
    for days in range(HORIZON_DAYS + 1):
        moment = per_leg["departure"] - timedelta(days=days)
        alive = (per_leg["created_at"] <= moment) & (
            per_leg["cancelled_at"].isna() | (per_leg["cancelled_at"] > moment)
        )
        part = per_leg[alive].groupby(["trip", "leg"])["seats"].sum().rename("sold").reset_index()
        part["days_before"] = days
        sold_parts.append(part)
    sold = pd.concat(sold_parts)

    table = table.merge(sold, on=["trip", "leg", "days_before"], how="left")
    table = table.merge(final.reset_index(), on=["trip", "leg"], how="left")
    table[["sold", "target"]] = table[["sold", "target"]].fillna(0).astype(int)
    return table


def current_table(trips_qs, now=None):
    """
    Таблица для прогноза будущих рейсов: те же признаки, но «продано» — сейчас,
    а «дней до отправления» — от сегодняшнего дня.
    """
    now = now or timezone.now()
    trips = trips_frame(trips_qs)
    if trips.empty:
        return pd.DataFrame(columns=FEATURES + ["trip"])
    legs_count = legs_of_routes(trips["route"].unique())
    table = grid(trips, legs_count, [0])
    # Дни до отправления округляем вверх: до рейса через 5 часов — «1 день»,
    # ведь за эти часы ещё могут купить места.
    days = {
        trip_id: min(max(math.ceil((dep - now).total_seconds() / 86400), 0), HORIZON_DAYS)
        for trip_id, dep in zip(trips["trip"], trips["departure"])
    }
    table["days_before"] = table["trip"].map(days)

    bookings = bookings_frame(trips["trip"].tolist())
    bookings = bookings[bookings["status"].isin(Booking.OCCUPYING_STATUSES)]
    if bookings.empty:
        table["sold"] = 0
    else:
        sold = expand_legs(bookings, "from_order", "to_order").groupby(["trip", "leg"])["seats"].sum()
        table = table.merge(sold.rename("sold").reset_index(), on=["trip", "leg"], how="left")
        table["sold"] = table["sold"].fillna(0).astype(int)
    return table
