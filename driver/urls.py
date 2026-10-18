from django.urls import path

from . import views

app_name = "driver"

urlpatterns = [
    path("trips/<int:pk>/", views.manifest, name="manifest"),
    path("trips/<int:pk>/complete/", views.complete, name="complete"),
    path("bookings/<int:pk>/mark/", views.mark, name="mark"),
]
