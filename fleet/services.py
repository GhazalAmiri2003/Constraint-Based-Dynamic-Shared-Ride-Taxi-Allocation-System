from django.db import transaction
from rides.models import Ride, RideRequest
from accounts.models import DriverProfile
from road_network.services import (
    RoadNetworkError,
    RoadNetworkService,
)

from .models import Vehicle


class VehicleMovementError(Exception):
    # خطای مربوط به حرکت Taxi
    pass


class VehicleMovementService:

    @staticmethod
    @transaction.atomic
    def move_to_adjacent_node(vehicle, next_node):
        """
        Taxi را فقط به یک Node متصل حرکت می‌دهد.
        """

        # فقط خود Vehicle را Lock می‌کنیم
        vehicle = (
            Vehicle.objects
            .select_for_update()
            .get(pk=vehicle.pk)
        )

        # Taxi باید موقعیت فعلی داشته باشد
        if vehicle.current_node is None:
            raise VehicleMovementError(
                "Vehicle has no current position."
            )

        # Driver باید Online باشد
        if (
            vehicle.driver.availability_status
            != DriverProfile.AvailabilityStatus.ONLINE
        ):
            raise VehicleMovementError(
                "Offline driver cannot move the vehicle."
            )

        # حرکت به همان Node مجاز نیست
        if vehicle.current_node_id == next_node.id:
            raise VehicleMovementError(
                "Vehicle is already at this node."
            )

        try:
            # باید Edge مستقیم معتبر وجود داشته باشد
            RoadNetworkService.get_edge(
                vehicle.current_node,
                next_node,
            )

        except RoadNetworkError as error:
            raise VehicleMovementError(
                "Vehicle can only move to an adjacent node."
            ) from error

        # حرکت فقط یک Step
        vehicle.current_node = next_node

        vehicle.save(
            update_fields=[
                "current_node",
                "updated_at",
            ]
        )

        return vehicle

    @staticmethod
    @transaction.atomic
    def move_towards_destination(
        vehicle,
        destination_node,
    ):
        """
        سریع‌ترین Route را پیدا می‌کند،
        ولی فقط یک Node حرکت می‌کند.
        """

        # فقط خود Vehicle را Lock می‌کنیم
        vehicle = (
            Vehicle.objects
            .select_for_update()
            .get(pk=vehicle.pk)
        )

        # موقعیت Taxi باید مشخص باشد
        if vehicle.current_node is None:
            raise VehicleMovementError(
                "Vehicle has no current position."
            )

        # Driver باید Online باشد
        if (
            vehicle.driver.availability_status
            != DriverProfile.AvailabilityStatus.ONLINE
        ):
            raise VehicleMovementError(
                "Offline driver cannot move the vehicle."
            )

        # Taxi از قبل در مقصد است
        if vehicle.current_node_id == destination_node.id:
            return vehicle

        try:
            # سریع‌ترین مسیر تا مقصد
            path = RoadNetworkService.shortest_path(
                vehicle.current_node,
                destination_node,
            )

        except RoadNetworkError as error:
            raise VehicleMovementError(
                "No route exists to the destination."
            ) from error

        # فقط Node بعدی Route
        next_node = path[1]

        vehicle.current_node = next_node

        vehicle.save(
            update_fields=[
                "current_node",
                "updated_at",
            ]
        )

        return vehicle

    @staticmethod
    @transaction.atomic
    def move_next_for_active_ride(vehicle):
        """
        Taxi را یک Step به سمت Target فعلی Ride حرکت می‌دهد.
        """

        # Ride فعال این Taxi
        active_rides = list(
            Ride.objects
            .select_for_update()
            .filter(
                vehicle=vehicle,
                status__in=[
                    Ride.Status.ASSIGNED,
                    Ride.Status.ACCEPTED,
                    Ride.Status.IN_PROGRESS,
                ],
            )
            .order_by("-assigned_at")[:2]
        )

        # Taxi باید Ride فعال داشته باشد
        if not active_rides:
            raise VehicleMovementError(
                "Vehicle has no active ride."
            )

        # نباید دو Ride فعال همزمان داشته باشد
        if len(active_rides) > 1:
            raise VehicleMovementError(
                "Vehicle has conflicting active rides."
            )

        ride = active_rides[0]

        # Driver باید ابتدا Ride را Accept کند
        if ride.status == Ride.Status.ASSIGNED:
            raise VehicleMovementError(
                "Driver must accept the ride before moving."
            )

        # فعلاً Movement مربوط به Private Ride
        if ride.ride_type != RideRequest.RideType.PRIVATE:
            raise VehicleMovementError(
                "Shared ride movement is not supported yet."
            )

        passenger_groups = list(
            ride.passenger_groups
            .select_related(
                "ride_request__pickup_node",
                "ride_request__destination_node",
            )
            .all()
        )

        # Private Ride باید دقیقاً یک Passenger Group داشته باشد
        if len(passenger_groups) != 1:
            raise VehicleMovementError(
                "Private ride must have one passenger group."
            )

        ride_request = passenger_groups[0].ride_request

        # قبل Pickup
        if ride.status == Ride.Status.ACCEPTED:
            target_node = ride_request.pickup_node
            target_type = "PICKUP"

        # بعد Pickup
        else:
            target_node = ride_request.destination_node
            target_type = "DROPOFF"

        previous_node = vehicle.current_node

        # فقط یک Node در Route حرکت می‌کند
        vehicle = VehicleMovementService.move_towards_destination(
            vehicle,
            target_node,
        )

        return {
            "vehicle": vehicle,
            "ride": ride,
            "previous_node": previous_node,
            "target_node": target_node,
            "target_type": target_type,
        }