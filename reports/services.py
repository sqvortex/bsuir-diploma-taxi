"""
Отчёты за период (ФТ-18, алгоритм 6): загрузка рейсов, выручка, доля неявок и отмен.

Данные берутся из базы в таблицы pandas, считаются сводки и по маршрутам,
и по рейсам, а потом те же таблицы выгружаются в Excel.

В отчёт входят рейсы, которые уже отправились, кроме отменённых рейсов.
Правила подсчёта:
* загрузка рейса — самый загруженный перегон, в процентах от мест в машине
  (места из неотменённых броней: пассажир сел, не явился или ещё не отмечен);
* выручка — стоимость броней, по которым пассажир сел или бронь ещё активна
  (оплата водителю при посадке, поэтому «не явился» денег не приносит);
* доля неявок и отмен — от числа всех броней за период.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from io import BytesIO

import pandas as pd
from django.utils import timezone

from bookings.models import Booking
from forecast.dataset import expand_legs
from transport.models import Trip

REVENUE_STATUSES = [Booking.Status.BOARDED, Booking.Status.ACTIVE]
# Колонки по статусам броней: ключ — значение статуса, подпись — для Excel.
STATUS_LABELS = {
    "boarded": "Сели",
    "active": "Ещё не отмечены",
    "no_show": "Не явились",
    "cancelled": "Отменили",
}
MAX_DAYS = 366  # больше года за раз не считаем: страница должна открываться быстро


@dataclass
class Report:
    date_from: object
    date_to: object
    summary: dict
    by_route: pd.DataFrame
    by_day: pd.DataFrame
    by_trip: pd.DataFrame


def period_bounds(date_from, date_to):
    """Начало первого и конец последнего дня периода по времени Минска."""
    start = timezone.make_aware(datetime.combine(date_from, time.min))
    end = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min))
    return start, end


def trips_frame(start, end, route_id, now):
    trips = Trip.objects.filter(
        departure_at__gte=start, departure_at__lt=min(end, now),
    ).exclude(status=Trip.Status.CANCELLED).select_related("route", "vehicle")
    if route_id:
        trips = trips.filter(route_id=route_id)
    rows = [{
        "trip": trip.pk,
        "route": trip.route.name,
        "departure": timezone.localtime(trip.departure_at),
        "capacity": trip.capacity,
    } for trip in trips.order_by("departure_at")]
    columns = ["trip", "route", "departure", "capacity"]
    return pd.DataFrame(rows, columns=columns)


def bookings_frame(trip_ids):
    rows = Booking.objects.filter(trip_id__in=trip_ids).values_list(
        "trip_id", "from_stop__order", "to_stop__order", "seats_count", "price", "status",
    )
    frame = pd.DataFrame(list(rows), columns=["trip", "from_order", "to_order", "seats", "price", "status"])
    frame["price"] = frame["price"].astype(float)
    return frame


def percent(part, total):
    return round(100 * part / total, 1) if total else 0.0


def build_report(date_from, date_to, route_id=None, now=None):
    now = now or timezone.now()
    start, end = period_bounds(date_from, date_to)
    trips = trips_frame(start, end, route_id, now)
    bookings = bookings_frame(trips["trip"].tolist())

    # Загрузка рейса: самый занятый перегон из неотменённых броней.
    live = bookings[bookings["status"] != Booking.Status.CANCELLED]
    if live.empty:
        peak = pd.Series(dtype=float, name="peak")
    else:
        per_leg = expand_legs(live, "from_order", "to_order")
        peak = per_leg.groupby(["trip", "leg"])["seats"].sum().groupby("trip").max().rename("peak")

    if bookings.empty:
        status = pd.DataFrame(columns=list(STATUS_LABELS), index=pd.Index([], name="trip"), dtype=int)
    else:
        status = bookings.pivot_table(index="trip", columns="status", values="seats", aggfunc="count", fill_value=0)
        status = status.reindex(columns=list(STATUS_LABELS), fill_value=0)
    revenue = bookings[bookings["status"].isin(REVENUE_STATUSES)].groupby("trip")["price"].sum().rename("revenue")
    passengers = bookings[bookings["status"].isin(REVENUE_STATUSES)].groupby("trip")["seats"].sum().rename("passengers")

    by_trip = trips.set_index("trip").join([peak, status, revenue, passengers]).fillna(0)
    for column in ["peak", "revenue", "passengers", *STATUS_LABELS]:
        if column not in by_trip:
            by_trip[column] = 0
    by_trip["bookings"] = by_trip[list(STATUS_LABELS)].sum(axis=1)
    by_trip["load"] = (100 * by_trip["peak"] / by_trip["capacity"]).round(1)
    by_trip["day"] = [moment.date() for moment in by_trip["departure"]]
    by_trip = by_trip.reset_index()

    return Report(
        date_from=date_from, date_to=date_to,
        summary=summarize(by_trip),
        by_route=group(by_trip, "route"),
        by_day=group(by_trip, "day"),
        by_trip=by_trip,
    )


def summarize(frame):
    bookings = int(frame["bookings"].sum()) if len(frame) else 0
    return {
        "trips": len(frame),
        "bookings": bookings,
        "passengers": int(frame["passengers"].sum()) if len(frame) else 0,
        "revenue": round(float(frame["revenue"].sum()), 2) if len(frame) else 0.0,
        "load": round(float(100 * frame["peak"].sum() / frame["capacity"].sum()), 1) if len(frame) and frame["capacity"].sum() else 0.0,
        "no_show": percent(int(frame["no_show"].sum()) if len(frame) else 0, bookings),
        "cancelled": percent(int(frame["cancelled"].sum()) if len(frame) else 0, bookings),
    }


def group(frame, key):
    """Те же показатели, что и в сводке, но отдельно по маршрутам или по дням."""
    rows = []
    for name, part in frame.groupby(key):
        row = summarize(part)
        rows.append({key: name, **row})
    return pd.DataFrame(rows, columns=[key, "trips", "bookings", "passengers", "revenue", "load", "no_show", "cancelled"])


# ---------- Выгрузка в Excel ----------

SUMMARY_NAMES = {
    "trips": "Рейсов", "bookings": "Броней", "passengers": "Пассажиров",
    "revenue": "Выручка, BYN", "load": "Средняя загрузка, %",
    "no_show": "Доля неявок, % от броней", "cancelled": "Доля отмен, % от броней",
}
COLUMN_NAMES = {
    "route": "Маршрут", "day": "Дата", "trips": "Рейсов", "bookings": "Броней",
    "passengers": "Пассажиров", "revenue": "Выручка, BYN", "load": "Загрузка, %",
    "no_show": "Неявки, %", "cancelled": "Отмены, %",
}


def to_excel(report):
    """Excel-файл с тремя листами: итоги, по маршрутам, по рейсам. Возвращает байты файла."""
    summary = pd.DataFrame(
        [(SUMMARY_NAMES[key], value) for key, value in report.summary.items()],
        columns=["Показатель", "Значение"],
    )
    summary.loc[len(summary)] = ["Период", f"{report.date_from:%d.%m.%Y} – {report.date_to:%d.%m.%Y}"]

    trips = report.by_trip.copy()
    trips["Дата и время"] = [moment.strftime("%d.%m.%Y %H:%M") for moment in trips["departure"]]
    trips = trips.rename(columns={"route": "Маршрут", "capacity": "Мест в машине", "peak": "Занято на пике",
                                  "load": "Загрузка, %", "revenue": "Выручка, BYN", "bookings": "Броней",
                                  **STATUS_LABELS})
    trips = trips[["Дата и время", "Маршрут", "Мест в машине", "Занято на пике", "Загрузка, %",
                   "Броней", *STATUS_LABELS.values(), "Выручка, BYN"]]
    trips["Занято на пике"] = trips["Занято на пике"].astype(int)

    by_route = report.by_route.rename(columns=COLUMN_NAMES)
    by_day = report.by_day.rename(columns=COLUMN_NAMES)

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, table in [("Итоги", summary), ("По маршрутам", by_route), ("По дням", by_day), ("По рейсам", trips)]:
            table.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            for column in sheet.columns:  # ширина колонки по самому длинному значению
                width = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column)
                sheet.column_dimensions[column[0].column_letter].width = min(width + 3, 45)
            sheet.freeze_panes = "A2"
    return buffer.getvalue()
