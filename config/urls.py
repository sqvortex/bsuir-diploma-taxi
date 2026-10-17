from django.contrib import admin
from django.urls import path

admin.site.site_header = "МаршрутБай: администрирование"
admin.site.site_title = "МаршрутБай"

urlpatterns = [
    path("admin/", admin.site.urls),
]
