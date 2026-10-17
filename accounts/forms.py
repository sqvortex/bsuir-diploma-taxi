"""Формы создания и изменения пользователя для админки (вход по телефону)."""

from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from django.contrib.auth.forms import UserCreationForm as BaseUserCreationForm

from .models import User


class UserCreationForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ["phone", "role"]


class UserChangeForm(BaseUserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
