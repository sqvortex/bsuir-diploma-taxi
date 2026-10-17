from django.contrib import admin

from .models import Route, RouteStop, ScheduleTemplate, Stop, Trip, Vehicle


@admin.register(Stop)
class StopAdmin(admin.ModelAdmin):
    list_display = ["city", "name"]
    search_fields = ["city", "name"]


class RouteStopInline(admin.TabularInline):
    """Остановки маршрута редактируются прямо на странице маршрута."""

    model = RouteStop
    extra = 1
    autocomplete_fields = ["stop"]


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    inlines = [RouteStopInline]


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ["plate_number", "brand", "seats", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["plate_number", "brand"]


@admin.register(ScheduleTemplate)
class ScheduleTemplateAdmin(admin.ModelAdmin):
    list_display = ["route", "departure_time", "weekdays", "valid_from", "valid_to"]
    list_filter = ["route"]


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ["route", "departure_at", "vehicle", "driver", "status"]
    list_filter = ["status", "route"]
    date_hierarchy = "departure_at"
