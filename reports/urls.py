from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("excel/", views.download, name="download"),
]
