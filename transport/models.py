"""
Всё, что относится к перевозке: остановки, маршруты, автопарк,
шаблоны расписания и конкретные рейсы.

Как эти модели связаны:

    Stop (остановка)  ─┐
                       ├─ RouteStop (остановка на маршруте: порядок, время, цена)
    Route (маршрут)   ─┘
       │
       ├─ ScheduleTemplate (шаблон: «каждый пн–пт в 07:30»)
       │        │ по шаблону создаются
       └─ Trip (рейс: конкретная дата и время, машина, водитель)
                │
                └─ Vehicle (машина: номер и число мест)
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


class Stop(models.Model):
    """Остановка, например «Минск, автовокзал Восточный»."""

    city = models.CharField("город", max_length=100)
    name = models.CharField("название остановки", max_length=150)

    class Meta:
        verbose_name = "остановка"
        verbose_name_plural = "остановки"
        ordering = ["city", "name"]
        constraints = [
            models.UniqueConstraint(fields=["city", "name"], name="unique_stop_in_city"),
        ]

    def __str__(self):
        return f"{self.city}, {self.name}"


class Route(models.Model):
    """Маршрут — упорядоченный список остановок (ФТ-11)."""

    name = models.CharField("название", max_length=150, help_text="Например: Минск – Гомель")
    is_active = models.BooleanField("действует", default=True)

    class Meta:
        verbose_name = "маршрут"
        verbose_name_plural = "маршруты"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def ordered_stops(self):
        """Остановки маршрута по порядку следования."""
        return self.route_stops.select_related("stop").order_by("order")


class RouteStop(models.Model):
    """
    Остановка в составе маршрута.

    Время и цена хранятся «от начала маршрута». Тогда время и стоимость
    поездки по любому участку считаются вычитанием:
    цена(Бобруйск → Гомель) = цена до Гомеля − цена до Бобруйска.
    """

    route = models.ForeignKey(
        Route, on_delete=models.CASCADE, related_name="route_stops", verbose_name="маршрут"
    )
    stop = models.ForeignKey(Stop, on_delete=models.PROTECT, verbose_name="остановка")
    order = models.PositiveSmallIntegerField(
        "порядковый номер", help_text="1 — начальная остановка, дальше по порядку"
    )
    minutes_from_start = models.PositiveIntegerField(
        "минут от начала маршрута", default=0
    )
    price_from_start = models.DecimalField(
        "цена от начала маршрута, BYN", max_digits=7, decimal_places=2, default=0
    )

    class Meta:
        verbose_name = "остановка маршрута"
        verbose_name_plural = "остановки маршрута"
        ordering = ["route", "order"]
        constraints = [
            models.UniqueConstraint(fields=["route", "order"], name="unique_order_in_route"),
            models.UniqueConstraint(fields=["route", "stop"], name="unique_stop_in_route"),
        ]

    def __str__(self):
        return f"{self.order}. {self.stop}"

    def price_to(self, other):
        """Стоимость поездки от этой остановки до остановки other."""
        return other.price_from_start - self.price_from_start

    def minutes_to(self, other):
        """Время в пути (в минутах) от этой остановки до остановки other."""
        return other.minutes_from_start - self.minutes_from_start


class Vehicle(models.Model):
    """Машина автопарка (ФТ-17)."""

    brand = models.CharField("марка", max_length=100, help_text="Например: Mercedes Sprinter")
    plate_number = models.CharField("госномер", max_length=15, unique=True)
    seats = models.PositiveSmallIntegerField(
        "пассажирских мест", validators=[MinValueValidator(1)]
    )
    is_active = models.BooleanField("в работе", default=True)

    class Meta:
        verbose_name = "машина"
        verbose_name_plural = "автопарк"
        ordering = ["plate_number"]

    def __str__(self):
        return f"{self.brand} {self.plate_number} ({self.seats} мест)"


# Дни недели записываются цифрами: 1 — понедельник, ..., 7 — воскресенье.
# Например, "12345" — рабочие дни, "57" — пятница и воскресенье.
weekdays_validator = RegexValidator(
    regex=r"^[1-7]{1,7}$",
    message="Укажите дни недели цифрами от 1 (пн) до 7 (вс), например 12345.",
)


class ScheduleTemplate(models.Model):
    """
    Шаблон расписания: по нему автоматически создаются рейсы (ФТ-12).
    Например: маршрут Минск – Гомель, отправление 07:30, дни 1234567.
    """

    route = models.ForeignKey(
        Route, on_delete=models.CASCADE, related_name="templates", verbose_name="маршрут"
    )
    departure_time = models.TimeField("время отправления")
    weekdays = models.CharField(
        "дни недели", max_length=7, default="1234567", validators=[weekdays_validator],
        help_text="1 — пн, 7 — вс. Например: 12345 — по будням.",
    )
    default_vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="машина по умолчанию",
    )
    default_driver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        limit_choices_to={"role": "driver"}, verbose_name="водитель по умолчанию",
    )
    valid_from = models.DateField("действует с")
    valid_to = models.DateField("действует по", null=True, blank=True)

    class Meta:
        verbose_name = "шаблон расписания"
        verbose_name_plural = "шаблоны расписания"
        ordering = ["route", "departure_time"]

    def __str__(self):
        return f"{self.route}, {self.departure_time:%H:%M} ({self.weekdays_display()})"

    def weekdays_display(self):
        names = {"1": "пн", "2": "вт", "3": "ср", "4": "чт", "5": "пт", "6": "сб", "7": "вс"}
        return ", ".join(names[d] for d in sorted(set(self.weekdays)))

    def runs_on(self, day):
        """Ходит ли рейс по этому шаблону в дату day."""
        if day < self.valid_from or (self.valid_to and day > self.valid_to):
            return False
        # isoweekday(): понедельник = 1, воскресенье = 7, как в поле weekdays.
        return str(day.isoweekday()) in self.weekdays

    def departure_on(self, day):
        """Дата и время отправления в день day с учётом часового пояса."""
        naive = datetime.combine(day, self.departure_time)
        return timezone.make_aware(naive)


class Trip(models.Model):
    """Конкретный рейс: маршрут, дата и время отправления, машина и водитель."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "По расписанию"
        CANCELLED = "cancelled", "Отменён"
        COMPLETED = "completed", "Выполнен"

    route = models.ForeignKey(
        Route, on_delete=models.PROTECT, related_name="trips", verbose_name="маршрут"
    )
    template = models.ForeignKey(
        ScheduleTemplate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="trips", verbose_name="создан по шаблону",
    )
    departure_at = models.DateTimeField("отправление")
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.PROTECT, null=True, blank=True, verbose_name="машина"
    )
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        limit_choices_to={"role": "driver"}, related_name="driver_trips",
        verbose_name="водитель",
    )
    status = models.CharField(
        "статус", max_length=20, choices=Status.choices, default=Status.SCHEDULED
    )

    class Meta:
        verbose_name = "рейс"
        verbose_name_plural = "рейсы"
        ordering = ["departure_at"]
        constraints = [
            # Один и тот же маршрут не может дважды отправляться в одну и ту же минуту.
            models.UniqueConstraint(
                fields=["route", "departure_at"], name="unique_trip_departure"
            ),
        ]
        indexes = [models.Index(fields=["departure_at"])]

    def __str__(self):
        local = timezone.localtime(self.departure_at)
        return f"{self.route}, {local:%d.%m.%Y %H:%M}"

    def clean(self):
        if self.driver_id and self.driver.role != "driver":
            raise ValidationError(
                {"driver": "Назначить можно только пользователя с ролью «Водитель»."}
            )

    @property
    def capacity(self):
        """Вместимость рейса: число мест назначенной машины (0, если машина не назначена)."""
        return self.vehicle.seats if self.vehicle else 0

    def time_at(self, route_stop):
        """Когда рейс будет на остановке route_stop."""
        return self.departure_at + timedelta(minutes=route_stop.minutes_from_start)
