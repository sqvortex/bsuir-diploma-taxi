"""
Страница «Прогноз» в панели диспетчера (ФТ-15): заполняемость рейсов
на 14 дней вперёд, рекомендации и точность модели.
"""

from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.models import User
from accounts.permissions import role_required
from transport.models import Trip

from . import model
from .dataset import HORIZON_DAYS
from .recommend import recommend


@role_required(User.Role.DISPATCHER, User.Role.ADMIN)
def overview(request):
    bundle = model.load()
    today = timezone.localdate()
    days = [today + timedelta(days=shift) for shift in range(HORIZON_DAYS)]
    selected = parse_date(request.GET.get("date", "")) or today
    if selected not in days:
        selected = today
    if bundle is None:
        return render(request, "forecast/overview.html", {"bundle": None})

    trips = list(
        Trip.objects.filter(
            status=Trip.Status.SCHEDULED, vehicle__isnull=False,
            departure_at__gte=timezone.now(), departure_at__date__lte=days[-1],
        ).select_related("route", "vehicle", "driver").order_by("departure_at")
    )
    forecasts = model.predict(Trip.objects.filter(pk__in=[trip.pk for trip in trips]), bundle=bundle)
    recommendations = recommend(trips, forecasts)
    advice = {rec.trip.pk: rec for rec in recommendations}

    # Данные для графика: по каждому дню — продано сейчас, ожидается ещё, всего мест.
    chart = {"labels": [], "dates": [], "sold": [], "extra": [], "capacity": []}
    for day in days:
        day_trips = [t for t in trips if timezone.localdate(t.departure_at) == day and t.pk in forecasts]
        if not day_trips:
            continue  # на этот день рейсы ещё не созданы
        sold = sum(forecasts[t.pk].peak().sold for t in day_trips)
        expected = sum(forecasts[t.pk].expected_load for t in day_trips)
        chart["labels"].append(f"{day:%d.%m}")
        chart["dates"].append(day.isoformat())
        chart["sold"].append(sold)
        chart["extra"].append(round(max(expected - sold, 0), 1))
        chart["capacity"].append(sum(t.capacity for t in day_trips))

    rows = []
    for trip in trips:
        forecast = forecasts.get(trip.pk)
        if forecast and timezone.localdate(trip.departure_at) == selected:
            peak = forecast.peak()
            rows.append({
                "trip": trip,
                "forecast": forecast,
                "sold": peak.sold,
                "expected": round(forecast.expected_load),
                "sold_percent": round(100 * peak.sold / forecast.capacity),
                "extra_percent": max(forecast.load_percent - round(100 * peak.sold / forecast.capacity), 0),
                "free": forecast.free_range(),
                "advice": advice.get(trip.pk),
            })

    return render(request, "forecast/overview.html", {
        "bundle": bundle,
        "report": bundle["report"],
        "days": days,
        "selected": selected,
        "chart": chart,
        "rows": rows,
        "recommendations": recommendations,
    })
