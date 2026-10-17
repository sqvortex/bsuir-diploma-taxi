"""
Бронирования мест.

Бронь занимает места не на весь рейс, а только на участке между
остановкой посадки и остановкой высадки (ФТ-4). Благодаря этому одно
и то же место можно продать дважды на непересекающиеся участки
(Минск – Бобруйск и Бобруйск – Гомель).

Создание и отмена броней вынесены в bookings/services.py: там же
защита от двойной продажи последнего места.
"""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from accounts.models import phone_validator
from transport.models import RouteStop, Trip


class Booking(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активна"
        CANCELLED = "cancelled", "Отменена"
        BOARDED = "boarded", "Пассажир сел"      # ФТ-10
        NO_SHOW = "no_show", "Не явился"         # ФТ-10

    # Статусы, при которых бронь занимает места в машине.
    OCCUPYING_STATUSES = [Status.ACTIVE, Status.BOARDED]

    trip = models.ForeignKey(
        Trip, on_delete=models.PROTECT, related_name="bookings", verbose_name="рейс"
    )
    # Аккаунт пассажира. Может быть пустым, если диспетчер бронирует
    # по телефонному звонку человеку без регистрации (ФТ-14).
    passenger = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="bookings", verbose_name="пассажир",
    )
    # Имя и телефон храним в самой брони: они нужны водителю в посадочной ведомости.
    passenger_name = models.CharField("имя пассажира", max_length=150)
    passenger_phone = models.CharField(
        "телефон пассажира", max_length=13, validators=[phone_validator]
    )
    from_stop = models.ForeignKey(
        RouteStop, on_delete=models.PROTECT, related_name="+", verbose_name="посадка"
    )
    to_stop = models.ForeignKey(
        RouteStop, on_delete=models.PROTECT, related_name="+", verbose_name="высадка"
    )
    seats_count = models.PositiveSmallIntegerField(
        "число мест", default=1, validators=[MinValueValidator(1)]
    )
    # Цена фиксируется в момент брони, чтобы смена тарифа не меняла старые брони.
    price = models.DecimalField("стоимость, BYN", max_digits=8, decimal_places=2)
    status = models.CharField(
        "статус", max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="кто оформил",
    )
    created_at = models.DateTimeField("создана", auto_now_add=True)
    cancelled_at = models.DateTimeField("отменена", null=True, blank=True)

    class Meta:
        verbose_name = "бронь"
        verbose_name_plural = "брони"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["trip", "status"])]

    def __str__(self):
        return f"{self.passenger_name}: {self.trip} ({self.seats_count} м.)"

    def clean(self):
        """Проверка, что остановки относятся к маршруту рейса и идут в правильном порядке."""
        if not (self.trip_id and self.from_stop_id and self.to_stop_id):
            return  # о пустых полях Django сообщит сам
        route_id = self.trip.route_id
        if self.from_stop.route_id != route_id or self.to_stop.route_id != route_id:
            raise ValidationError("Остановки посадки и высадки должны быть на маршруте этого рейса.")
        if self.from_stop.order >= self.to_stop.order:
            raise ValidationError("Остановка посадки должна быть раньше остановки высадки.")

    def calculate_price(self):
        """Стоимость: цена участка, умноженная на число мест."""
        return self.from_stop.price_to(self.to_stop) * self.seats_count

    @property
    def occupies_seats(self):
        return self.status in self.OCCUPYING_STATUSES

    @property
    def code(self):
        """Номер брони для пассажира и водителя, например VG-000042."""
        return f"VG-{self.pk:06d}"

    @property
    def departure(self):
        """Когда машина будет на остановке посадки."""
        return self.trip.time_at(self.from_stop)

    @property
    def arrival(self):
        return self.trip.time_at(self.to_stop)

    @property
    def cancel_deadline(self):
        """До какого момента пассажир может отменить бронь сам (ФТ-5)."""
        return self.departure - timedelta(hours=settings.BOOKING_CANCEL_HOURS)

    def can_cancel(self, user):
        """
        Может ли user отменить эту бронь.
        Пассажир: свою активную бронь не позже чем за BOOKING_CANCEL_HOURS часов до посадки.
        Диспетчер и администратор: любую активную бронь до отправления
        (например, если пассажир позвонил в последний момент).
        """
        if self.status != self.Status.ACTIVE:
            return False
        now = timezone.now()
        if user.is_dispatcher or user.is_admin_role:
            return now < self.departure
        return self.passenger_id == user.pk and now < self.cancel_deadline
