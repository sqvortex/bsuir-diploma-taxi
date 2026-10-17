from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render

from .forms import RegistrationForm


def register(request):
    """Регистрация пассажира. После успешной регистрации сразу входим в систему."""
    if request.user.is_authenticated:
        return redirect("core:cabinet")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Добро пожаловать, {user.first_name}! Аккаунт создан.")
        return redirect("core:cabinet")
    return render(request, "accounts/register.html", {"form": form})
