"""Данные, которые нужны в каждом шаблоне (название сервиса и логотип)."""

from django.conf import settings


def site(request):
    name = settings.SITE_NAME
    accent = getattr(settings, "SITE_LOGO_ACCENT", "")
    if not (accent and name.endswith(accent)):
        accent = ""
    return {
        "SITE_NAME": name,
        "SITE_TAGLINE": settings.SITE_TAGLINE,
        # Логотип делится на две части: вторая часть выделяется цветом.
        "LOGO_MAIN": name[: len(name) - len(accent)],
        "LOGO_ACCENT": accent,
    }
