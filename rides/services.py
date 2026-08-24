from django.db import transaction
from django.utils import timezone

from accounts.models import DriverProfile
from fleet.models import Vehicle

from .models import Ride, RidePassenger, RideRequest


class RideLifecycleError(Exception):
    # خطای Business Logic مربوط به Ride
    pass


@transaction.atomic
def assign_private_ride(ride_request, vehicle):
    """
    یک Private RideRequest را به Taxi اختصاص می‌دهد.
    """

    # Lock Request برای جلوگیری از Assignment همزمان
    ride_request = (
        RideRequest.objects
        .select_for_update()
        .get(pk=ride_request.pk)
    )

    # Lock Vehicle برای جلوگیری از Double Assignment
    vehicle = (
        Vehicle.objects
        .select_for_update()
        .select_related("driver")
        .get(pk=vehicle.pk)
    )

    # فقط Request منتظر Assignment
    if ride_request.status != RideRequest.Status.PENDING:
        raise RideLifecycleError(
            "Ride request is not pending."
        )

    # این Service فعلاً فقط Private Ride
    if ride_request.ride_type != RideRequest.RideType.PRIVATE:
        raise RideLifecycleError(
            "This service only supports private rides."
        )

    # Driver باید Online باشد
    if (
        vehicle.driver.availability_status
        != DriverProfile.AvailabilityStatus.ONLINE
    ):
        raise RideLifecycleError(
            "Driver is offline."
        )

    # Vehicle باید قابل استفاده باشد
    if not vehicle.is_available:
        raise RideLifecycleError(
            "Vehicle is unavailable."
        )

    # Taxi نباید Ride فعال داشته باشد
    if vehicle.ride_mode != Vehicle.RideMode.IDLE:
        raise RideLifecycleError(
            "Vehicle is not idle."
        )

    # ظرفیت Taxi باید کافی باشد
    if vehicle.capacity < ride_request.passenger_count:
        raise RideLifecycleError(
            "Vehicle capacity is insufficient."
        )

    # Ride عملیاتی ساخته می‌شود
    ride = Ride.objects.create(
        vehicle=vehicle,
        ride_type=RideRequest.RideType.PRIVATE,
        status=Ride.Status.ASSIGNED,
    )

    # Request به Ride وصل می‌شود
    RidePassenger.objects.create(
        ride=ride,
        ride_request=ride_request,
    )

    # Request دیگر Pending نیست
    ride_request.status = RideRequest.Status.ASSIGNED
    ride_request.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    # Taxi برای Private Ride رزرو شد
    vehicle.ride_mode = Vehicle.RideMode.PRIVATE
    vehicle.save(
        update_fields=[
            "ride_mode",
            "updated_at",
        ]
    )

    return ride


@transaction.atomic
def accept_ride(ride, driver_profile):
    """
    Driver یک Ride اختصاص‌داده‌شده را قبول می‌کند.
    """

    # Lock Ride
    ride = (
        Ride.objects
        .select_for_update()
        .select_related("vehicle__driver")
        .get(pk=ride.pk)
    )

    # فقط Driver صاحب Taxi
    if ride.vehicle.driver_id != driver_profile.id:
        raise RideLifecycleError(
            "This ride is not assigned to this driver."
        )

    # فقط ASSIGNED قابل Accept است
    if ride.status != Ride.Status.ASSIGNED:
        raise RideLifecycleError(
            "Ride cannot be accepted in its current state."
        )

    ride.status = Ride.Status.ACCEPTED
    ride.accepted_at = timezone.now()

    ride.save(
        update_fields=[
            "status",
            "accepted_at",
            "updated_at",
        ]
    )

    return ride


@transaction.atomic
def reject_ride(ride, driver_profile):
    """
    Driver قبل از Pickup، Assignment را رد می‌کند.
    """

    # Lock Ride و Vehicle
    ride = (
        Ride.objects
        .select_for_update()
        .select_related("vehicle__driver")
        .get(pk=ride.pk)
    )

    vehicle = (
        Vehicle.objects
        .select_for_update()
        .get(pk=ride.vehicle_id)
    )

    # فقط Driver صاحب Taxi
    if vehicle.driver_id != driver_profile.id:
        raise RideLifecycleError(
            "This ride is not assigned to this driver."
        )

    # فقط ASSIGNED قابل Reject است
    if ride.status != Ride.Status.ASSIGNED:
        raise RideLifecycleError(
            "Ride cannot be rejected in its current state."
        )

    # Ride رد می‌شود
    ride.status = Ride.Status.REJECTED
    ride.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    # Taxi دوباره آزاد می‌شود
    vehicle.ride_mode = Vehicle.RideMode.IDLE
    vehicle.save(
        update_fields=[
            "ride_mode",
            "updated_at",
        ]
    )

    # Request دوباره منتظر Taxi می‌شود
    RideRequest.objects.filter(
        ride_links__ride=ride
    ).update(
        status=RideRequest.Status.PENDING,
        updated_at=timezone.now(),
    )

    return ride


@transaction.atomic
def start_ride(ride, driver_profile):
    # Ride را Lock می‌کنیم
    ride = (
        Ride.objects
        .select_for_update()
        .select_related("vehicle")
        .get(pk=ride.pk)
    )

    # Vehicle را جداگانه Lock می‌کنیم
    vehicle = (
        Vehicle.objects
        .select_for_update()
        .get(pk=ride.vehicle_id)
    )

    # فقط Driver همین Taxi
    if vehicle.driver_id != driver_profile.id:
        raise RideLifecycleError(
            "This ride does not belong to this driver."
        )

    # فقط Ride قبول‌شده قابل Start است
    if ride.status != Ride.Status.ACCEPTED:
        raise RideLifecycleError(
            "Only accepted rides can be started."
        )

    # فعلاً Private Ride
    if ride.ride_type == RideRequest.RideType.PRIVATE:

        passenger_group = (
            ride.passenger_groups
            .select_related(
                "ride_request__pickup_node"
            )
            .first()
        )

        if not passenger_group:
            raise RideLifecycleError(
                "Ride has no passenger group."
            )

        pickup_node = (
            passenger_group
            .ride_request
            .pickup_node
        )

        # Taxi باید واقعاً روی Pickup باشد
        if vehicle.current_node_id != pickup_node.id:
            raise RideLifecycleError(
                "Vehicle must reach the pickup node before starting the ride."
            )

    # شروع Ride
    ride.status = Ride.Status.IN_PROGRESS
    ride.started_at = timezone.now()

    ride.save(
        update_fields=[
            "status",
            "started_at",
            "updated_at",
        ]
    )

    return ride

@transaction.atomic
def complete_ride(ride, driver_profile):
    # Ride را Lock می‌کنیم
    ride = (
        Ride.objects
        .select_for_update()
        .get(pk=ride.pk)
    )

    # Vehicle را جداگانه Lock می‌کنیم
    vehicle = (
        Vehicle.objects
        .select_for_update()
        .get(pk=ride.vehicle_id)
    )

    # فقط Driver همین Taxi
    if vehicle.driver_id != driver_profile.id:
        raise RideLifecycleError(
            "This ride does not belong to this driver."
        )

    # فقط Ride شروع‌شده قابل Complete است
    if ride.status != Ride.Status.IN_PROGRESS:
        raise RideLifecycleError(
            "Only in-progress rides can be completed."
        )

    # فعلاً برای Private Ride
    if ride.ride_type == RideRequest.RideType.PRIVATE:
        passenger_group = (
            ride.passenger_groups
            .select_related(
                "ride_request__destination_node"
            )
            .first()
        )

        if not passenger_group:
            raise RideLifecycleError(
                "Ride has no passenger group."
            )

        destination_node = (
            passenger_group
            .ride_request
            .destination_node
        )

        # Taxi باید واقعاً به مقصد رسیده باشد
        if (
            vehicle.current_node_id
            != destination_node.id
        ):
            raise RideLifecycleError(
                "Vehicle must reach the destination before completing the ride."
            )

    # Ride تمام می‌شود
    ride.status = Ride.Status.COMPLETED
    ride.completed_at = timezone.now()

    ride.save(
        update_fields=[
            "status",
            "completed_at",
            "updated_at",
        ]
    )

    # Taxi دوباره آزاد می‌شود
    vehicle.ride_mode = Vehicle.RideMode.IDLE

    vehicle.save(
        update_fields=[
            "ride_mode",
            "updated_at",
        ]
    )

    # Requestهای مرتبط هم Complete می‌شوند
    ride_requests = RideRequest.objects.filter(
        ride_links__ride=ride
    )

    ride_requests.update(
        status=RideRequest.Status.COMPLETED
    )

    return ride


def _release_active_holds_for_request(
    ride_request,
    now,
):
    """
    اگر Passenger هنوز Request را Confirm نکرده باشد،
    ممکن است یک TaxiHold فعال داشته باشد.

    Cancel کردن Request باید Hold را هم آزاد کند تا Taxi
    بی‌دلیل تا پایان timeout قفل نماند.
    """

    # Local import برای جلوگیری از dependency cycle بی‌مورد.
    from assignment.models import TaxiHold

    holds = list(
        TaxiHold.objects
        .select_for_update()
        .filter(
            ride_request=ride_request,
            status=TaxiHold.Status.ACTIVE,
        )
    )

    for hold in holds:

        if hold.expires_at <= now:
            hold.status = TaxiHold.Status.EXPIRED

        else:
            hold.status = TaxiHold.Status.RELEASED

        hold.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )


def _cancel_private_active_ride(
    *,
    active_ride,
):
    """
    Private Ride فقط تا قبل از pickup قابل Cancel است.

    در Private Ride، IN_PROGRESS یعنی Passenger pickup شده است.
    """

    if (
        active_ride.status
        == Ride.Status.IN_PROGRESS
    ):
        raise RideLifecycleError(
            "Ride cannot be cancelled after pickup."
        )

    vehicle = (
        Vehicle.objects
        .select_for_update()
        .get(
            pk=active_ride.vehicle_id
        )
    )

    active_ride.status = (
        Ride.Status.CANCELLED
    )

    active_ride.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    vehicle.ride_mode = (
        Vehicle.RideMode.IDLE
    )

    vehicle.save(
        update_fields=[
            "ride_mode",
            "updated_at",
        ]
    )


def _build_remaining_shared_simulation_state(
    *,
    route,
):
    """
    Route فعلی را بعد از Cancellation به input Simulation تبدیل می‌کند.

    Passengerهای already picked-up داخل initial_onboard قرار می‌گیرند.
    فقط PENDING stopها وارد remaining route می‌شوند.
    """

    from shared_ride.models import RouteStop
    from shared_ride.simulation import SimulatedStop

    all_stops = list(
        RouteStop.objects
        .select_for_update()
        .filter(
            route=route
        )
        .exclude(
            status=RouteStop.Status.CANCELLED
        )
        .select_related(
            "node",
            "ride_passenger",
            "ride_passenger__ride_request",
        )
        .order_by(
            "sequence_number",
            "id",
        )
    )

    pending_stops = [
        stop
        for stop in all_stops
        if (
            stop.status
            == RouteStop.Status.PENDING
        )
    ]

    pending_dropoff_ids = {
        stop.ride_passenger_id
        for stop in pending_stops
        if (
            stop.stop_type
            == RouteStop.StopType.DROPOFF
        )
    }

    completed_pickup_ids = {
        stop.ride_passenger_id
        for stop in all_stops
        if (
            stop.stop_type
            == RouteStop.StopType.PICKUP
            and
            stop.status
            == RouteStop.Status.COMPLETED
        )
    }

    onboard_ids = (
        completed_pickup_ids
        &
        pending_dropoff_ids
    )

    passenger_count_by_id = {}

    for stop in all_stops:
        passenger_count_by_id[
            stop.ride_passenger_id
        ] = (
            stop
            .ride_passenger
            .ride_request
            .passenger_count
        )

    initial_onboard = {
        f"rp:{ride_passenger_id}":
            passenger_count_by_id[
                ride_passenger_id
            ]

        for ride_passenger_id
        in onboard_ids
    }

    simulated_stops = tuple(
        SimulatedStop(
            group_key=(
                f"rp:{stop.ride_passenger_id}"
            ),

            passenger_count=(
                stop
                .ride_passenger
                .ride_request
                .passenger_count
            ),

            node=stop.node,

            stop_type=stop.stop_type,
        )

        for stop
        in pending_stops
    )

    return (
        pending_stops,
        simulated_stops,
        initial_onboard,
    )


def _recalculate_shared_route_after_cancellation(
    *,
    route,
    vehicle,
    reference_time,
):
    """
    Passenger حذف شده است، اما Shared Ride هنوز Passenger فعال دارد.

    Remaining stops دوباره از current taxi position شبیه‌سازی می‌شوند
    و ETA / route metrics / revision به‌روز می‌شوند.

    ترتیب remaining stops حفظ می‌شود؛ فقط stopهای Passenger لغوشده
    از مسیر عملیاتی حذف می‌شوند.
    """

    from datetime import timedelta

    from shared_ride.simulation import (
        SharedRouteSimulationService,
    )

    if vehicle.current_node_id is None:
        raise RideLifecycleError(
            "Shared taxi has no current position."
        )

    (
        pending_stops,
        simulated_stops,
        initial_onboard,
    ) = (
        _build_remaining_shared_simulation_state(
            route=route
        )
    )

    if not pending_stops:
        return None

    simulation = (
        SharedRouteSimulationService
        .simulate(
            current_node=(
                vehicle.current_node
            ),

            vehicle_capacity=(
                vehicle.capacity
            ),

            stops=(
                simulated_stops
            ),

            initial_onboard=(
                initial_onboard
            ),
        )
    )

    if not simulation.is_valid:
        raise RideLifecycleError(
            (
                "Remaining shared route became invalid "
                "after cancellation: "
                + ", ".join(
                    simulation.violations
                )
            )
        )

    if (
        len(simulation.stop_results)
        != len(pending_stops)
    ):
        raise RideLifecycleError(
            (
                "Shared route recalculation returned "
                "an incomplete stop result."
            )
        )

    for (
        stop,
        stop_result,
    ) in zip(
        pending_stops,
        simulation.stop_results,
    ):

        stop.estimated_arrival_minutes = (
            stop_result.arrival_minutes
        )

        stop.estimated_arrival_time = (
            reference_time
            + timedelta(
                minutes=(
                    stop_result
                    .arrival_minutes
                )
            )
        )

        stop.save(
            update_fields=[
                "estimated_arrival_minutes",
                "estimated_arrival_time",
                "updated_at",
            ]
        )

    route.revision += 1

    route.total_estimated_time_minutes = (
        simulation.total_time_minutes
    )

    route.total_estimated_distance_km = (
        simulation.total_distance_km
    )

    route.save(
        update_fields=[
            "revision",
            "total_estimated_time_minutes",
            "total_estimated_distance_km",
            "updated_at",
        ]
    )

    return simulation


def _finish_shared_ride_after_last_pre_pickup_cancellation(
    *,
    route,
    ride,
    vehicle,
    reference_time,
):
    """
    بعد از Cancellation هیچ PENDING stop باقی نمانده است.

    اگر قبلاً Passenger دیگری واقعاً Dropoff شده باشد،
    Shared Ride را COMPLETED می‌بندیم.

    در غیر این صورت کل Shared Ride عملاً Cancel شده است.
    """

    from shared_ride.models import RouteStop

    served_any_passenger = (
        RouteStop.objects
        .filter(
            route=route,

            stop_type=(
                RouteStop.StopType.DROPOFF
            ),

            status=(
                RouteStop.Status.COMPLETED
            ),
        )
        .exists()
    )

    if served_any_passenger:

        route.status = (
            route.Status.COMPLETED
        )

        ride.status = (
            Ride.Status.COMPLETED
        )

        ride.completed_at = (
            reference_time
        )

        ride.save(
            update_fields=[
                "status",
                "completed_at",
                "updated_at",
            ]
        )

    else:

        route.status = (
            route.Status.CANCELLED
        )

        ride.status = (
            Ride.Status.CANCELLED
        )

        ride.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

    route.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    vehicle.ride_mode = (
        Vehicle.RideMode.IDLE
    )

    vehicle.save(
        update_fields=[
            "ride_mode",
            "updated_at",
        ]
    )


def _cancel_shared_passenger_before_pickup(
    *,
    active_ride,
    ride_request,
    reference_time,
):
    """
    فقط Passenger Group مربوط به همین RideRequest را از Shared Route
    حذف می‌کند.

    نکته‌ی مهم:
    Ride ممکن است IN_PROGRESS باشد چون Passenger دیگری قبلاً pickup
    شده است. بنابراین برای اجازه‌ی Cancel، وضعیت PICKUP stop همین
    Passenger بررسی می‌شود، نه status کلی Ride.
    """

    from shared_ride.models import (
        Route,
        RouteStop,
    )

    vehicle = (
        Vehicle.objects
        .select_for_update()
        .get(
            pk=active_ride.vehicle_id
        )
    )

    try:
        route = (
            Route.objects
            .select_for_update()
            .get(
                ride=active_ride,
                status=Route.Status.ACTIVE,
            )
        )

    except Route.DoesNotExist:
        raise RideLifecycleError(
            "Active shared route was not found."
        )

    try:
        ride_passenger = (
            RidePassenger.objects
            .select_for_update()
            .get(
                ride=active_ride,
                ride_request=ride_request,
            )
        )

    except RidePassenger.DoesNotExist:
        raise RideLifecycleError(
            (
                "Passenger group was not found "
                "in the active shared ride."
            )
        )

    passenger_stops = list(
        RouteStop.objects
        .select_for_update()
        .filter(
            route=route,
            ride_passenger=ride_passenger,
        )
        .order_by(
            "sequence_number",
            "id",
        )
    )

    pickup_stop = next(
        (
            stop
            for stop
            in passenger_stops
            if (
                stop.stop_type
                == RouteStop.StopType.PICKUP
            )
        ),
        None,
    )

    if pickup_stop is None:
        raise RideLifecycleError(
            "Shared passenger pickup stop was not found."
        )

    # Passenger خودش قبلاً سوار شده است.
    if (
        pickup_stop.status
        == RouteStop.Status.COMPLETED
    ):
        raise RideLifecycleError(
            "Ride cannot be cancelled after pickup."
        )

    if (
        pickup_stop.status
        != RouteStop.Status.PENDING
    ):
        raise RideLifecycleError(
            (
                "Ride request cannot be cancelled "
                "in its current shared-route state."
            )
        )

    # فقط stopهای هنوز عملیاتی Passenger لغوشده حذف می‌شوند.
    RouteStop.objects.filter(
        route=route,
        ride_passenger=ride_passenger,
        status=RouteStop.Status.PENDING,
    ).update(
        status=RouteStop.Status.CANCELLED,
        updated_at=reference_time,
    )

    remaining_pending_exists = (
        RouteStop.objects
        .filter(
            route=route,
            status=RouteStop.Status.PENDING,
        )
        .exists()
    )

    if remaining_pending_exists:

        # Passengerهای دیگر باقی می‌مانند.
        # Taxi همچنان SHARED و Ride همچنان active است.
        _recalculate_shared_route_after_cancellation(
            route=route,
            vehicle=vehicle,
            reference_time=reference_time,
        )

    else:

        # Passenger فعال دیگری باقی نمانده است.
        _finish_shared_ride_after_last_pre_pickup_cancellation(
            route=route,
            ride=active_ride,
            vehicle=vehicle,
            reference_time=reference_time,
        )


@transaction.atomic
def cancel_ride_request(
    ride_request,
    passenger_profile,
):
    """
    Passenger cancellation policy:

    PENDING:
        - Request -> CANCELLED
        - ACTIVE TaxiHold -> RELEASED / EXPIRED

    PRIVATE before pickup:
        - Request -> CANCELLED
        - Ride -> CANCELLED
        - Vehicle -> IDLE

    SHARED before THIS passenger's pickup:
        - only this Passenger's pending pickup/dropoff -> CANCELLED

        If other Passenger groups remain:
            - Ride stays active
            - Route stays active
            - Vehicle stays SHARED
            - route ETA/metrics are recalculated

        If no operational stops remain:
            - Route/Ride are closed
            - Vehicle -> IDLE

    After THIS passenger's pickup:
        - cancellation is rejected.
    """

    reference_time = timezone.now()

    # =====================================================
    # 1. Lock Request + Ownership
    # =====================================================

    ride_request = (
        RideRequest.objects
        .select_for_update()
        .get(
            pk=ride_request.pk
        )
    )

    if (
        ride_request.passenger_id
        != passenger_profile.id
    ):
        raise RideLifecycleError(
            (
                "This ride request does not "
                "belong to this passenger."
            )
        )

    if (
        ride_request.status
        == RideRequest.Status.CANCELLED
    ):
        raise RideLifecycleError(
            "Ride request is already cancelled."
        )

    if (
        ride_request.status
        == RideRequest.Status.COMPLETED
    ):
        raise RideLifecycleError(
            (
                "Completed ride requests "
                "cannot be cancelled."
            )
        )

    # =====================================================
    # 2. Release Any Still-Active Hold
    # =====================================================

    _release_active_holds_for_request(
        ride_request,
        reference_time,
    )

    # =====================================================
    # 3. Find Current Active Operational Ride
    # =====================================================

    active_ride = (
        Ride.objects
        .select_for_update()
        .filter(
            passenger_groups__ride_request=(
                ride_request
            ),

            status__in=[
                Ride.Status.ASSIGNED,
                Ride.Status.ACCEPTED,
                Ride.Status.IN_PROGRESS,
            ],
        )
        .order_by(
            "-assigned_at"
        )
        .first()
    )

    # =====================================================
    # 4. Apply Ride-Type Specific Cancellation
    # =====================================================

    if active_ride is not None:

        if (
            active_ride.ride_type
            == RideRequest.RideType.PRIVATE
        ):

            _cancel_private_active_ride(
                active_ride=active_ride,
            )

        elif (
            active_ride.ride_type
            == RideRequest.RideType.SHARED
        ):

            _cancel_shared_passenger_before_pickup(
                active_ride=active_ride,
                ride_request=ride_request,
                reference_time=reference_time,
            )

        else:

            raise RideLifecycleError(
                "Unsupported ride type."
            )

    # =====================================================
    # 5. Request -> CANCELLED
    # =====================================================

    ride_request.status = (
        RideRequest.Status.CANCELLED
    )

    ride_request.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    return ride_request
