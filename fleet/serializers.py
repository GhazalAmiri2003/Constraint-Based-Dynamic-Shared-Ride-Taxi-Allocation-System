from rest_framework import serializers

from .models import Vehicle


class VehicleSerializer(serializers.ModelSerializer):

    # فقط برای نمایش Username راننده
    driver_username = serializers.CharField(
        source="driver.user.username",
        read_only=True,
    )

    # نام Node فعلی Taxi
    current_node_name = serializers.CharField(
        source="current_node.name",
        read_only=True,
    )

    class Meta:
        model = Vehicle

        fields = [
            "id",
            "driver_username",
            "capacity",
            "is_available",
            "ride_mode",
            "current_node",
            "current_node_name",
            "created_at",
            "updated_at",
        ]

        # این فیلدها مستقیماً توسط Driver تغییر نمی‌کنند
        read_only_fields = [
            "id",
            "driver_username",
            "ride_mode",
            "current_node",
            "current_node_name",
            "created_at",
            "updated_at",
        ]