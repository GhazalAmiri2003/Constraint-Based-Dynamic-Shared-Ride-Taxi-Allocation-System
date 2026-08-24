from django.contrib import admin

from .models import Vehicle


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):

    # ستون‌های قابل مشاهده در Admin
    list_display = (
        "id",
        "driver",
        "capacity",
        "is_available",
        "ride_mode",
        "current_node",
    )

    # Filterهای Admin
    list_filter = (
        "is_available",
        "ride_mode",
    )