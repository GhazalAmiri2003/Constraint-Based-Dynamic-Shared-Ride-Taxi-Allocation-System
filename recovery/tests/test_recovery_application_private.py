import pytest

from django.contrib.auth.models import User

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from fleet.models import Vehicle
from recovery.application import (
    RecoveryApplicationError,
    RecoveryApplicationService,
)
from recovery.models import RecoveryEvent
from recovery.planning import (
    RecoveryPlanService,
)
from recovery.services import (
    RecoveryDetectionService,
)
from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)
from rides.services import (
    assign_private_ride,
)
from road_network.models import (
    RoadEdge,
    RoadNode,
)


pytestmark = pytest.mark.django_db


# =========================================================
# Helpers
# =========================================================

def create_network():

    n1 = RoadNode.objects.create(
        name="RECOVERY_N1",
        x=1,
        y=0,
    )

    n2 = RoadNode.objects.create(
        name="RECOVERY_N2",
        x=2,
        y=0,
    )

    n3 = RoadNode.objects.create(
        name="RECOVERY_N3",
        x=3,
        y=0,
    )


    RoadEdge.objects.create(
        from_node=n1,
        to_node=n2,
        distance_km=1,
        travel_time_minutes=1,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )


    RoadEdge.objects.create(
        from_node=n2,
        to_node=n3,
        distance_km=1,
        travel_time_minutes=1,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )


    return n1, n2, n3


def create_passenger():

    user = User.objects.create_user(
        username="recovery_private_passenger",
        password="StrongPass123!",
    )


    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.PASSENGER,
    )


    return PassengerProfile.objects.create(
        user=user
    )


def create_vehicle(
    *,
    username,
    current_node,
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
        ride_mode=Vehicle.RideMode.IDLE,
        current_node=current_node,
    )


def create_rejected_private_scenario():

    n1, n2, n3 = create_network()


    passenger = create_passenger()


    failed_vehicle = create_vehicle(
        username="failed_private_driver",
        current_node=n1,
    )


    replacement_vehicle = create_vehicle(
        username="replacement_private_driver",
        current_node=n1,
    )


    ride_request = RideRequest.objects.create(
        passenger=passenger,

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        passenger_count=1,

        pickup_node=n2,

        destination_node=n3,

        status=(
            RideRequest.Status.PENDING
        ),
    )


    old_ride = assign_private_ride(
        ride_request,
        failed_vehicle,
    )


    # =====================================================
    # Simulate current Driver Reject lifecycle result:
    #
    # Old Ride    -> REJECTED
    # Request     -> PENDING
    # Failed taxi -> IDLE
    # =====================================================

    old_ride.status = (
        Ride.Status.REJECTED
    )

    old_ride.save(
        update_fields=[
            "status",
        ]
    )


    ride_request.status = (
        RideRequest.Status.PENDING
    )

    ride_request.save(
        update_fields=[
            "status",
        ]
    )


    failed_vehicle.ride_mode = (
        Vehicle.RideMode.IDLE
    )

    failed_vehicle.save(
        update_fields=[
            "ride_mode",
        ]
    )


    return (
        old_ride,
        ride_request,
        failed_vehicle,
        replacement_vehicle,
    )


# =========================================================
# 1. Rejected Ride can still be detected
# =========================================================

def test_rejected_private_ride_is_detected_for_recovery():

    (
        old_ride,
        ride_request,
        _,
        _,
    ) = create_rejected_private_scenario()


    groups = (
        RecoveryDetectionService
        .find_affected_groups(
            old_ride
        )
    )


    assert len(groups) == 1

    assert (
        groups[0].ride_request_id
        == ride_request.id
    )


# =========================================================
# 2. Apply Private Recovery
# =========================================================

def test_private_recovery_reassigns_to_replacement_taxi():

    (
        old_ride,
        ride_request,
        failed_vehicle,
        replacement_vehicle,
    ) = create_rejected_private_scenario()


    groups = (
        RecoveryDetectionService
        .find_affected_groups(
            old_ride
        )
    )


    planning_result = (
        RecoveryPlanService
        .generate_recovery_plans(
            affected_groups=groups,

            failed_vehicle_id=(
                failed_vehicle.id
            ),
        )
    )


    assert (
        planning_result.best_plan
        is not None
    )


    event = RecoveryEvent.objects.create(
        ride=old_ride,

        failed_vehicle=(
            failed_vehicle
        ),

        trigger_type=(
            RecoveryEvent
            .TriggerType
            .DRIVER_REJECT
        ),
    )


    result = (
        RecoveryApplicationService
        .apply_best_private_plan(
            recovery_event=event,

            planning_result=(
                planning_result
            ),
        )
    )


    # =====================================================
    # Refresh DB
    # =====================================================

    event.refresh_from_db()

    old_ride.refresh_from_db()

    ride_request.refresh_from_db()

    failed_vehicle.refresh_from_db()

    replacement_vehicle.refresh_from_db()


    # =====================================================
    # Recovery Event
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
    # Old Ride remains historical REJECTED Ride
    # =====================================================

    assert (
        old_ride.status
        == Ride.Status.REJECTED
    )


    # =====================================================
    # Request is assigned again
    # =====================================================

    assert (
        ride_request.status
        == RideRequest.Status.ASSIGNED
    )


    # =====================================================
    # Replacement Ride
    # =====================================================

    new_ride = (
        Ride.objects.get(
            pk=(
                result
                .assignments[0]
                .new_ride_id
            )
        )
    )


    assert (
        new_ride.vehicle_id
        == replacement_vehicle.id
    )


    assert (
        new_ride.status
        == Ride.Status.ASSIGNED
    )


    assert (
        replacement_vehicle.ride_mode
        == Vehicle.RideMode.PRIVATE
    )


    # =====================================================
    # Historical old RidePassenger is preserved
    # AND a new membership exists.
    # =====================================================

    assert (
        RidePassenger.objects
        .filter(
            ride_request=ride_request
        )
        .count()
        == 2
    )


# =========================================================
# 3. Final Revalidation Failure Rolls Back
# =========================================================

def test_private_recovery_rolls_back_if_replacement_becomes_unavailable():

    (
        old_ride,
        ride_request,
        failed_vehicle,
        replacement_vehicle,
    ) = create_rejected_private_scenario()


    groups = (
        RecoveryDetectionService
        .find_affected_groups(
            old_ride
        )
    )


    planning_result = (
        RecoveryPlanService
        .generate_recovery_plans(
            affected_groups=groups,

            failed_vehicle_id=(
                failed_vehicle.id
            ),
        )
    )


    assert (
        planning_result.best_plan
        is not None
    )


    event = RecoveryEvent.objects.create(
        ride=old_ride,

        failed_vehicle=(
            failed_vehicle
        ),

        trigger_type=(
            RecoveryEvent
            .TriggerType
            .DRIVER_REJECT
        ),
    )


    # =====================================================
    # Taxi changes AFTER planning.
    # =====================================================

    replacement_vehicle.is_available = False

    replacement_vehicle.save(
        update_fields=[
            "is_available",
        ]
    )


    # =====================================================
    # Application must revalidate and reject the old plan.
    # =====================================================

    with pytest.raises(
        RecoveryApplicationError
    ):

        (
            RecoveryApplicationService
            .apply_best_private_plan(
                recovery_event=event,

                planning_result=(
                    planning_result
                ),
            )
        )


    event.refresh_from_db()

    ride_request.refresh_from_db()

    old_ride.refresh_from_db()


    assert (
        event.status
        == RecoveryEvent.Status.FAILED
    )


    # Recovery assignment did not partially happen.
    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )


    assert (
        old_ride.status
        == Ride.Status.REJECTED
    )


    # Only original historical membership remains.
    assert (
        RidePassenger.objects
        .filter(
            ride_request=ride_request
        )
        .count()
        == 1
    )