from django.db import transaction
from django.utils import timezone

from fleet.models import Vehicle
from rides.models import (
    Ride,
    RideRequest,
)
from shared_ride.models import (
    Route,
    RouteStop,
)


# =========================================================
# Cleanup Error
# =========================================================

class RecoveryCleanupError(Exception):
    pass


# =========================================================
# Failed Shared Ride Cleanup
# =========================================================

@transaction.atomic
def cleanup_failed_shared_route(
    *,
    ride_id,
    failed_vehicle_id,
):
    """
    Clean the old SHARED route after Recovery cannot
    produce/apply a replacement plan.

    Historical objects are preserved.

    We do NOT delete:
        - Ride
        - RidePassenger
        - Route
        - RouteStops

    Instead:
        pending RouteStops -> CANCELLED
        active Route       -> CANCELLED
        failed Vehicle     -> IDLE

    RideRequests remain PENDING so the passenger can
    still retry later.
    """

    # =====================================================
    # 1. Lock Ride
    # =====================================================

    try:

        ride = (
            Ride.objects
            .select_for_update()
            .get(
                pk=ride_id
            )
        )

    except Ride.DoesNotExist:

        raise RecoveryCleanupError(
            "Failed ride does not exist."
        )


    # =====================================================
    # 2. Only SHARED needs Route cleanup
    # =====================================================

    if (
        ride.ride_type
        != RideRequest.RideType.SHARED
    ):

        return False


    # =====================================================
    # 3. Validate Failed Vehicle
    # =====================================================

    if (
        ride.vehicle_id
        != failed_vehicle_id
    ):

        raise RecoveryCleanupError(
            (
                "Failed vehicle does not "
                "belong to this ride."
            )
        )


    try:

        vehicle = (
            Vehicle.objects
            .select_for_update()
            .get(
                pk=failed_vehicle_id
            )
        )

    except Vehicle.DoesNotExist:

        raise RecoveryCleanupError(
            "Failed vehicle does not exist."
        )


    # =====================================================
    # 4. Lock Active Route
    # =====================================================

    route = (
        Route.objects
        .select_for_update()
        .filter(
            ride=ride,
            status=Route.Status.ACTIVE,
        )
        .first()
    )


    # Route may already have been cleaned.
    if route is None:

        if (
            vehicle.ride_mode
            != Vehicle.RideMode.IDLE
        ):

            vehicle.ride_mode = (
                Vehicle.RideMode.IDLE
            )

            vehicle.save(
                update_fields=[
                    "ride_mode",
                    "updated_at",
                ]
            )

        return False


    # =====================================================
    # 5. Cancel Remaining Pending Stops
    # =====================================================

    (
        RouteStop.objects
        .select_for_update()
        .filter(
            route=route,
            status=RouteStop.Status.PENDING,
        )
        .update(
            status=RouteStop.Status.CANCELLED,
            updated_at=timezone.now(),
        )
    )


    # =====================================================
    # 6. Cancel Old Route
    # =====================================================

    route.status = (
        Route.Status.CANCELLED
    )

    route.total_estimated_time_minutes = 0

    route.total_estimated_distance_km = 0

    route.revision += 1


    route.save(
        update_fields=[
            "status",
            "total_estimated_time_minutes",
            "total_estimated_distance_km",
            "revision",
            "updated_at",
        ]
    )


    # =====================================================
    # 7. Failed Taxi remains free
    # =====================================================

    vehicle.ride_mode = (
        Vehicle.RideMode.IDLE
    )

    vehicle.save(
        update_fields=[
            "ride_mode",
            "updated_at",
        ]
    )


    return True