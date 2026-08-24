from types import SimpleNamespace

import pytest

from django.contrib.auth.models import User

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from fleet.models import Vehicle
from notifications.models import Notification
from recovery.models import RecoveryEvent
from recovery.orchestrator import (
    RecoveryOrchestrator,
)
from recovery.planning import (
    RecoveryPlanService,
)
from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)
from road_network.models import RoadNode
from shared_ride.models import (
    Route,
    RouteStop,
)


pytestmark = pytest.mark.django_db


# =========================================================
# Scenario
# =========================================================

def create_failed_shared_scenario():

    node = RoadNode.objects.create(
        name="FAILED_RECOVERY_NODE",
        x=1,
        y=0,
    )


    # =====================================================
    # Passenger
    # =====================================================

    passenger_user = User.objects.create_user(
        username="failed_recovery_passenger",
        password="StrongPass123!",
    )


    UserProfile.objects.create(
        user=passenger_user,
        role=UserProfile.Role.PASSENGER,
    )


    passenger = PassengerProfile.objects.create(
        user=passenger_user
    )


    # =====================================================
    # Driver
    # =====================================================

    driver_user = User.objects.create_user(
        username="failed_recovery_driver",
        password="StrongPass123!",
    )


    UserProfile.objects.create(
        user=driver_user,
        role=UserProfile.Role.DRIVER,
    )


    driver = DriverProfile.objects.create(

        user=driver_user,

        availability_status=(
            DriverProfile
            .AvailabilityStatus
            .ONLINE
        ),
    )


    vehicle = Vehicle.objects.create(

        driver=driver,

        capacity=4,

        is_available=True,

        # Reject/Unavailable trigger already freed Taxi.
        ride_mode=Vehicle.RideMode.IDLE,

        current_node=node,
    )


    # =====================================================
    # Request
    # =====================================================

    ride_request = RideRequest.objects.create(

        passenger=passenger,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        passenger_count=1,

        pickup_node=node,

        destination_node=node,

        status=(
            RideRequest.Status.PENDING
        ),
    )


    # =====================================================
    # Failed Ride
    # =====================================================

    ride = Ride.objects.create(

        vehicle=vehicle,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        status=(
            Ride.Status.REJECTED
        ),
    )


    membership = RidePassenger.objects.create(

        ride=ride,

        ride_request=ride_request,
    )


    # =====================================================
    # Old Route
    # =====================================================

    route = Route.objects.create(

        ride=ride,

        status=(
            Route.Status.ACTIVE
        ),

        revision=1,

        total_estimated_time_minutes=5,

        total_estimated_distance_km=2,
    )


    pickup = RouteStop.objects.create(

        route=route,

        ride_passenger=membership,

        node=node,

        stop_type=(
            RouteStop.StopType.PICKUP
        ),

        sequence_number=1,

        status=(
            RouteStop.Status.PENDING
        ),
    )


    dropoff = RouteStop.objects.create(

        route=route,

        ride_passenger=membership,

        node=node,

        stop_type=(
            RouteStop.StopType.DROPOFF
        ),

        sequence_number=2,

        status=(
            RouteStop.Status.PENDING
        ),
    )


    return (
        ride,
        ride_request,
        vehicle,
        route,
        pickup,
        dropoff,
    )


# =========================================================
# No feasible plan cleans old Shared Route
# =========================================================

def test_no_replacement_plan_cleans_old_shared_route(
    monkeypatch,
):

    (
        ride,
        ride_request,
        vehicle,
        route,
        pickup,
        dropoff,
    ) = create_failed_shared_scenario()


    # =====================================================
    # Force Planning to return no feasible plan.
    # =====================================================

    fake_result = (
        SimpleNamespace(
            best_plan=None
        )
    )


    monkeypatch.setattr(

        RecoveryPlanService,

        "generate_recovery_plans",

        classmethod(
            lambda cls, **kwargs:
                fake_result
        ),
    )


    event = (
        RecoveryOrchestrator
        .recover_ride(

            ride_id=ride.id,

            failed_vehicle_id=(
                vehicle.id
            ),

            trigger_type=(
                RecoveryEvent
                .TriggerType
                .DRIVER_REJECT
            ),
        )
    )


    # =====================================================
    # Refresh
    # =====================================================

    event.refresh_from_db()

    ride_request.refresh_from_db()

    vehicle.refresh_from_db()

    route.refresh_from_db()

    pickup.refresh_from_db()

    dropoff.refresh_from_db()


    # =====================================================
    # Recovery failed
    # =====================================================

    assert (
        event.status
        == RecoveryEvent.Status.FAILED
    )


    # =====================================================
    # Passenger remains available for future retry
    # =====================================================

    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )


    # =====================================================
    # No orphan active route
    # =====================================================

    assert (
        route.status
        == Route.Status.CANCELLED
    )


    assert (
        pickup.status
        == RouteStop.Status.CANCELLED
    )


    assert (
        dropoff.status
        == RouteStop.Status.CANCELLED
    )


    # =====================================================
    # Failed taxi is free
    # =====================================================

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )


    # =====================================================
    # Passenger receives failure notification
    # =====================================================

    assert (
        Notification.objects
        .filter(
            ride_request=ride_request,

            notification_type=(
                Notification
                .Type
                .RECOVERY_FAILED
            ),
        )
        .exists()
    )