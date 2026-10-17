from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("trip/<int:trip_pk>/", views.book, name="book"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/cancel/", views.cancel, name="cancel"),
]
