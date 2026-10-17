from django.conf import settings
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = f"{settings.SITE_NAME}: администрирование"
admin.site.site_title = settings.SITE_NAME

urlpatterns = [
    path("", include("core.urls")),
    path("accounts/", include("accounts.urls")),
    path("admin/", admin.site.urls),
]
