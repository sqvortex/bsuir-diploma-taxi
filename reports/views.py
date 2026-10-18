"""Страница «Отчёты» (ФТ-18) для диспетчера и администратора и выгрузка в Excel."""

from datetime import timedelta

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.models import User
from accounts.permissions import role_required
from transport.models import Route

from .services import MAX_DAYS, build_report, to_excel


def read_filters(request):
    """Период и маршрут из адреса. По умолчанию последние 30 дней, все маршруты."""
    today = timezone.localdate()
    date_to = parse_date(request.GET.get("to", "")) or today
    date_from = parse_date(request.GET.get("from", "")) or date_to - timedelta(days=29)
    error = None
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    if (date_to - date_from).days >= MAX_DAYS:
        date_from = date_to - timedelta(days=MAX_DAYS - 1)
        error = f"Период ограничен {MAX_DAYS} днями, начало сдвинуто."
    route_id = request.GET.get("route", "")
    route_id = int(route_id) if route_id.isdigit() else None
    return date_from, date_to, route_id, error


@role_required(User.Role.DISPATCHER, User.Role.ADMIN)
def overview(request):
    date_from, date_to, route_id, error = read_filters(request)
    report = build_report(date_from, date_to, route_id)
    chart = {
        "labels": [f"{day:%d.%m}" for day in report.by_day["day"]],
        "revenue": [float(value) for value in report.by_day["revenue"]],
        "load": [float(value) for value in report.by_day["load"]],
    }
    query = request.GET.copy()
    query["from"], query["to"] = date_from.isoformat(), date_to.isoformat()
    return render(request, "reports/overview.html", {
        "report": report,
        "chart": chart,
        "routes": Route.objects.order_by("name"),
        "route_id": route_id,
        "error": error,
        "date_from": date_from,
        "date_to": date_to,
        "excel_query": query.urlencode(),
        "trips": report.by_trip.sort_values("departure", ascending=False).head(30).to_dict("records"),
        "trips_total": len(report.by_trip),
    })


@role_required(User.Role.DISPATCHER, User.Role.ADMIN)
def download(request):
    date_from, date_to, route_id, _ = read_filters(request)
    report = build_report(date_from, date_to, route_id)
    response = HttpResponse(
        to_excel(report),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="report_{date_from:%Y%m%d}_{date_to:%Y%m%d}.xlsx"'
    return response
