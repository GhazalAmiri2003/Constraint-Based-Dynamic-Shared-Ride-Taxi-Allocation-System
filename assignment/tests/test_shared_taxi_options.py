from datetime import timedelta

import pytest

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
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


def connect(
    first,
    second,
    *,
    time_minutes=2,
):
    return RoadEdge.objects.create(
        from_node=first,
        to_node=second,
        distance_km=1.0,
        travel_time_minutes=time_minutes,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )


def create_network():
    """
    N1 --2-- N2 --2-- N3 --2-- N4 --2-- N5
    """

    nodes = [
        create_node(
            f"N{i}",
            i,
        )
        for i in range(1, 6)
    ]

    for index in range(4):
        connect(
            nodes[index],
            nodes[index + 1],
        )

    return nodes


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


def create_vehicle(
    *,
    username,
    current_node,
    mode=Vehicle.RideMode.IDLE,
    online=True,
    available=True,
    capacity=4,
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

            if online

            else DriverProfile
            .AvailabilityStatus
            .OFFLINE
        ),
    )

    return Vehicle.objects.create(
        driver=driver,

        capacity=capacity,

        is_available=available,

        ride_mode=mode,

        current_node=current_node,
    )


def create_shared_request(
    *,
    username,
    pickup,
    destination,
    passenger_count=1,
):
    passenger = create_passenger(
        username
    )

    return RideRequest.objects.create(
        passenger=passenger,

        ride_type=(
            RideRequest
            .RideType
            .SHARED
        ),

        passenger_count=(
            passenger_count
        ),

        pickup_node=pickup,

        destination_node=destination,

        status=(
            RideRequest
            .Status
            .PENDING
        ),
    )


def create_existing_shared_ride(
    *,
    vehicle,
    reference_time,
    pickup,
    destination,
):
    passenger = create_passenger(
        "existing_passenger"
    )

    request = RideRequest.objects.create(
        passenger=passenger,

        ride_type=(
            RideRequest
            .RideType
            .SHARED
        ),

        passenger_count=1,

        pickup_node=pickup,

        destination_node=destination,

        status=(
            RideRequest
            .Status
            .ASSIGNED
        ),
    )


    ride = Ride.objects.create(
        vehicle=vehicle,

        ride_type=(
            RideRequest
            .RideType
            .SHARED
        ),

        status=(
            Ride.Status.IN_PROGRESS
        ),
    )


    ride_passenger = (
        RidePassenger.objects.create(
            ride=ride,
            ride_request=request,
        )
    )


    route = Route.objects.create(
        ride=ride,
        status=Route.Status.ACTIVE,
        revision=1,
    )


    RouteStop.objects.create(
        route=route,

        ride_passenger=(
            ride_passenger
        ),

        node=pickup,

        stop_type=(
            RouteStop
            .StopType
            .PICKUP
        ),

        sequence_number=1,

        status=(
            RouteStop
            .Status
            .COMPLETED
        ),

        actual_arrival_time=(
            reference_time
        ),
    )


    RouteStop.objects.create(
        route=route,

        ride_passenger=(
            ride_passenger
        ),

        node=destination,

        stop_type=(
            RouteStop
            .StopType
            .DROPOFF
        ),

        sequence_number=2,

        status=(
            RouteStop
            .Status
            .PENDING
        ),
    )


    SharedPassengerBaseline.objects.create(
        ride_passenger=(
            ride_passenger
        ),

        direct_trip_time_minutes=8,

        # vehicle در N2 است
        # N2 → N5 = 6 min
        baseline_expected_dropoff_at=(
            reference_time
            + timedelta(
                minutes=6
            )
        ),

        baseline_route_revision=1,
    )


    return (
        ride,
        route,
        ride_passenger,
    )


# =========================================================
# 1. IDLE Taxi Produces Shared Option
# =========================================================

def test_idle_taxi_produces_shared_option():

    n1, n2, _, n4, _ = (
        create_network()
    )


    vehicle = create_vehicle(
        username="driver_idle",

        current_node=n1,
    )


    request = create_shared_request(
        username="new_passenger",

        pickup=n2,

        destination=n4,
    )


    options = (
        SharedTaxiOptionService
        .generate_shared_taxi_options(
            request
        )
    )


    assert len(options) == 1


    option = options[0]


    assert (
        option.vehicle_id
        == vehicle.id
    )

    assert (
        option.vehicle_mode
        == Vehicle.RideMode.IDLE
    )


    # N1 → N2
    assert (
        option.pickup_eta_minutes
        == 2
    )


    # N2 → N4 = 4 min
    assert (
        option
        .estimated_trip_duration_minutes
        == 4
    )


    assert (
        option
        .expected_shared_delay_minutes
        == 0
    )


    assert len(
        option.proposed_route
    ) == 2


# =========================================================
# 2. PRIVATE Taxi Is Rejected
# =========================================================

def test_private_taxi_is_not_candidate():

    n1, n2, _, n4, _ = (
        create_network()
    )


    create_vehicle(
        username="driver_private",

        current_node=n1,

        mode=(
            Vehicle
            .RideMode
            .PRIVATE
        ),
    )


    request = create_shared_request(
        username="passenger_private_test",

        pickup=n2,

        destination=n4,
    )


    options = (
        SharedTaxiOptionService
        .generate_shared_taxi_options(
            request
        )
    )


    assert options == []


# =========================================================
# 3. Offline Taxi Is Rejected
# =========================================================

def test_offline_taxi_is_not_candidate():

    n1, n2, _, n4, _ = (
        create_network()
    )


    create_vehicle(
        username="driver_offline",

        current_node=n1,

        online=False,
    )


    request = create_shared_request(
        username="passenger_offline_test",

        pickup=n2,

        destination=n4,
    )


    options = (
        SharedTaxiOptionService
        .generate_shared_taxi_options(
            request
        )
    )


    assert options == []


# =========================================================
# 4. Existing SHARED Taxi Uses Insertion Engine
# =========================================================

def test_shared_taxi_uses_route_insertion_engine():

    (
        n1,
        n2,
        n3,
        n4,
        n5,
    ) = create_network()


    now = timezone.now()


    vehicle = create_vehicle(
        username="driver_shared",

        current_node=n2,

        mode=(
            Vehicle
            .RideMode
            .SHARED
        ),
    )


    _, route, _ = (
        create_existing_shared_ride(
            vehicle=vehicle,

            reference_time=now,

            pickup=n1,

            destination=n5,
        )
    )


    request = create_shared_request(
        username="new_shared_passenger",

        pickup=n3,

        destination=n4,
    )


    options = (
        SharedTaxiOptionService
        .generate_shared_taxi_options(
            request,

            reference_time=now,
        )
    )


    assert len(options) == 1


    option = options[0]


    assert (
        option.vehicle_mode
        == Vehicle.RideMode.SHARED
    )


    assert (
        option.source_route_id
        == route.id
    )


    assert (
        option.source_route_revision
        == 1
    )


    # Best route:
    #
    # Pickup new at N3
    # Dropoff new at N4
    # Dropoff A at N5

    assert (
        option
        .proposed_route[0]
        .node_id
        == n3.id
    )

    assert (
        option
        .proposed_route[0]
        .stop_type
        == RouteStop.StopType.PICKUP
    )


    assert (
        option
        .proposed_route[1]
        .node_id
        == n4.id
    )


    assert (
        option
        .proposed_route[2]
        .node_id
        == n5.id
    )


# =========================================================
# 5. Pickup Wait Constraint Removes Taxi
# =========================================================

@override_settings(
    MAX_SHARED_PICKUP_WAIT_MINUTES=1
)
def test_taxi_with_excessive_pickup_wait_removed():

    n1, n2, _, n4, _ = (
        create_network()
    )


    create_vehicle(
        username="driver_too_far",

        current_node=n1,
    )


    request = create_shared_request(
        username="passenger_wait",

        pickup=n2,

        destination=n4,
    )


    # N1 → N2 = 2 min
    # limit = 1

    options = (
        SharedTaxiOptionService
        .generate_shared_taxi_options(
            request
        )
    )


    assert options == []


# =========================================================
# 6. Active Hold Removes Taxi
# =========================================================

def test_actively_held_taxi_is_removed():

    n1, n2, _, n4, _ = (
        create_network()
    )


    vehicle = create_vehicle(
        username="driver_held",

        current_node=n1,
    )


    held_request = (
        create_shared_request(
            username="holding_passenger",

            pickup=n2,

            destination=n4,
        )
    )


    TaxiHold.objects.create(
        ride_request=(
            held_request
        ),

        vehicle=vehicle,

        status=(
            TaxiHold
            .Status
            .ACTIVE
        ),

        expires_at=(
            timezone.now()
            + timedelta(
                minutes=2
            )
        ),
    )


    new_request = (
        create_shared_request(
            username="second_passenger",

            pickup=n2,

            destination=n4,
        )
    )


    options = (
        SharedTaxiOptionService
        .generate_shared_taxi_options(
            new_request
        )
    )


    assert options == []


# =========================================================
# 7. Multiple Taxis Are Ranked
# =========================================================

def test_multiple_feasible_taxis_are_ranked():

    n1, n2, _, n4, _ = (
        create_network()
    )


    # Farther taxi
    far_vehicle = create_vehicle(
        username="driver_far",

        current_node=n1,
    )


    # Taxi already at pickup
    near_vehicle = create_vehicle(
        username="driver_near",

        current_node=n2,
    )


    request = create_shared_request(
        username="ranking_passenger",

        pickup=n2,

        destination=n4,
    )


    options = (
        SharedTaxiOptionService
        .generate_shared_taxi_options(
            request
        )
    )


    assert len(options) == 2


    assert options[0].rank == 1

    assert options[1].rank == 2


    assert (
        options[0].vehicle_id
        == near_vehicle.id
    )

    assert (
        options[1].vehicle_id
        == far_vehicle.id
    )