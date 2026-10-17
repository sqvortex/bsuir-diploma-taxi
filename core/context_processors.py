"""Данные, которые нужны в каждом шаблоне (название сервиса)."""

from django.conf import settings


def site(request):
    return {"SITE_NAME": settings.SITE_NAME, "SITE_TAGLINE": settings.SITE_TAGLINE}
