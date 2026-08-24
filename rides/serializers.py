from rest_framework import serializers

from .models import RideRequest
from .models import Ride, RidePassenger

class RideRequestSerializer(serializers.ModelSerializer):
    # Username فقط برای نمایش در Response
    passenger_username = serializers.CharField(
        source="passenger.user.username",
        read_only=True,
    )

    # نام Node مبدا برای نمایش خواناتر
    pickup_node_name = serializers.CharField(
        source="pickup_node.name",
        read_only=True,
    )

    # نام Node مقصد برای نمایش خواناتر
    destination_node_name = serializers.CharField(
        source="destination_node.name",
        read_only=True,
    )

    class Meta:
        model = RideRequest

        fields = [
            "id",
            "passenger_username",
            "ride_type",
            "passenger_count",
            "pickup_node",
            "pickup_node_name",
            "destination_node",
            "destination_node_name",
            "notes",
            "status",
            "created_at",
            "updated_at",
        ]

        # این فیلدها توسط Passenger مستقیم تغییر نمی‌کنند
        read_only_fields = [
            "id",
            "passenger_username",
            "pickup_node_name",
            "destination_node_name",
            "status",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        # مبدا و مقصد نباید یکی باشند
        if attrs["pickup_node"] == attrs["destination_node"]:
            raise serializers.ValidationError(
                "Pickup and destination nodes must be different."
            )

        return attrs




class RidePassengerSerializer(serializers.ModelSerializer):
    # اطلاعات Passenger Group برای Driver
    passenger_username = serializers.CharField(
        source="ride_request.passenger.user.username",
        read_only=True,
    )

    passenger_count = serializers.IntegerField(
        source="ride_request.passenger_count",
        read_only=True,
    )

    pickup_node = serializers.IntegerField(
        source="ride_request.pickup_node.id",
        read_only=True,
    )

    pickup_node_name = serializers.CharField(
        source="ride_request.pickup_node.name",
        read_only=True,
    )

    destination_node = serializers.IntegerField(
        source="ride_request.destination_node.id",
        read_only=True,
    )

    destination_node_name = serializers.CharField(
        source="ride_request.destination_node.name",
        read_only=True,
    )

    class Meta:
        model = RidePassenger

        fields = [
            "id",
            "ride_request",
            "passenger_username",
            "passenger_count",
            "pickup_node",
            "pickup_node_name",
            "destination_node",
            "destination_node_name",
            "joined_at",
        ]

        # Driver فقط اطلاعات را می‌بیند
        read_only_fields = fields


class RideSerializer(serializers.ModelSerializer):
    # Passenger Groupهای Ride
    passenger_groups = RidePassengerSerializer(
        many=True,
        read_only=True,
    )

    # Driver مربوط به Taxi
    driver_username = serializers.CharField(
        source="vehicle.driver.user.username",
        read_only=True,
    )

    class Meta:
        model = Ride

        fields = [
            "id",
            "vehicle",
            "driver_username",
            "ride_type",
            "status",
            "passenger_groups",
            "assigned_at",
            "accepted_at",
            "started_at",
            "completed_at",
            "updated_at",
        ]

        # وضعیت Ride فقط از Service تغییر می‌کند
        read_only_fields = fields