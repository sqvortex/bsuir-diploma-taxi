from django.contrib import admin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = [
        "passenger_name", "passenger_phone", "trip", "from_stop", "to_stop",
        "seats_count", "price", "status",
    ]
    list_filter = ["status", "trip__route"]
    search_fields = ["passenger_name", "passenger_phone"]
    readonly_fields = ["created_at", "cancelled_at"]
