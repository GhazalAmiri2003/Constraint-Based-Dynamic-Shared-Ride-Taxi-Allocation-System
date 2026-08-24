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
from recovery.services import (
    AffectedPassengerGroup,
    RecoveryDetectionService,
    RecoveryPriorityService,
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
# Helpers
# =========================================================

def create_node(
    name,
    x,
):

    return RoadNode.objects.create(
        name=name,
        x=x,
        y=0,
    )


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
        user=user,
    )


def create_vehicle(
    username,
    current_node,
    mode,
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

        ride_mode=mode,

        current_node=current_node,
    )


def create_request(
    *,
    passenger,
    ride_type,
    pickup,
    destination,
):

    return RideRequest.objects.create(

        passenger=passenger,

        ride_type=ride_type,

        passenger_count=1,

        pickup_node=pickup,

        destination_node=destination,

        status=RideRequest.Status.ASSIGNED,
    )


# =========================================================
# 1. PRIVATE before pickup is affected
# =========================================================

def test_private_passenger_before_pickup_is_detected():

    n1 = create_node(
        "PRIVATE_N1",
        1,
    )

    n2 = create_node(
        "PRIVATE_N2",
        2,
    )


    passenger = create_passenger(
        "private_recovery_passenger"
    )


    vehicle = create_vehicle(

        "private_recovery_driver",

        n1,

        Vehicle.RideMode.PRIVATE,
    )


    ride_request = create_request(

        passenger=passenger,

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        pickup=n1,

        destination=n2,
    )


    ride = Ride.objects.create(

        vehicle=vehicle,

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        status=Ride.Status.ASSIGNED,
    )


    ride_passenger = (
        RidePassenger.objects.create(

            ride=ride,

            ride_request=ride_request,
        )
    )


    groups = (
        RecoveryDetectionService
        .find_affected_groups(
            ride
        )
    )


    assert len(groups) == 1

    assert (
        groups[0].ride_passenger_id
        == ride_passenger.id
    )

    assert (
        groups[0].ride_request_id
        == ride_request.id
    )


# =========================================================
# 2. PRIVATE after pickup is NOT recoverable
# =========================================================

def test_private_passenger_in_progress_is_not_detected():

    n1 = create_node(
        "PRIVATE_PROGRESS_N1",
        1,
    )

    n2 = create_node(
        "PRIVATE_PROGRESS_N2",
        2,
    )


    passenger = create_passenger(
        "private_onboard_passenger"
    )


    vehicle = create_vehicle(

        "private_onboard_driver",

        n1,

        Vehicle.RideMode.PRIVATE,
    )


    ride_request = create_request(

        passenger=passenger,

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        pickup=n1,

        destination=n2,
    )


    ride = Ride.objects.create(

        vehicle=vehicle,

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        status=Ride.Status.IN_PROGRESS,
    )


    RidePassenger.objects.create(

        ride=ride,

        ride_request=ride_request,
    )


    groups = (
        RecoveryDetectionService
        .find_affected_groups(
            ride
        )
    )


    assert groups == []


# =========================================================
# 3. SHARED:
#    onboard passenger excluded
#    waiting passenger included
# =========================================================

def test_shared_only_not_picked_up_group_is_detected():

    n1 = create_node(
        "SHARED_N1",
        1,
    )

    n2 = create_node(
        "SHARED_N2",
        2,
    )

    n3 = create_node(
        "SHARED_N3",
        3,
    )

    n4 = create_node(
        "SHARED_N4",
        4,
    )


    passenger_one = create_passenger(
        "shared_onboard_passenger"
    )

    passenger_two = create_passenger(
        "shared_waiting_passenger"
    )


    vehicle = create_vehicle(

        "shared_recovery_driver",

        n2,

        Vehicle.RideMode.SHARED,
    )


    request_one = create_request(

        passenger=passenger_one,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        pickup=n1,

        destination=n4,
    )


    request_two = create_request(

        passenger=passenger_two,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        pickup=n3,

        destination=n4,
    )


    ride = Ride.objects.create(

        vehicle=vehicle,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        status=Ride.Status.IN_PROGRESS,
    )


    rp_one = RidePassenger.objects.create(

        ride=ride,

        ride_request=request_one,
    )


    rp_two = RidePassenger.objects.create(

        ride=ride,

        ride_request=request_two,
    )


    route = Route.objects.create(

        ride=ride,

        status=Route.Status.ACTIVE,

        revision=1,
    )


    # Passenger 1 already onboard.
    RouteStop.objects.create(

        route=route,

        ride_passenger=rp_one,

        node=n1,

        stop_type=(
            RouteStop.StopType.PICKUP
        ),

        sequence_number=1,

        status=(
            RouteStop.Status.COMPLETED
        ),
    )


    RouteStop.objects.create(

        route=route,

        ride_passenger=rp_one,

        node=n4,

        stop_type=(
            RouteStop.StopType.DROPOFF
        ),

        sequence_number=2,

        status=(
            RouteStop.Status.PENDING
        ),
    )


    # Passenger 2 has NOT been picked up.
    RouteStop.objects.create(

        route=route,

        ride_passenger=rp_two,

        node=n3,

        stop_type=(
            RouteStop.StopType.PICKUP
        ),

        sequence_number=3,

        status=(
            RouteStop.Status.PENDING
        ),
    )


    RouteStop.objects.create(

        route=route,

        ride_passenger=rp_two,

        node=n4,

        stop_type=(
            RouteStop.StopType.DROPOFF
        ),

        sequence_number=4,

        status=(
            RouteStop.Status.PENDING
        ),
    )


    groups = (
        RecoveryDetectionService
        .find_affected_groups(
            ride
        )
    )


    assert len(groups) == 1

    assert (
        groups[0].ride_request_id
        == request_two.id
    )


# =========================================================
# 4. Priority:
#    less pickup slack first
#    then older request
# =========================================================

def test_recovery_priority_orders_most_urgent_first():

    now = timezone.now()


    less_urgent = AffectedPassengerGroup(

        ride_passenger_id=1,

        ride_request_id=1,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        passenger_count=1,

        pickup_node_id=1,

        destination_node_id=2,

        original_request_time=(
            now
            - timedelta(
                minutes=2
            )
        ),

        pickup_slack_minutes=8.0,
    )


    urgent = AffectedPassengerGroup(

        ride_passenger_id=2,

        ride_request_id=2,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        passenger_count=1,

        pickup_node_id=3,

        destination_node_id=4,

        original_request_time=(
            now
            - timedelta(
                minutes=8
            )
        ),

        pickup_slack_minutes=2.0,
    )


    ranked = (
        RecoveryPriorityService
        .rank_groups(
            [
                less_urgent,
                urgent,
            ]
        )
    )


    assert (
        ranked[0].ride_request_id
        == urgent.ride_request_id
    )


# =========================================================
# 5. Same urgency:
#    original request time breaks the tie
# =========================================================

def test_older_request_wins_when_urgency_is_equal():

    now = timezone.now()


    older = AffectedPassengerGroup(

        ride_passenger_id=1,

        ride_request_id=1,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        passenger_count=1,

        pickup_node_id=1,

        destination_node_id=2,

        original_request_time=(
            now
            - timedelta(
                minutes=8
            )
        ),

        pickup_slack_minutes=2.0,
    )


    newer = AffectedPassengerGroup(

        ride_passenger_id=2,

        ride_request_id=2,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        passenger_count=1,

        pickup_node_id=3,

        destination_node_id=4,

        original_request_time=(
            now
            - timedelta(
                minutes=5
            )
        ),

        pickup_slack_minutes=2.0,
    )


    ranked = (
        RecoveryPriorityService
        .rank_groups(
            [
                newer,
                older,
            ]
        )
    )


    assert (
        ranked[0].ride_request_id
        == older.ride_request_id
    )