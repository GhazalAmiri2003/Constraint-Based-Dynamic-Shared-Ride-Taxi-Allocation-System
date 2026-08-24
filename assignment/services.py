from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import DriverProfile
from assignment.hold_services import (
    TaxiHoldError,
    TaxiHoldService,
)
from assignment.models import TaxiHold
from fleet.models import Vehicle
from pricing.services import PricingService
from rides.models import RideRequest
from rides.services import (
    RideLifecycleError,
    assign_private_ride,
)
from road_network.services import (
    RoadNetworkError,
    RoadNetworkService,
)


class AssignmentError(Exception):
    # خطاهای Assignment Engine
    pass


@dataclass
class TaxiOption:
    # Rank
    rank: int

    # Taxi
    vehicle_id: int
    driver_username: str
    current_node_id: int
    current_node_name: str
    capacity: int

    # Taxi → Pickup
    pickup_eta_minutes: int
    pickup_distance_km: float
    pickup_path_node_ids: list[int]

    # Pickup → Destination
    trip_eta_minutes: int
    trip_distance_km: float
    trip_path_node_ids: list[int]

    # Total
    total_eta_minutes: int
    total_distance_km: float

    # Price
    estimated_price: float


class AssignmentService:

    # =====================================================
    # Private Ranking Policy
    # =====================================================

    @staticmethod
    def _private_ranking_key(option):
        """
        Private Ride ranking:

        1. Lower pickup ETA
        2. Lower pickup distance
        3. Lower vehicle ID
        """

        return (
            option["pickup_eta_minutes"],
            option["pickup_distance_km"],
            option["vehicle"].id,
        )


    # =====================================================
    # Generate Ranked Taxi Options
    # =====================================================

    @staticmethod
    def generate_private_taxi_options(
        ride_request,
    ):
        """
        همه Taxiهای feasible را پیدا می‌کند
        و کل لیست را Rank می‌کند.
        """

        # فقط Pending
        if (
            ride_request.status
            != RideRequest.Status.PENDING
        ):
            raise AssignmentError(
                "Only pending ride requests can generate taxi options."
            )


        # فعلاً فقط Private
        if (
            ride_request.ride_type
            != RideRequest.RideType.PRIVATE
        ):
            raise AssignmentError(
                "This method only supports private rides."
            )


        # =================================================
        # 1. Passenger Trip
        # Pickup → Destination
        # =================================================

        try:
            trip_path = (
                RoadNetworkService.shortest_path(
                    ride_request.pickup_node,
                    ride_request.destination_node,
                )
            )

        except RoadNetworkError:
            # خود Ride قابل انجام نیست
            return []


        trip_eta = (
            RoadNetworkService.route_time(
                trip_path
            )
        )


        trip_distance = (
            RoadNetworkService.route_distance(
                trip_path
            )
        )


        trip_path_node_ids = [
            node.id
            for node in trip_path
        ]


        # =================================================
        # 2. Estimated Price
        # =================================================

        estimated_price = (
            PricingService
            .calculate_private_price(
                distance_km=trip_distance,
                travel_time_minutes=trip_eta,
            )
        )


        # =================================================
        # 3. Expire Old Temporary Holds
        # =================================================

        now = timezone.now()

        TaxiHold.objects.filter(
            status=TaxiHold.Status.ACTIVE,
            expires_at__lte=now,
        ).update(
            status=TaxiHold.Status.EXPIRED,
            updated_at=now,
        )


        # =================================================
        # 4. Candidate Taxiها
        # =================================================

        candidate_vehicles = (
            Vehicle.objects
            .select_related(
                "driver__user",
                "current_node",
            )
            .filter(
                # Driver Online
                driver__availability_status=(
                    DriverProfile
                    .AvailabilityStatus
                    .ONLINE
                ),

                # Vehicle available
                is_available=True,

                # Private → Taxi باید Idle باشد
                ride_mode=Vehicle.RideMode.IDLE,

                # Position مشخص
                current_node__isnull=False,

                # Capacity کافی
                capacity__gte=(
                    ride_request.passenger_count
                ),
            )

            # Taxiهایی که Hold فعال دارند
            # نباید برای Passengerهای دیگر نمایش داده شوند
            .exclude(
                taxi_holds__status=(
                    TaxiHold.Status.ACTIVE
                )
            )
        )


        feasible_options = []


        # =================================================
        # 5. Taxi Feasibility
        # =================================================

        for vehicle in candidate_vehicles:

            # ---------------------------------------------
            # Taxi → Pickup
            # ---------------------------------------------

            try:
                pickup_path = (
                    RoadNetworkService.shortest_path(
                        vehicle.current_node,
                        ride_request.pickup_node,
                    )
                )

            except RoadNetworkError:
                # Taxi به Pickup نمی‌رسد
                continue


            pickup_eta = (
                RoadNetworkService.route_time(
                    pickup_path
                )
            )


            # ---------------------------------------------
            # Maximum Pickup Wait
            # ---------------------------------------------

            max_pickup_wait = getattr(
                settings,
                "MAX_PRIVATE_PICKUP_WAIT_MINUTES",
                10,
            )


            if pickup_eta > max_pickup_wait:
                # Taxi بیش از حد دیر می‌رسد
                continue


            pickup_distance = (
                RoadNetworkService.route_distance(
                    pickup_path
                )
            )


            # ---------------------------------------------
            # Feasible Option
            # ---------------------------------------------

            feasible_options.append(
                {
                    "vehicle": vehicle,

                    # Taxi → Pickup
                    "pickup_eta_minutes":
                        pickup_eta,

                    "pickup_distance_km":
                        pickup_distance,

                    "pickup_path_node_ids": [
                        node.id
                        for node in pickup_path
                    ],

                    # Pickup → Destination
                    "trip_eta_minutes":
                        trip_eta,

                    "trip_distance_km":
                        trip_distance,

                    "trip_path_node_ids":
                        trip_path_node_ids,

                    # Total
                    "total_eta_minutes":
                        pickup_eta
                        + trip_eta,

                    "total_distance_km":
                        pickup_distance
                        + trip_distance,

                    # Price
                    "estimated_price":
                        estimated_price,
                }
            )


        # =================================================
        # 6. Ranking
        # =================================================

        feasible_options.sort(
            key=(
                AssignmentService
                ._private_ranking_key
            )
        )


        # =================================================
        # 7. Build TaxiOption List
        # =================================================

        ranked_options = []


        for index, option in enumerate(
            feasible_options,
            start=1,
        ):

            vehicle = option["vehicle"]


            ranked_options.append(
                TaxiOption(
                    # Rank
                    rank=index,

                    # Taxi
                    vehicle_id=(
                        vehicle.id
                    ),

                    driver_username=(
                        vehicle
                        .driver
                        .user
                        .username
                    ),

                    current_node_id=(
                        vehicle.current_node_id
                    ),

                    current_node_name=(
                        vehicle.current_node.name
                    ),

                    capacity=(
                        vehicle.capacity
                    ),

                    # Taxi → Pickup
                    pickup_eta_minutes=(
                        option[
                            "pickup_eta_minutes"
                        ]
                    ),

                    pickup_distance_km=(
                        option[
                            "pickup_distance_km"
                        ]
                    ),

                    pickup_path_node_ids=(
                        option[
                            "pickup_path_node_ids"
                        ]
                    ),

                    # Pickup → Destination
                    trip_eta_minutes=(
                        option[
                            "trip_eta_minutes"
                        ]
                    ),

                    trip_distance_km=(
                        option[
                            "trip_distance_km"
                        ]
                    ),

                    trip_path_node_ids=(
                        option[
                            "trip_path_node_ids"
                        ]
                    ),

                    # Total
                    total_eta_minutes=(
                        option[
                            "total_eta_minutes"
                        ]
                    ),

                    total_distance_km=(
                        option[
                            "total_distance_km"
                        ]
                    ),

                    # Price
                    estimated_price=float(
                        option[
                            "estimated_price"
                        ]
                    ),
                )
            )


        # همه گزینه‌های feasible برمی‌گردند
        return ranked_options


    # =====================================================
    # Create Temporary Taxi Hold
    # =====================================================

    @staticmethod
    @transaction.atomic
    def create_private_taxi_hold(
        ride_request,
        vehicle_id,
    ):
        """
        Taxi انتخاب‌شده را دوباره بررسی می‌کند
        و Temporary Hold می‌سازد.
        """

        # =================================================
        # 1. Lock RideRequest
        # =================================================

        locked_request = (
            RideRequest.objects
            .select_for_update()
            .select_related(
                "pickup_node",
                "destination_node",
            )
            .get(
                pk=ride_request.pk
            )
        )


        if (
            locked_request.status
            != RideRequest.Status.PENDING
        ):
            raise AssignmentError(
                "Ride request is no longer pending."
            )


        if (
            locked_request.ride_type
            != RideRequest.RideType.PRIVATE
        ):
            raise AssignmentError(
                "Only private rides are supported."
            )


        # =================================================
        # 2. Lock Vehicle
        # =================================================

        try:
            vehicle = (
                Vehicle.objects
                .select_for_update()
                .get(
                    pk=vehicle_id
                )
            )

        except Vehicle.DoesNotExist:
            raise AssignmentError(
                "Selected taxi does not exist."
            )


        # =================================================
        # 3. Re-check Taxi State
        # =================================================

        if (
            vehicle.driver.availability_status
            != DriverProfile.AvailabilityStatus.ONLINE
        ):
            raise AssignmentError(
                "Selected taxi driver is no longer online."
            )


        if not vehicle.is_available:
            raise AssignmentError(
                "Selected taxi is no longer available."
            )


        if (
            vehicle.ride_mode
            != Vehicle.RideMode.IDLE
        ):
            raise AssignmentError(
                "Selected taxi is no longer idle."
            )


        if vehicle.current_node_id is None:
            raise AssignmentError(
                "Selected taxi has no current position."
            )


        if (
            vehicle.capacity
            < locked_request.passenger_count
        ):
            raise AssignmentError(
                "Selected taxi does not have enough capacity."
            )


        # =================================================
        # 4. Re-check Taxi → Pickup
        # =================================================

        try:
            pickup_path = (
                RoadNetworkService.shortest_path(
                    vehicle.current_node,
                    locked_request.pickup_node,
                )
            )

        except RoadNetworkError:
            raise AssignmentError(
                "Selected taxi cannot reach the pickup node."
            )


        pickup_eta = (
            RoadNetworkService.route_time(
                pickup_path
            )
        )


        max_pickup_wait = getattr(
            settings,
            "MAX_PRIVATE_PICKUP_WAIT_MINUTES",
            10,
        )


        if pickup_eta > max_pickup_wait:
            raise AssignmentError(
                "Selected taxi exceeds the maximum pickup wait time."
            )


        # =================================================
        # 5. Re-check Passenger Trip
        # =================================================

        try:
            RoadNetworkService.shortest_path(
                locked_request.pickup_node,
                locked_request.destination_node,
            )

        except RoadNetworkError:
            raise AssignmentError(
                "The destination cannot be reached from the pickup node."
            )


        # =================================================
        # 6. Create Hold
        # =================================================

        try:
            hold = (
                TaxiHoldService
                .create_hold(
                    locked_request,
                    vehicle,
                )
            )

        except TaxiHoldError as error:
            raise AssignmentError(
                str(error)
            )


        return hold


    # =====================================================
    # Confirm Temporary Taxi Hold
    # =====================================================

    @staticmethod
    def confirm_private_taxi_hold(
        hold,
    ):
        """
        Hold فعال را Confirm می‌کند.

        اگر معتبر باشد:
        - Taxi دوباره بررسی می‌شود
        - Ride ساخته می‌شود
        - Hold → CONFIRMED
        """

        expired = False

        ride = None

        confirmed_hold = None


        with transaction.atomic():

            # =============================================
            # 1. Lock Hold
            # =============================================

            try:
                locked_hold = (
                    TaxiHold.objects
                    .select_for_update()
                    .select_related(
                        "ride_request",
                        "vehicle",
                    )
                    .get(
                        pk=hold.pk
                    )
                )

            except TaxiHold.DoesNotExist:
                raise AssignmentError(
                    "Taxi hold does not exist."
                )


            # =============================================
            # 2. Hold باید ACTIVE باشد
            # =============================================

            if (
                locked_hold.status
                != TaxiHold.Status.ACTIVE
            ):
                raise AssignmentError(
                    "Only active taxi holds can be confirmed."
                )


            # =============================================
            # 3. Expiration
            # =============================================

            if (
                locked_hold.expires_at
                <= timezone.now()
            ):

                locked_hold.status = (
                    TaxiHold.Status.EXPIRED
                )

                locked_hold.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

                # Exception بعد از Transaction
                # تا EXPIRED در DB باقی بماند
                expired = True


            else:

                # =========================================
                # 4. Final Revalidation + Assignment
                # =========================================

                ride = (
                    AssignmentService
                    .assign_selected_private_taxi(
                        locked_hold.ride_request,
                        locked_hold.vehicle_id,
                    )
                )


                # =========================================
                # 5. Hold → CONFIRMED
                # =========================================

                locked_hold.status = (
                    TaxiHold.Status.CONFIRMED
                )

                locked_hold.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )


                confirmed_hold = (
                    locked_hold
                )


        # Transaction اینجا Commit شده
        if expired:
            raise AssignmentError(
                "Taxi hold has expired."
            )


        return (
            ride,
            confirmed_hold,
        )


    # =====================================================
    # Select Taxi + Safe Assignment
    # =====================================================

    @staticmethod
    @transaction.atomic
    def assign_selected_private_taxi(
        ride_request,
        vehicle_id,
    ):
        """
        Final Assignment.

        RideRequest و Vehicle را Lock می‌کند،
        Feasibility را دوباره بررسی می‌کند
        و سپس Ride را می‌سازد.

        این متد مستقیماً از Web/API عمومی
        استفاده نمی‌شود و توسط Confirm Hold
        فراخوانی می‌شود.
        """

        # =================================================
        # 1. Lock RideRequest
        # =================================================

        locked_request = (
            RideRequest.objects
            .select_for_update()
            .select_related(
                "pickup_node",
                "destination_node",
            )
            .get(
                pk=ride_request.pk
            )
        )


        if (
            locked_request.status
            != RideRequest.Status.PENDING
        ):
            raise AssignmentError(
                "Ride request is no longer pending."
            )


        if (
            locked_request.ride_type
            != RideRequest.RideType.PRIVATE
        ):
            raise AssignmentError(
                "Only private rides are supported."
            )


        # =================================================
        # 2. Lock Vehicle
        # =================================================

        try:
            vehicle = (
                Vehicle.objects
                .select_for_update()
                .get(
                    pk=vehicle_id
                )
            )

        except Vehicle.DoesNotExist:
            raise AssignmentError(
                "Selected taxi does not exist."
            )


        # =================================================
        # 3. Re-check Taxi State
        # =================================================

        if (
            vehicle.driver.availability_status
            != DriverProfile.AvailabilityStatus.ONLINE
        ):
            raise AssignmentError(
                "Selected taxi driver is no longer online."
            )


        if not vehicle.is_available:
            raise AssignmentError(
                "Selected taxi is no longer available."
            )


        if (
            vehicle.ride_mode
            != Vehicle.RideMode.IDLE
        ):
            raise AssignmentError(
                "Selected taxi is no longer idle."
            )


        if vehicle.current_node_id is None:
            raise AssignmentError(
                "Selected taxi has no current position."
            )


        if (
            vehicle.capacity
            < locked_request.passenger_count
        ):
            raise AssignmentError(
                "Selected taxi does not have enough capacity."
            )


        # =================================================
        # 4. Re-check Taxi → Pickup
        # =================================================

        try:
            pickup_path = (
                RoadNetworkService.shortest_path(
                    vehicle.current_node,
                    locked_request.pickup_node,
                )
            )

        except RoadNetworkError:
            raise AssignmentError(
                "Selected taxi cannot reach the pickup node."
            )


        pickup_eta = (
            RoadNetworkService.route_time(
                pickup_path
            )
        )


        max_pickup_wait = getattr(
            settings,
            "MAX_PRIVATE_PICKUP_WAIT_MINUTES",
            10,
        )


        if pickup_eta > max_pickup_wait:
            raise AssignmentError(
                "Selected taxi exceeds the maximum pickup wait time."
            )


        # =================================================
        # 5. Re-check Pickup → Destination
        # =================================================

        try:
            RoadNetworkService.shortest_path(
                locked_request.pickup_node,
                locked_request.destination_node,
            )

        except RoadNetworkError:
            raise AssignmentError(
                "The destination cannot be reached from the pickup node."
            )


        # =================================================
        # 6. Final Assignment
        # =================================================

        try:
            ride = assign_private_ride(
                locked_request,
                vehicle,
            )

        except RideLifecycleError as error:
            raise AssignmentError(
                str(error)
            )


        return ride