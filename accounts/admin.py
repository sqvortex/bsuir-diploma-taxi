from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import UserChangeForm, UserCreationForm
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Админка пользователей, переделанная под вход по телефону."""

    form = UserChangeForm
    add_form = UserCreationForm
    ordering = ["phone"]
    list_display = ["phone", "first_name", "last_name", "role", "is_active"]
    list_filter = ["role", "is_active"]
    search_fields = ["phone", "first_name", "last_name", "email"]

    fieldsets = [
        (None, {"fields": ["phone", "password"]}),
        ("Личные данные", {"fields": ["first_name", "last_name", "email"]}),
        ("Роль и доступ", {"fields": ["role", "is_active", "is_staff", "is_superuser"]}),
        ("Даты", {"fields": ["last_login", "date_joined"]}),
    ]
    add_fieldsets = [
        (None, {
            "classes": ["wide"],
            "fields": ["phone", "role", "password1", "password2"],
        }),
    ]
