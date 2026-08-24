from django.contrib import admin

from .models import Ride, RidePassenger, RideRequest


@admin.register(RideRequest)
class RideRequestAdmin(admin.ModelAdmin):
    # اطلاعات اصلی Request
    list_display = (
        "id",
        "passenger",
        "ride_type",
        "passenger_count",
        "pickup_node",
        "destination_node",
        "status",
        "created_at",
    )

    list_filter = (
        "ride_type",
        "status",
    )

    search_fields = (
        "passenger__user__username",
    )


class RidePassengerInline(admin.TabularInline):
    # Passenger Groupهای داخل Ride
    model = RidePassenger
    extra = 0


@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    # اطلاعات اصلی Ride
    list_display = (
        "id",
        "vehicle",
        "ride_type",
        "status",
        "assigned_at",
    )

    list_filter = (
        "ride_type",
        "status",
    )

    # نمایش Passenger Groupها داخل Ride
    inlines = [
        RidePassengerInline,
    ]


@admin.register(RidePassenger)
class RidePassengerAdmin(admin.ModelAdmin):
    # ارتباط Ride و Request
    list_display = (
        "id",
        "ride",
        "ride_request",
        "joined_at",
    )