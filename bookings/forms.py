from django import forms
from django.conf import settings
from django.utils import timezone

from accounts.models import phone_validator
from core.forms import BootstrapFormMixin


class StopChoiceField(forms.ModelChoiceField):
    """Список остановок рейса с временем: «08:30 · Бобруйск, Автовокзал»."""

    def __init__(self, trip, **kwargs):
        self.trip = trip
        super().__init__(queryset=trip.route.ordered_stops(), empty_label=None, **kwargs)

    def label_from_instance(self, route_stop):
        time = timezone.localtime(self.trip.time_at(route_stop))
        return f"{time:%H:%M} · {route_stop.stop}"


class BookingForm(BootstrapFormMixin, forms.Form):
    """
    Форма брони места (ФТ-4). Её заполняет пассажир на сайте
    или диспетчер, когда бронирует по телефонному звонку (ФТ-14).
    """

    seats_count = forms.IntegerField(
        label="Мест", min_value=1, max_value=settings.BOOKING_MAX_SEATS, initial=1,
    )
    passenger_name = forms.CharField(label="Имя пассажира", max_length=150)
    passenger_phone = forms.CharField(
        label="Телефон пассажира", max_length=13, validators=[phone_validator],
        widget=forms.TextInput(attrs={"placeholder": "+375291234567", "inputmode": "tel"}),
    )

    def __init__(self, *args, trip, **kwargs):
        super().__init__(*args, **kwargs)
        # Поля остановок добавляем отдельно: список зависит от маршрута рейса.
        self.fields = {
            "from_stop": StopChoiceField(trip, label="Посадка"),
            "to_stop": StopChoiceField(trip, label="Высадка"),
            **self.fields,
        }
        for name in ("from_stop", "to_stop"):
            self.fields[name].widget.attrs["class"] = "form-select"

    def clean(self):
        data = super().clean()
        if data.get("from_stop") and data.get("to_stop"):
            if data["from_stop"].order >= data["to_stop"].order:
                raise forms.ValidationError("Остановка высадки должна быть после остановки посадки.")
        return data
