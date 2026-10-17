"""
Панель диспетчера (ФТ-11, ФТ-12, ФТ-13, ФТ-17).

Страницы доступны диспетчеру и администратору. Автопарк по ТЗ ведёт
администратор, поэтому изменять машины может только он.

Большинство страниц сделаны на стандартных классах Django:
ListView показывает список, CreateView и UpdateView показывают форму
и сохраняют её. Нам остаётся указать модель, форму и шаблон.
"""

from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import CreateView, ListView, UpdateView

from accounts.models import User
from accounts.permissions import RoleRequiredMixin, role_required
from bookings.models import Booking
from transport.models import Route, ScheduleTemplate, Stop, Trip, Vehicle
from transport.schedule import generate_trips

from .forms import (
    GenerateTripsForm, RouteForm, RouteStopFormSet, ScheduleTemplateForm,
    StopForm, TripForm, VehicleForm,
)

STAFF = [User.Role.DISPATCHER, User.Role.ADMIN]


class StaffMixin(RoleRequiredMixin):
    allowed_roles = STAFF


class SimpleFormMixin:
    """Общая страница с одной формой: заголовок, кнопка «Сохранить», сообщение об успехе."""

    template_name = "dispatch/form.html"
    title = ""
    back_url = None
    success_message = "Сохранено."

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = self.title
        context["back_url"] = self.back_url or self.success_url
        return context

    def form_valid(self, form):
        messages.success(self.request, self.success_message)
        return super().form_valid(form)


# ---------- Остановки ----------

class StopList(StaffMixin, ListView):
    model = Stop
    template_name = "dispatch/stop_list.html"


class StopCreate(StaffMixin, SimpleFormMixin, CreateView):
    model = Stop
    form_class = StopForm
    title = "Новая остановка"
    success_url = reverse_lazy("dispatch:stops")
    success_message = "Остановка добавлена."


class StopUpdate(StaffMixin, SimpleFormMixin, UpdateView):
    model = Stop
    form_class = StopForm
    title = "Остановка"
    success_url = reverse_lazy("dispatch:stops")


# ---------- Маршруты (ФТ-11) ----------

class RouteList(StaffMixin, ListView):
    template_name = "dispatch/route_list.html"

    def get_queryset(self):
        return Route.objects.prefetch_related("route_stops__stop").annotate(
            templates_count=Count("templates", distinct=True)
        )


@role_required(*STAFF)
def route_edit(request, pk=None):
    """Маршрут и его остановки редактируются на одной странице."""
    route = get_object_or_404(Route, pk=pk) if pk else Route()
    form = RouteForm(request.POST or None, instance=route)
    formset = RouteStopFormSet(request.POST or None, instance=route, prefix="stops")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            route = form.save()
            formset.instance = route
            formset.save()
        messages.success(request, f"Маршрут «{route}» сохранён.")
        return redirect("dispatch:routes")

    return render(request, "dispatch/route_form.html", {
        "form": form,
        "formset": formset,
        "route": route if pk else None,
    })


# ---------- Автопарк (ФТ-17) ----------

class VehicleList(StaffMixin, ListView):
    model = Vehicle
    template_name = "dispatch/vehicle_list.html"


class VehicleCreate(RoleRequiredMixin, SimpleFormMixin, CreateView):
    allowed_roles = [User.Role.ADMIN]
    model = Vehicle
    form_class = VehicleForm
    title = "Новая машина"
    success_url = reverse_lazy("dispatch:vehicles")
    success_message = "Машина добавлена в автопарк."


class VehicleUpdate(RoleRequiredMixin, SimpleFormMixin, UpdateView):
    allowed_roles = [User.Role.ADMIN]
    model = Vehicle
    form_class = VehicleForm
    title = "Машина"
    success_url = reverse_lazy("dispatch:vehicles")


# ---------- Расписание (ФТ-12) ----------

class TemplateList(StaffMixin, ListView):
    template_name = "dispatch/template_list.html"

    def get_queryset(self):
        return ScheduleTemplate.objects.select_related(
            "route", "default_vehicle", "default_driver"
        ).order_by("route__name", "departure_time")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["generate_form"] = GenerateTripsForm()
        return context


class TemplateCreate(StaffMixin, SimpleFormMixin, CreateView):
    model = ScheduleTemplate
    form_class = ScheduleTemplateForm
    title = "Новый шаблон расписания"
    success_url = reverse_lazy("dispatch:templates")
    success_message = "Шаблон добавлен. Не забудьте создать по нему рейсы."

    def get_initial(self):
        return {"valid_from": timezone.localdate(), "weekdays": "1234567"}


class TemplateUpdate(StaffMixin, SimpleFormMixin, UpdateView):
    model = ScheduleTemplate
    form_class = ScheduleTemplateForm
    title = "Шаблон расписания"
    success_url = reverse_lazy("dispatch:templates")
    success_message = "Шаблон сохранён. Уже созданные рейсы не меняются."


@role_required(*STAFF)
def trips_generate(request):
    """Кнопка «Создать рейсы»: рейсы по всем шаблонам на N дней вперёд."""
    form = GenerateTripsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        today = timezone.localdate()
        result = generate_trips(today, today + timedelta(days=form.cleaned_data["days"] - 1))
        messages.success(
            request,
            f"Создано рейсов: {result.created}. Уже были в расписании: {result.existing}.",
        )
    return redirect("dispatch:templates")


# ---------- Рейсы (ФТ-13) ----------

@role_required(*STAFF)
def trip_list(request):
    """Рейсы за выбранный день с загрузкой и назначенными машиной и водителем."""
    day = parse_date(request.GET.get("date", "")) or timezone.localdate()
    trips = (
        Trip.objects.filter(departure_at__date=day)
        .select_related("route", "vehicle", "driver")
        .annotate(booked=Sum(
            "bookings__seats_count",
            filter=Q(bookings__status__in=Booking.OCCUPYING_STATUSES),
        ))
        .order_by("departure_at", "route__name")
    )
    for trip in trips:
        trip.booked = trip.booked or 0
        trip.load_percent = round(100 * trip.booked / trip.capacity) if trip.capacity else 0
        trip.needs_attention = trip.status == Trip.Status.SCHEDULED and not (trip.vehicle_id and trip.driver_id)
    return render(request, "dispatch/trip_list.html", {
        "day": day,
        "prev_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1),
        "trips": trips,
    })


class TripUpdate(StaffMixin, SimpleFormMixin, UpdateView):
    model = Trip
    form_class = TripForm
    title = "Рейс"
    success_message = "Рейс сохранён."

    def get_success_url(self):
        day = timezone.localdate(self.object.departure_at)
        return f"{reverse('dispatch:trips')}?date={day.isoformat()}"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = str(self.object)
        context["back_url"] = self.get_success_url()
        return context
