"""Формы панели диспетчера."""

from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import F, Q, Sum

from accounts.models import User
from bookings.models import Booking
from core.forms import BootstrapFormMixin
from transport.models import Route, RouteStop, ScheduleTemplate, Stop, Trip, Vehicle


class StopForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Stop
        fields = ["city", "name"]


class RouteForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Route
        fields = ["name", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_active"].widget.attrs["class"] = "form-check-input"


class RouteStopForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = RouteStop
        fields = ["order", "stop", "minutes_from_start", "price_from_start"]
        labels = {
            "order": "№",
            "minutes_from_start": "Минут от начала",
            "price_from_start": "Цена от начала, BYN",
        }


class BaseRouteStopFormSet(forms.BaseInlineFormSet):
    """
    Проверки остановок маршрута целиком (ФТ-11):
    - остановок не меньше двух, номера 1, 2, 3, ... без пропусков;
    - одна и та же остановка не повторяется;
    - время и цена от начала растут от остановки к остановке,
      иначе цена или время по участку получились бы отрицательными.
    """

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        rows = [
            form.cleaned_data for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        for form in self.forms:
            if form.cleaned_data.get("DELETE") and form.instance.pk and Booking.objects.filter(
                Q(from_stop=form.instance) | Q(to_stop=form.instance)
            ).exists():
                raise ValidationError(f"Остановку «{form.instance.stop}» нельзя удалить: на неё есть брони.")
        if len(rows) < 2:
            raise ValidationError("У маршрута должно быть хотя бы две остановки.")

        rows.sort(key=lambda row: row["order"])
        if [row["order"] for row in rows] != list(range(1, len(rows) + 1)):
            raise ValidationError("Номера остановок должны идти подряд: 1, 2, 3, ...")
        if len({row["stop"].pk for row in rows}) != len(rows):
            raise ValidationError("Одна и та же остановка указана дважды.")
        if rows[0]["minutes_from_start"] != 0 or rows[0]["price_from_start"] != 0:
            raise ValidationError("У первой остановки время и цена от начала должны быть 0.")
        for prev, cur in zip(rows, rows[1:]):
            if cur["minutes_from_start"] <= prev["minutes_from_start"]:
                raise ValidationError(f"Время до остановки №{cur['order']} должно быть больше, чем до №{prev['order']}.")
            if cur["price_from_start"] < prev["price_from_start"]:
                raise ValidationError(f"Цена до остановки №{cur['order']} не может быть меньше, чем до №{prev['order']}.")

    def save(self, commit=True):
        """
        Сохраняем остановки сами, а не стандартным способом.

        Номер остановки уникален внутри маршрута, поэтому если поменять местами
        №2 и №3, база не даст сохранить первую из них. Поэтому сначала временно
        сдвигаем все старые номера на 1000, а потом записываем новые.
        """
        route = self.instance
        route.route_stops.update(order=F("order") + 1000)
        for form in self.forms:
            data = form.cleaned_data
            if not data:
                continue  # пустая строка для новой остановки
            if data.get("DELETE"):
                if form.instance.pk:
                    form.instance.delete()
                continue
            route_stop = form.save(commit=False)
            route_stop.route = route
            route_stop.save()


RouteStopFormSet = forms.inlineformset_factory(
    Route, RouteStop, form=RouteStopForm, formset=BaseRouteStopFormSet,
    extra=2, can_delete=True,
)


class VehicleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ["brand", "plate_number", "seats", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_active"].widget.attrs["class"] = "form-check-input"


class ScheduleTemplateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ScheduleTemplate
        fields = [
            "route", "departure_time", "weekdays",
            "default_vehicle", "default_driver", "valid_from", "valid_to",
        ]
        widgets = {
            "departure_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "valid_from": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "valid_to": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["route"].queryset = Route.objects.filter(is_active=True)
        self.fields["default_vehicle"].queryset = Vehicle.objects.filter(is_active=True)
        self.fields["default_driver"].queryset = User.objects.filter(role=User.Role.DRIVER, is_active=True)

    def clean(self):
        data = super().clean()
        if data.get("valid_to") and data.get("valid_from") and data["valid_to"] < data["valid_from"]:
            self.add_error("valid_to", "Дата окончания раньше даты начала.")
        return data


class GenerateTripsForm(BootstrapFormMixin, forms.Form):
    days = forms.IntegerField(
        label="На сколько дней вперёд", min_value=1, max_value=60, initial=14
    )


def trip_interval(trip):
    """Время, когда машина и водитель заняты рейсом: от отправления до прибытия на конечную."""
    last = trip.route.route_stops.order_by("-order").first()
    duration = timedelta(minutes=last.minutes_from_start if last else 0)
    return trip.departure_at, trip.departure_at + duration


class TripForm(BootstrapFormMixin, forms.ModelForm):
    """
    Назначение на рейс машины и водителя (ФТ-13).

    Проверяем, что машина и водитель не заняты другим рейсом в это же время
    и что в новой машине хватит мест для уже проданных броней.
    """

    class Meta:
        model = Trip
        fields = ["vehicle", "driver", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(is_active=True)
        self.fields["driver"].queryset = User.objects.filter(role=User.Role.DRIVER, is_active=True)

    def clean(self):
        data = super().clean()
        trip = self.instance
        vehicle, driver = data.get("vehicle"), data.get("driver")

        if vehicle:
            booked = trip.bookings.filter(status__in=Booking.OCCUPYING_STATUSES).aggregate(
                s=Sum("seats_count"))["s"] or 0
            # Мест должно хватить хотя бы на самый загруженный участок;
            # для простоты сравниваем с общим числом проданных мест.
            if booked > vehicle.seats:
                self.add_error("vehicle", f"В этой машине {vehicle.seats} мест, а продано уже {booked}.")

        start, end = trip_interval(trip)
        # Рейсы, которые могут пересечься по времени (идут не дольше суток).
        nearby = Trip.objects.filter(
            status=Trip.Status.SCHEDULED,
            departure_at__lt=end,
            departure_at__gt=start - timedelta(days=1),
        ).exclude(pk=trip.pk).filter(Q(vehicle=vehicle) | Q(driver=driver)).select_related("route")
        for other in nearby:
            other_start, other_end = trip_interval(other)
            if other_start < end and start < other_end:
                if vehicle and other.vehicle_id == vehicle.pk:
                    self.add_error("vehicle", f"Машина уже занята на рейсе «{other}».")
                if driver and other.driver_id == driver.pk:
                    self.add_error("driver", f"Водитель уже занят на рейсе «{other}».")
        return data
