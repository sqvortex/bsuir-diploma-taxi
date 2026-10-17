"""Формы создания и изменения пользователя для админки (вход по телефону)."""

from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from django.contrib.auth.forms import UserCreationForm as BaseUserCreationForm

from core.forms import BootstrapFormMixin

from .models import User


class UserCreationForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ["phone", "role"]


class UserChangeForm(BaseUserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class RegistrationForm(BootstrapFormMixin, BaseUserCreationForm):
    """Регистрация пассажира на сайте (ФТ-1). Роль всегда «Пассажир»."""

    class Meta:
        model = User
        fields = ["phone", "first_name", "last_name", "email"]
        labels = {"first_name": "Имя", "last_name": "Фамилия", "email": "Электронная почта"}
        help_texts = {
            "phone": "В формате +375XXXXXXXXX",
            "email": "Сюда придут подтверждение брони и напоминание о поездке",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["phone"].widget.attrs.update(
            {"placeholder": "+375291234567", "autocomplete": "tel", "inputmode": "tel"}
        )

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.PASSENGER  # другие роли выдаёт только администратор
        if commit:
            user.save()
        return user


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    """Вход по телефону и паролю (ФТ-1)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Телефон"
        self.fields["username"].widget.attrs.update(
            {"placeholder": "+375291234567", "autocomplete": "tel", "inputmode": "tel"}
        )
