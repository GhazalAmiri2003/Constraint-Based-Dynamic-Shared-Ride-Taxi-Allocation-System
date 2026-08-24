from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from rides.models import RideRequest
from road_network.services import (
    RoadNetworkError,
    RoadNetworkService,
)
from shared_ride.models import (
    SharedPassengerBaseline,
)


class SharedBaselineError(Exception):
    pass


class SharedPassengerBaselineService:

    # =====================================================
    # Direct Trip Time
    # =====================================================

    @staticmethod
    def calculate_direct_trip_time(
        ride_passenger,
    ):
        """
        Direct travel time:

        Pickup → Destination

        هیچ Shared detour داخل این مقدار نیست.
        """

        ride_request = (
            ride_passenger.ride_request
        )


        if (
            ride_request.ride_type
            != RideRequest.RideType.SHARED
        ):
            raise SharedBaselineError(
                "Baseline is only supported for shared rides."
            )


        try:
            direct_path = (
                RoadNetworkService.shortest_path(
                    ride_request.pickup_node,
                    ride_request.destination_node,
                )
            )

        except RoadNetworkError:
            raise SharedBaselineError(
                "Passenger direct route is unreachable."
            )


        direct_trip_time = (
            RoadNetworkService.route_time(
                direct_path
            )
        )


        # از division by zero در Relative Delay
        # جلوگیری می‌کنیم.
        if direct_trip_time <= 0:
            raise SharedBaselineError(
                "Direct trip time must be greater than zero."
            )


        return direct_trip_time


    # =====================================================
    # Create Immutable Baseline
    # =====================================================

    @staticmethod
    @transaction.atomic
    def create_baseline(
        ride_passenger,
        expected_dropoff_minutes,
        route_revision,
        reference_time=None,
    ):
        """
        Baseline اولیه Passenger را می‌سازد.

        نکته:
        Baseline موجود overwrite نمی‌شود.
        """

        if expected_dropoff_minutes <= 0:
            raise SharedBaselineError(
                "Expected drop-off time must be greater than zero."
            )


        if route_revision < 1:
            raise SharedBaselineError(
                "Route revision must be at least 1."
            )


        direct_trip_time = (
            SharedPassengerBaselineService
            .calculate_direct_trip_time(
                ride_passenger
            )
        )


        if reference_time is None:
            reference_time = timezone.now()


        baseline_dropoff_at = (
            reference_time
            + timedelta(
                minutes=expected_dropoff_minutes
            )
        )


        # مهم:
        # get_or_create باعث می‌شود Baseline
        # در insertionهای بعدی overwrite نشود.
        baseline, created = (
            SharedPassengerBaseline.objects
            .get_or_create(
                ride_passenger=ride_passenger,

                defaults={
                    "direct_trip_time_minutes":
                        direct_trip_time,

                    "baseline_expected_dropoff_at":
                        baseline_dropoff_at,

                    "baseline_route_revision":
                        route_revision,
                },
            )
        )


        return baseline