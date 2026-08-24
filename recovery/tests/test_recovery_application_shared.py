from datetime import timedelta

import pytest

from django.contrib.auth.models import User
from django.utils import timezone

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from fleet.models import Vehicle
from recovery.models import RecoveryEvent
from recovery.planning import RecoveryPlanService
from recovery.services import RecoveryDetectionService
from recovery.shared_application import (
    SharedRecoveryApplicationError,
    SharedRecoveryApplicationService,
)
from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)
from road_network.models import (
    RoadEdge,
    RoadNode,
)
from shared_ride.models import (
    Route,
    RouteStop,
    SharedPassengerBaseline,
)


pytestmark = pytest.mark.django_db


# =========================================================
# Network
# =========================================================

def create_network():

    nodes = []

    for index in range(1, 6):

        nodes.append(

            RoadNode.objects.create(
                name=f"SHARED_RECOVERY_N{index}",
                x=index,
                y=0,
            )
        )


    for index in range(4):

        RoadEdge.objects.create(

            from_node=nodes[index],

            to_node=nodes[index + 1],

            distance_km=1,

            travel_time_minutes=1,

            road_type=(
                RoadEdge.RoadType.LOCAL
            ),

            is_bidirectional=True,
        )


    return nodes


# =========================================================
# Passenger
# =========================================================

def create_passenger(
    username,
):

    user = User.objects.create_user(
        username=username,
        password="StrongPass123!",
    )


    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.PASSENGER,
    )


    return PassengerProfile.objects.create(
        user=user
    )


# =========================================================
# Vehicle
# =========================================================

def create_vehicle(
    *,
    username,
    current_node,
    ride_mode,
):

    user = User.objects.create_user(
        username=username,
        password="StrongPass123!",
    )


    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.DRIVER,
    )


    driver = DriverProfile.objects.create(

        user=user,

        availability_status=(
            DriverProfile
            .AvailabilityStatus
            .ONLINE
        ),
    )


    return Vehicle.objects.create(

        driver=driver,

        capacity=4,

        is_available=True,

        ride_mode=ride_mode,

        current_node=current_node,
    )


# =========================================================
# Scenario
# =========================================================

def create_shared_recovery_scenario():

    nodes = create_network()


    passenger = create_passenger(
        "shared_recovery_passenger"
    )


    failed_vehicle = create_vehicle(

        username="failed_shared_driver",

        current_node=nodes[0],

        ride_mode=(
            Vehicle.RideMode.SHARED
        ),
    )


    replacement_vehicle = create_vehicle(

        username="replacement_shared_driver",

        current_node=nodes[0],

        ride_mode=(
            Vehicle.RideMode.IDLE
        ),
    )


    ride_request = (
        RideRequest.objects.create(

            passenger=passenger,

            ride_type=(
                RideRequest.RideType.SHARED
            ),

            passenger_count=1,

            pickup_node=nodes[1],

            destination_node=nodes[4],

            status=(
                RideRequest.Status.ASSIGNED
            ),
        )
    )


    old_ride = Ride.objects.create(

        vehicle=failed_vehicle,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        status=(
            Ride.Status.REJECTED
        ),
    )


    old_membership = (
        RidePassenger.objects.create(

            ride=old_ride,

            ride_request=ride_request,
        )
    )


    old_route = Route.objects.create(

        ride=old_ride,

        status=(
            Route.Status.ACTIVE
        ),

        revision=1,

        total_estimated_time_minutes=4,

        total_estimated_distance_km=4,
    )


    pickup = RouteStop.objects.create(

        route=old_route,

        ride_passenger=old_membership,

        node=nodes[1],

        stop_type=(
            RouteStop.StopType.PICKUP
        ),

        sequence_number=1,

        estimated_arrival_minutes=1,

        status=(
            RouteStop.Status.PENDING
        ),
    )


    dropoff = RouteStop.objects.create(

        route=old_route,

        ride_passenger=old_membership,

        node=nodes[4],

        stop_type=(
            RouteStop.StopType.DROPOFF
        ),

        sequence_number=2,

        estimated_arrival_minutes=4,

        status=(
            RouteStop.Status.PENDING
        ),
    )


    SharedPassengerBaseline.objects.create(

        ride_passenger=(
            old_membership
        ),

        direct_trip_time_minutes=3,

        baseline_expected_dropoff_at=(
            timezone.now()
            + timedelta(
                minutes=4
            )
        ),

        baseline_route_revision=1,
    )


    return {
        "nodes": nodes,

        "ride_request": (
            ride_request
        ),

        "old_ride": (
            old_ride
        ),

        "old_membership": (
            old_membership
        ),

        "old_route": (
            old_route
        ),

        "pickup": pickup,

        "dropoff": dropoff,

        "failed_vehicle": (
            failed_vehicle
        ),

        "replacement_vehicle": (
            replacement_vehicle
        ),
    }


# =========================================================
# 1. Detection
# =========================================================

def test_rejected_shared_passenger_is_detected():

    scenario = (
        create_shared_recovery_scenario()
    )


    groups = (
        RecoveryDetectionService
        .find_affected_groups(
            scenario["old_ride"]
        )
    )


    assert len(groups) == 1

    assert (
        groups[0].ride_request_id
        == scenario[
            "ride_request"
        ].id
    )


# =========================================================
# 2. Shared Recovery Success
# =========================================================

def test_shared_recovery_reassigns_passenger():

    scenario = (
        create_shared_recovery_scenario()
    )


    groups = (
        RecoveryDetectionService
        .find_affected_groups(
            scenario["old_ride"]
        )
    )


    planning = (
        RecoveryPlanService
        .generate_recovery_plans(

            affected_groups=groups,

            failed_vehicle_id=(
                scenario[
                    "failed_vehicle"
                ].id
            ),
        )
    )


    assert (
        planning.best_plan
        is not None
    )


    event = RecoveryEvent.objects.create(

        ride=(
            scenario["old_ride"]
        ),

        failed_vehicle=(
            scenario[
                "failed_vehicle"
            ]
        ),

        trigger_type=(
            RecoveryEvent
            .TriggerType
            .DRIVER_REJECT
        ),
    )


    result = (
        SharedRecoveryApplicationService
        .apply_best_shared_plan(

            recovery_event=event,

            planning_result=planning,
        )
    )


    # =====================================================
    # Refresh
    # =====================================================

    event.refresh_from_db()

    scenario[
        "ride_request"
    ].refresh_from_db()

    scenario[
        "old_route"
    ].refresh_from_db()

    scenario[
        "pickup"
    ].refresh_from_db()

    scenario[
        "dropoff"
    ].refresh_from_db()

    scenario[
        "failed_vehicle"
    ].refresh_from_db()

    scenario[
        "replacement_vehicle"
    ].refresh_from_db()


    # =====================================================
    # Event
    # =====================================================

    assert (
        event.status
        == RecoveryEvent.Status.COMPLETED
    )


    assert (
        result.recovered_group_count
        == 1
    )


    # =====================================================
    # Old Route History
    # =====================================================

    assert (
        scenario["pickup"].status
        == RouteStop.Status.CANCELLED
    )


    assert (
        scenario["dropoff"].status
        == RouteStop.Status.CANCELLED
    )


    assert (
        scenario["old_route"].status
        == Route.Status.CANCELLED
    )


    assert (
        scenario["failed_vehicle"].ride_mode
        == Vehicle.RideMode.IDLE
    )


    # =====================================================
    # Request assigned again
    # =====================================================

    assert (
        scenario[
            "ride_request"
        ].status
        == RideRequest.Status.ASSIGNED
    )


    # =====================================================
    # New Shared Ride
    # =====================================================

    new_ride_id = (
        result
        .assignments[0]
        .new_ride_id
    )


    new_ride = (
        Ride.objects.get(
            pk=new_ride_id
        )
    )


    assert (
        new_ride.vehicle_id
        == scenario[
            "replacement_vehicle"
        ].id
    )


    assert (
        new_ride.ride_type
        == RideRequest.RideType.SHARED
    )


    assert (
        new_ride.status
        == Ride.Status.ASSIGNED
    )


    # =====================================================
    # New Route
    # =====================================================

    new_route = (
        Route.objects.get(
            pk=(
                result
                .assignments[0]
                .new_route_id
            )
        )
    )


    assert (
        new_route.status
        == Route.Status.ACTIVE
    )


    assert (
        RouteStop.objects
        .filter(
            route=new_route,

            status=(
                RouteStop.Status.PENDING
            ),
        )
        .count()
        == 2
    )


    # =====================================================
    # Historical + new memberships
    # =====================================================

    assert (
        RidePassenger.objects
        .filter(
            ride_request=(
                scenario[
                    "ride_request"
                ]
            )
        )
        .count()
        == 2
    )


# =========================================================
# 3. Final Revalidation Failure → Rollback
# =========================================================

def test_shared_recovery_rolls_back_if_replacement_changes():

    scenario = (
        create_shared_recovery_scenario()
    )


    groups = (
        RecoveryDetectionService
        .find_affected_groups(
            scenario["old_ride"]
        )
    )


    planning = (
        RecoveryPlanService
        .generate_recovery_plans(

            affected_groups=groups,

            failed_vehicle_id=(
                scenario[
                    "failed_vehicle"
                ].id
            ),
        )
    )


    assert (
        planning.best_plan
        is not None
    )


    event = RecoveryEvent.objects.create(

        ride=(
            scenario["old_ride"]
        ),

        failed_vehicle=(
            scenario[
                "failed_vehicle"
            ]
        ),

        trigger_type=(
            RecoveryEvent
            .TriggerType
            .DRIVER_REJECT
        ),
    )


    # =====================================================
    # Replacement changes AFTER planning
    # =====================================================

    scenario[
        "replacement_vehicle"
    ].is_available = False


    scenario[
        "replacement_vehicle"
    ].save(
        update_fields=[
            "is_available",
        ]
    )


    # =====================================================
    # Apply
    # =====================================================

    with pytest.raises(
        SharedRecoveryApplicationError
    ):

        (
            SharedRecoveryApplicationService
            .apply_best_shared_plan(

                recovery_event=event,

                planning_result=planning,
            )
        )


    # =====================================================
    # Refresh
    # =====================================================

    event.refresh_from_db()

    scenario[
        "ride_request"
    ].refresh_from_db()

    scenario[
        "old_route"
    ].refresh_from_db()

    scenario[
        "pickup"
    ].refresh_from_db()

    scenario[
        "dropoff"
    ].refresh_from_db()


    # =====================================================
    # Event failed
    # =====================================================

    assert (
        event.status
        == RecoveryEvent.Status.FAILED
    )


    # =====================================================
    # EVERYTHING inside the Recovery transaction rolled back
    # =====================================================

    assert (
        scenario[
            "ride_request"
        ].status
        == RideRequest.Status.ASSIGNED
    )


    assert (
        scenario["pickup"].status
        == RouteStop.Status.PENDING
    )


    assert (
        scenario["dropoff"].status
        == RouteStop.Status.PENDING
    )


    assert (
        scenario["old_route"].status
        == Route.Status.ACTIVE
    )


    # No second membership was created.
    assert (
        RidePassenger.objects
        .filter(
            ride_request=(
                scenario[
                    "ride_request"
                ]
            )
        )
        .count()
        == 1
    )