"""
Пользователи системы.

Вместо стандартного логина Django используется номер телефона (ФТ-1),
а у каждого пользователя есть одна роль: пассажир, водитель,
диспетчер или администратор (раздел 3 ТЗ).
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models

# Белорусский номер в международном формате: +375 и 9 цифр.
phone_validator = RegexValidator(
    regex=r"^\+375\d{9}$",
    message="Введите номер в формате +375XXXXXXXXX.",
)


class UserManager(BaseUserManager):
    """Создаёт пользователей по номеру телефона вместо имени пользователя."""

    use_in_migrations = True

    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError("Нужно указать номер телефона")
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)  # пароль сохраняется только в виде хеша
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        return self.create_user(phone, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        PASSENGER = "passenger", "Пассажир"
        DRIVER = "driver", "Водитель"
        DISPATCHER = "dispatcher", "Диспетчер"
        ADMIN = "admin", "Администратор"

    # Стандартное поле username не нужно: входим по телефону.
    username = None
    phone = models.CharField(
        "телефон", max_length=13, unique=True, validators=[phone_validator]
    )
    role = models.CharField(
        "роль", max_length=20, choices=Role.choices, default=Role.PASSENGER
    )

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"

    def __str__(self):
        name = self.get_full_name()
        return f"{name} ({self.phone})" if name else self.phone

    # Короткие проверки роли, чтобы в коде писать user.is_driver вместо сравнения строк.
    @property
    def is_passenger(self):
        return self.role == self.Role.PASSENGER

    @property
    def is_driver(self):
        return self.role == self.Role.DRIVER

    @property
    def is_dispatcher(self):
        return self.role == self.Role.DISPATCHER

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN
