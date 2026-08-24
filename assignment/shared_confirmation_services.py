from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import (
    IntegrityError,
    transaction,
)
from django.db.models import Q
from django.utils import timezone

from accounts.models import DriverProfile
from assignment.models import TaxiHold
from assignment.shared_services import (
    SharedTaxiOptionService,
)
from fleet.models import Vehicle
from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)
from shared_ride.baseline_services import (
    SharedBaselineError,
    SharedPassengerBaselineService,
)
from shared_ride.models import (
    Route,
    RouteStop,
)


# =========================================================
# Errors
# =========================================================

class SharedConfirmationError(Exception):
    pass


class _SharedRevalidationError(Exception):
    """
    Internal error.

    یعنی Option قبلی دیگر قابل Confirm نیست
    و Hold باید آزاد شود.
    """

    pass


# =========================================================
# Confirmation Result
# =========================================================

@dataclass(frozen=True)
class SharedConfirmationResult:

    hold: TaxiHold

    ride: Ride

    ride_passenger: RidePassenger

    route: Route


# =========================================================
# Shared Hold + Confirmation Service
# =========================================================

class SharedTaxiConfirmationService:

    # =====================================================
    # Validate Request
    # =====================================================

    @staticmethod
    def _validate_request(
        ride_request,
    ):
        if (
            ride_request.status
            != RideRequest.Status.PENDING
        ):
            raise _SharedRevalidationError(
                "Ride request is no longer pending."
            )


        if (
            ride_request.ride_type
            != RideRequest.RideType.SHARED
        ):
            raise _SharedRevalidationError(
                "Only shared ride requests are supported."
            )


    # =====================================================
    # Validate Vehicle
    # =====================================================

    @staticmethod
    def _validate_vehicle(
        vehicle,
        ride_request,
    ):
        if (
            vehicle.driver.availability_status
            != DriverProfile
            .AvailabilityStatus
            .ONLINE
        ):
            raise _SharedRevalidationError(
                "Selected taxi driver is no longer online."
            )


        if not vehicle.is_available:
            raise _SharedRevalidationError(
                "Selected taxi is no longer available."
            )


        if vehicle.current_node_id is None:
            raise _SharedRevalidationError(
                "Selected taxi has no current position."
            )


        if (
            vehicle.capacity
            < ride_request.passenger_count
        ):
            raise _SharedRevalidationError(
                "Selected taxi does not have enough capacity."
            )


        if (
            vehicle.ride_mode
            not in {
                Vehicle.RideMode.IDLE,
                Vehicle.RideMode.SHARED,
            }
        ):
            raise _SharedRevalidationError(
                "Selected taxi is not available for shared rides."
            )


    # =====================================================
    # Lock Existing Ride / Route State
    # =====================================================

    @staticmethod
    def _lock_vehicle_route_state(
        vehicle,
    ):
        """
        IDLE:
            نباید Active Ride داشته باشد.

        SHARED:
            Ride + Route + RouteStops
            قبل از revalidation Lock می‌شوند.
        """

        active_statuses = [
            Ride.Status.ASSIGNED,
            Ride.Status.ACCEPTED,
            Ride.Status.IN_PROGRESS,
        ]


        # =================================================
        # IDLE Taxi
        # =================================================

        if (
            vehicle.ride_mode
            == Vehicle.RideMode.IDLE
        ):

            conflicting_rides = list(
                Ride.objects
                .select_for_update()
                .filter(
                    vehicle=vehicle,

                    status__in=(
                        active_statuses
                    ),
                )[:1]
            )


            if conflicting_rides:
                raise _SharedRevalidationError(
                    (
                        "Idle taxi has a conflicting "
                        "active ride."
                    )
                )


            return (
                None,
                None,
            )


        # =================================================
        # SHARED Taxi
        # =================================================

        shared_rides = list(
            Ride.objects
            .select_for_update()
            .filter(
                vehicle=vehicle,

                ride_type=(
                    RideRequest
                    .RideType
                    .SHARED
                ),

                status__in=(
                    active_statuses
                ),
            )
            .order_by("-id")[:2]
        )


        if len(shared_rides) != 1:
            raise _SharedRevalidationError(
                (
                    "Shared taxi must have exactly "
                    "one active shared ride."
                )
            )


        ride = shared_rides[0]


        try:
            route = (
                Route.objects
                .select_for_update()
                .get(
                    ride=ride,
                    status=Route.Status.ACTIVE,
                )
            )

        except Route.DoesNotExist:
            raise _SharedRevalidationError(
                "Active shared route was not found."
            )


        # Passenger assignments را Lock می‌کنیم.
        list(
            RidePassenger.objects
            .select_for_update()
            .filter(
                ride=ride
            )
        )


        # Route ordering را هم Lock می‌کنیم.
        list(
            RouteStop.objects
            .select_for_update()
            .filter(
                route=route
            )
        )


        return (
            ride,
            route,
        )


    # =====================================================
    # Revalidate Selected Taxi
    # =====================================================

    @staticmethod
    def _revalidate_option(
        *,
        ride_request,
        vehicle,
        reference_time,
    ):
        direct_trip = (
            SharedTaxiOptionService
            ._calculate_direct_trip(
                ride_request
            )
        )


        if direct_trip is None:
            raise _SharedRevalidationError(
                "Passenger route is no longer reachable."
            )


        option = (
            SharedTaxiOptionService
            ._evaluate_vehicle(
                vehicle=vehicle,

                ride_request=(
                    ride_request
                ),

                direct_trip=(
                    direct_trip
                ),

                reference_time=(
                    reference_time
                ),
            )
        )


        if option is None:
            raise _SharedRevalidationError(
                (
                    "Selected taxi is no longer "
                    "feasible for this shared ride."
                )
            )


        return option


    # =====================================================
    # Create Shared Temporary Hold
    # =====================================================

    @staticmethod
    @transaction.atomic
    def create_shared_taxi_hold(
        ride_request,
        vehicle_id,
    ):
        """
        Shared Taxi را temporarily hold می‌کند.

        هنوز:
        Ride ساخته نمی‌شود.
        Route تغییر نمی‌کند.
        """

        # =================================================
        # 1. Lock Request
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


        try:
            (
                SharedTaxiConfirmationService
                ._validate_request(
                    locked_request
                )
            )

        except _SharedRevalidationError as error:
            raise SharedConfirmationError(
                str(error)
            )


        # =================================================
        # 2. Lock Vehicle
        # =================================================

        try:
            vehicle = (
                Vehicle.objects
                .select_for_update()
                .select_related(
                    "driver",
                    "driver__user",
                )
                .get(
                    pk=vehicle_id
                )
            )

        except Vehicle.DoesNotExist:
            raise SharedConfirmationError(
                "Selected taxi does not exist."
            )


        try:
            (
                SharedTaxiConfirmationService
                ._validate_vehicle(
                    vehicle,
                    locked_request,
                )
            )

        except _SharedRevalidationError as error:
            raise SharedConfirmationError(
                str(error)
            )


        now = timezone.now()


        # =================================================
        # 3. Lock Conflicting Holds
        # =================================================

        conflicting_holds = list(
            TaxiHold.objects
            .select_for_update()
            .filter(
                status=TaxiHold.Status.ACTIVE
            )
            .filter(
                Q(
                    ride_request=(
                        locked_request
                    )
                )
                |
                Q(
                    vehicle=vehicle
                )
            )
        )


        active_holds = []


        for hold in conflicting_holds:

            if hold.expires_at <= now:

                hold.status = (
                    TaxiHold.Status.EXPIRED
                )

                hold.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

            else:
                active_holds.append(
                    hold
                )


        # =================================================
        # 4. Request Already Holds Taxi
        # =================================================

        request_hold = next(
            (
                hold

                for hold
                in active_holds

                if (
                    hold.ride_request_id
                    == locked_request.id
                )
            ),
            None,
        )


        if request_hold is not None:

            if (
                request_hold.vehicle_id
                == vehicle.id
            ):
                return request_hold


            raise SharedConfirmationError(
                (
                    "Ride request already has "
                    "another active taxi hold."
                )
            )


        # =================================================
        # 5. Vehicle Held By Another Request
        # =================================================

        if any(
            hold.vehicle_id
            == vehicle.id

            for hold
            in active_holds
        ):
            raise SharedConfirmationError(
                (
                    "Selected taxi is temporarily "
                    "held by another passenger."
                )
            )


        # =================================================
        # 6. Revalidate Before Holding
        # =================================================

        try:
            (
                SharedTaxiConfirmationService
                ._revalidate_option(
                    ride_request=(
                        locked_request
                    ),

                    vehicle=vehicle,

                    reference_time=now,
                )
            )

        except _SharedRevalidationError as error:
            raise SharedConfirmationError(
                str(error)
            )


        # =================================================
        # 7. Create Hold
        # =================================================

        hold_duration = int(
            getattr(
                settings,
                "TAXI_HOLD_DURATION_SECONDS",
                120,
            )
        )


        try:
            hold = TaxiHold.objects.create(
                ride_request=locked_request,

                vehicle=vehicle,

                status=TaxiHold.Status.ACTIVE,

                expires_at=(
                    now
                    + timedelta(
                        seconds=(
                            hold_duration
                        )
                    )
                ),
            )

        except IntegrityError as error:
            raise SharedConfirmationError(
                (
                    "Taxi could not be held because "
                    "its state changed concurrently."
                )
            ) from error


        return hold


    # =====================================================
    # Create New Shared Ride For IDLE Taxi
    # =====================================================

    @staticmethod
    def _create_new_shared_ride(
        *,
        ride_request,
        vehicle,
        option,
        reference_time,
    ):
        ride = Ride.objects.create(
            vehicle=vehicle,

            ride_type=(
                RideRequest
                .RideType
                .SHARED
            ),

            status=(
                Ride.Status.ASSIGNED
            ),
        )


        ride_passenger = (
            RidePassenger.objects.create(
                ride=ride,

                ride_request=(
                    ride_request
                ),
            )
        )


        route = Route.objects.create(
            ride=ride,

            status=Route.Status.ACTIVE,

            revision=1,

            total_estimated_time_minutes=(
                option
                .route_total_time_minutes
            ),

            total_estimated_distance_km=(
                option
                .route_total_distance_km
            ),
        )


        expected_group_key = (
            f"request:{ride_request.id}"
        )


        for stop in option.proposed_route:

            if (
                stop.group_key
                != expected_group_key
            ):
                raise SharedConfirmationError(
                    (
                        "Unexpected passenger group "
                        "in new shared route."
                    )
                )


            RouteStop.objects.create(
                route=route,

                ride_passenger=(
                    ride_passenger
                ),

                node_id=stop.node_id,

                stop_type=(
                    stop.stop_type
                ),

                sequence_number=(
                    stop.sequence_number
                ),

                estimated_arrival_minutes=(
                    stop
                    .estimated_arrival_minutes
                ),

                estimated_arrival_time=(
                    reference_time
                    + timedelta(
                        minutes=(
                            stop
                            .estimated_arrival_minutes
                        )
                    )
                ),

                status=(
                    RouteStop
                    .Status
                    .PENDING
                ),
            )


        ride_request.status = (
            RideRequest.Status.ASSIGNED
        )

        ride_request.save(
            update_fields=[
                "status",
            ]
        )


        vehicle.ride_mode = (
            Vehicle.RideMode.SHARED
        )

        vehicle.save(
            update_fields=[
                "ride_mode",
                "updated_at",
            ]
        )


        (
            SharedPassengerBaselineService
            .create_baseline(
                ride_passenger=(
                    ride_passenger
                ),

                expected_dropoff_minutes=(
                    option
                    .estimated_destination_arrival_minutes
                ),

                route_revision=1,

                reference_time=(
                    reference_time
                ),
            )
        )


        return (
            ride,
            ride_passenger,
            route,
        )


    # =====================================================
    # Insert Into Existing Shared Ride
    # =====================================================

    @staticmethod
    def _insert_into_existing_shared_ride(
        *,
        ride_request,
        vehicle,
        ride,
        route,
        option,
        reference_time,
    ):
        # =================================================
        # 1. New RidePassenger
        # =================================================

        ride_passenger = (
            RidePassenger.objects.create(
                ride=ride,

                ride_request=(
                    ride_request
                ),
            )
        )


        # =================================================
        # 2. Existing Pending Stops
        # =================================================

        pending_stops = list(
            RouteStop.objects
            .select_for_update()
            .filter(
                route=route,

                status=(
                    RouteStop
                    .Status
                    .PENDING
                ),
            )
            .select_related(
                "ride_passenger"
            )
        )


        existing_stop_map = {
            (
                f"rp:{stop.ride_passenger_id}",
                stop.stop_type,
            ):
                stop

            for stop
            in pending_stops
        }


        # =================================================
        # 3. Preserve Completed/Cancelled Sequence Area
        # =================================================

        fixed_sequence_numbers = list(
            RouteStop.objects
            .filter(
                route=route
            )
            .exclude(
                status=(
                    RouteStop
                    .Status
                    .PENDING
                )
            )
            .values_list(
                "sequence_number",
                flat=True,
            )
        )


        sequence_offset = max(
            fixed_sequence_numbers,
            default=0,
        )


        # =================================================
        # 4. Temporarily Move Existing Pending Sequences
        # =================================================
        #
        # برای جلوگیری از UniqueConstraint conflict
        # هنگام swap شدن sequenceها.

        for stop in pending_stops:

            stop.sequence_number = (
                1_000_000
                + stop.id
            )

            stop.save(
                update_fields=[
                    "sequence_number",
                    "updated_at",
                ]
            )


        # =================================================
        # 5. Apply Proposed Route
        # =================================================

        new_group_key = (
            f"request:{ride_request.id}"
        )


        consumed_existing_stop_ids = set()


        new_stop_count = 0


        for proposed in (
            option.proposed_route
        ):

            final_sequence = (
                sequence_offset
                + proposed.sequence_number
            )


            estimated_arrival_time = (
                reference_time
                + timedelta(
                    minutes=(
                        proposed
                        .estimated_arrival_minutes
                    )
                )
            )


            # =============================================
            # Existing Passenger Stop
            # =============================================

            if proposed.group_key.startswith(
                "rp:"
            ):

                key = (
                    proposed.group_key,
                    proposed.stop_type,
                )


                existing_stop = (
                    existing_stop_map
                    .get(key)
                )


                if existing_stop is None:
                    raise SharedConfirmationError(
                        (
                            "Proposed route contains "
                            "an unknown existing stop."
                        )
                    )


                existing_stop.node_id = (
                    proposed.node_id
                )

                existing_stop.sequence_number = (
                    final_sequence
                )

                existing_stop.estimated_arrival_minutes = (
                    proposed
                    .estimated_arrival_minutes
                )

                existing_stop.estimated_arrival_time = (
                    estimated_arrival_time
                )


                existing_stop.save(
                    update_fields=[
                        "node",
                        "sequence_number",
                        "estimated_arrival_minutes",
                        "estimated_arrival_time",
                        "updated_at",
                    ]
                )


                consumed_existing_stop_ids.add(
                    existing_stop.id
                )


            # =============================================
            # New Passenger Stop
            # =============================================

            elif (
                proposed.group_key
                == new_group_key
            ):

                RouteStop.objects.create(
                    route=route,

                    ride_passenger=(
                        ride_passenger
                    ),

                    node_id=(
                        proposed.node_id
                    ),

                    stop_type=(
                        proposed.stop_type
                    ),

                    sequence_number=(
                        final_sequence
                    ),

                    estimated_arrival_minutes=(
                        proposed
                        .estimated_arrival_minutes
                    ),

                    estimated_arrival_time=(
                        estimated_arrival_time
                    ),

                    status=(
                        RouteStop
                        .Status
                        .PENDING
                    ),
                )


                new_stop_count += 1


            else:
                raise SharedConfirmationError(
                    (
                        "Proposed route contains "
                        "an unknown passenger group."
                    )
                )


        # =================================================
        # 6. Defensive Route Checks
        # =================================================

        if (
            len(consumed_existing_stop_ids)
            != len(pending_stops)
        ):
            raise SharedConfirmationError(
                (
                    "Not all existing route stops "
                    "were preserved."
                )
            )


        if new_stop_count != 2:
            raise SharedConfirmationError(
                (
                    "New shared passenger must have "
                    "exactly one pickup and one drop-off."
                )
            )


        # =================================================
        # 7. Route Revision + Metrics
        # =================================================

        route.revision += 1

        route.total_estimated_time_minutes = (
            option
            .route_total_time_minutes
        )

        route.total_estimated_distance_km = (
            option
            .route_total_distance_km
        )


        route.save(
            update_fields=[
                "revision",
                "total_estimated_time_minutes",
                "total_estimated_distance_km",
                "updated_at",
            ]
        )


        # =================================================
        # 8. Request → ASSIGNED
        # =================================================

        ride_request.status = (
            RideRequest.Status.ASSIGNED
        )

        ride_request.save(
            update_fields=[
                "status",
            ]
        )


        # =================================================
        # 9. New Passenger Immutable Baseline
        # =================================================

        (
            SharedPassengerBaselineService
            .create_baseline(
                ride_passenger=(
                    ride_passenger
                ),

                expected_dropoff_minutes=(
                    option
                    .estimated_destination_arrival_minutes
                ),

                route_revision=(
                    route.revision
                ),

                reference_time=(
                    reference_time
                ),
            )
        )


        return (
            ride,
            ride_passenger,
            route,
        )


    # =====================================================
    # Confirm Shared Hold
    # =====================================================

    @staticmethod
    def confirm_shared_taxi_hold(
        hold,
    ):
        """
        FINAL Shared Assignment.

        مهم:
        Option قبلی Trust نمی‌شود.
        Algorithm داخل Transaction دوباره اجرا می‌شود.
        """

        try:
            hold_reference = (
                TaxiHold.objects
                .only(
                    "id",
                    "ride_request_id",
                    "vehicle_id",
                )
                .get(
                    pk=hold.pk
                )
            )

        except TaxiHold.DoesNotExist:
            raise SharedConfirmationError(
                "Taxi hold does not exist."
            )


        terminal_error = None

        result = None


        with transaction.atomic():

            # =============================================
            # 1. Lock Request
            # =============================================

            locked_request = (
                RideRequest.objects
                .select_for_update()
                .select_related(
                    "pickup_node",
                    "destination_node",
                )
                .get(
                    pk=(
                        hold_reference
                        .ride_request_id
                    )
                )
            )


            # =============================================
            # 2. Lock Vehicle
            # =============================================

            locked_vehicle = (
                Vehicle.objects
                .select_for_update()
                .select_related(
                    "driver",
                    "driver__user",
                )
                .get(
                    pk=(
                        hold_reference
                        .vehicle_id
                    )
                )
            )


            # =============================================
            # 3. Lock Hold
            # =============================================

            locked_hold = (
                TaxiHold.objects
                .select_for_update()
                .get(
                    pk=hold_reference.id
                )
            )


            if (
                locked_hold.ride_request_id
                != locked_request.id

                or locked_hold.vehicle_id
                != locked_vehicle.id
            ):
                raise SharedConfirmationError(
                    "Taxi hold references changed unexpectedly."
                )


            # =============================================
            # 4. Hold State
            # =============================================

            if (
                locked_hold.status
                != TaxiHold.Status.ACTIVE
            ):
                raise SharedConfirmationError(
                    (
                        "Only active taxi holds "
                        "can be confirmed."
                    )
                )


            reference_time = (
                timezone.now()
            )


            # =============================================
            # 5. Expiration
            # =============================================

            if (
                locked_hold.expires_at
                <= reference_time
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


                terminal_error = (
                    "Taxi hold has expired."
                )


            else:

                # =========================================
                # 6. Full Revalidation
                # =========================================

                try:

                    (
                        SharedTaxiConfirmationService
                        ._validate_request(
                            locked_request
                        )
                    )


                    (
                        SharedTaxiConfirmationService
                        ._validate_vehicle(
                            locked_vehicle,
                            locked_request,
                        )
                    )


                    (
                        existing_ride,
                        existing_route,
                    ) = (
                        SharedTaxiConfirmationService
                        ._lock_vehicle_route_state(
                            locked_vehicle
                        )
                    )


                    option = (
                        SharedTaxiConfirmationService
                        ._revalidate_option(
                            ride_request=(
                                locked_request
                            ),

                            vehicle=(
                                locked_vehicle
                            ),

                            reference_time=(
                                reference_time
                            ),
                        )
                    )


                except _SharedRevalidationError as error:

                    # Option دیگر معتبر نیست.
                    # Taxi را آزاد می‌کنیم.

                    locked_hold.status = (
                        TaxiHold.Status.RELEASED
                    )

                    locked_hold.save(
                        update_fields=[
                            "status",
                            "updated_at",
                        ]
                    )


                    terminal_error = str(
                        error
                    )


                else:

                    # =====================================
                    # 7. Apply Assignment Atomically
                    # =====================================

                    try:

                        if (
                            locked_vehicle.ride_mode
                            == Vehicle.RideMode.IDLE
                        ):

                            (
                                ride,
                                ride_passenger,
                                route,
                            ) = (
                                SharedTaxiConfirmationService
                                ._create_new_shared_ride(
                                    ride_request=(
                                        locked_request
                                    ),

                                    vehicle=(
                                        locked_vehicle
                                    ),

                                    option=option,

                                    reference_time=(
                                        reference_time
                                    ),
                                )
                            )


                        else:

                            (
                                ride,
                                ride_passenger,
                                route,
                            ) = (
                                SharedTaxiConfirmationService
                                ._insert_into_existing_shared_ride(
                                    ride_request=(
                                        locked_request
                                    ),

                                    vehicle=(
                                        locked_vehicle
                                    ),

                                    ride=(
                                        existing_ride
                                    ),

                                    route=(
                                        existing_route
                                    ),

                                    option=option,

                                    reference_time=(
                                        reference_time
                                    ),
                                )
                            )


                    except (
                        SharedBaselineError,
                        IntegrityError,
                        SharedConfirmationError,
                    ) as error:

                        # Raise INSIDE transaction
                        # تا تمام DB changes rollback شوند.
                        raise SharedConfirmationError(
                            (
                                "Shared assignment failed "
                                "and was rolled back: "
                                f"{error}"
                            )
                        ) from error


                    # =====================================
                    # 8. Hold → CONFIRMED
                    # =====================================

                    locked_hold.status = (
                        TaxiHold.Status.CONFIRMED
                    )

                    locked_hold.save(
                        update_fields=[
                            "status",
                            "updated_at",
                        ]
                    )


                    result = (
                        SharedConfirmationResult(
                            hold=locked_hold,

                            ride=ride,

                            ride_passenger=(
                                ride_passenger
                            ),

                            route=route,
                        )
                    )


        # =================================================
        # Raise AFTER Commit
        # =================================================
        #
        # برای EXPIRED / RELEASED مهم است.
        # اگر داخل transaction raise کنیم،
        # status rollback می‌شد.

        if terminal_error is not None:
            raise SharedConfirmationError(
                terminal_error
            )


        return result



    # =====================================================
    # Release Shared Hold
    # =====================================================

    @staticmethod
    @transaction.atomic
    def release_shared_taxi_hold(
        hold,
    ):
        """
        Passenger voluntarily releases
        an ACTIVE shared taxi hold.

        ACTIVE:
            → RELEASED

        Expired:
            → EXPIRED

        CONFIRMED / RELEASED / EXPIRED:
            cannot be released again.
        """

        try:
            locked_hold = (
                TaxiHold.objects
                .select_for_update()
                .get(
                    pk=hold.pk
                )
            )

        except TaxiHold.DoesNotExist:
            raise SharedConfirmationError(
                "Taxi hold does not exist."
            )


        if (
            locked_hold.status
            != TaxiHold.Status.ACTIVE
        ):
            raise SharedConfirmationError(
                (
                    "Only active taxi holds "
                    "can be released."
                )
            )


        now = timezone.now()


        # Hold already expired.
        if (
            locked_hold.expires_at
            <= now
        ):

            locked_hold.status = (
                TaxiHold.Status.EXPIRED
            )

        else:

            locked_hold.status = (
                TaxiHold.Status.RELEASED
            )


        locked_hold.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )


        return locked_hold