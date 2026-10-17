from django.urls import path

from . import views

app_name = "dispatch"

urlpatterns = [
    path("trips/", views.trip_list, name="trips"),
    path("trips/<int:pk>/", views.TripUpdate.as_view(), name="trip_edit"),
    path("trips/<int:pk>/bookings/", views.trip_bookings, name="trip_bookings"),
    path("trips/generate/", views.trips_generate, name="trips_generate"),
    path("routes/", views.RouteList.as_view(), name="routes"),
    path("routes/new/", views.route_edit, name="route_new"),
    path("routes/<int:pk>/", views.route_edit, name="route_edit"),
    path("stops/", views.StopList.as_view(), name="stops"),
    path("stops/new/", views.StopCreate.as_view(), name="stop_new"),
    path("stops/<int:pk>/", views.StopUpdate.as_view(), name="stop_edit"),
    path("vehicles/", views.VehicleList.as_view(), name="vehicles"),
    path("vehicles/new/", views.VehicleCreate.as_view(), name="vehicle_new"),
    path("vehicles/<int:pk>/", views.VehicleUpdate.as_view(), name="vehicle_edit"),
    path("schedule/", views.TemplateList.as_view(), name="templates"),
    path("schedule/new/", views.TemplateCreate.as_view(), name="template_new"),
    path("schedule/<int:pk>/", views.TemplateUpdate.as_view(), name="template_edit"),
]
