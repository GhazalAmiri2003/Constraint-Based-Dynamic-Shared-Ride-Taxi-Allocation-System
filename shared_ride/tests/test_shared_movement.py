
import pytest

from django.contrib.auth.models import User

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
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
)
from shared_ride.movement_services import (
    SharedMovementAction,
    SharedMovementError,
    SharedRouteMovementService,
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
    N1 -- N2 -- N3 -- N4
    """

    n1 = create_node(
        "N1",
        1,
    )

    n2 = create_node(
        "N2",
        2,
    )

    n3 = create_node(
        "N3",
        3,
    )

    n4 = create_node(
        "N4",
        4,
    )


    connect(n1, n2)

    connect(n2, n3)

    connect(n3, n4)


    return (
        n1,
        n2,
        n3,
        n4,
    )


def create_passenger(
    username="passenger",
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
    current_node,
):
    user = User.objects.create_user(
        username="driver",
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

        ride_mode=(
            Vehicle.RideMode.SHARED
        ),

        current_node=current_node,
    )


def create_shared_ride(
    *,
    current_node,
    pickup_node,
    destination_node,
    ride_status=Ride.Status.ACCEPTED,
):
    passenger = create_passenger()

    vehicle = create_vehicle(
        current_node
    )


    ride_request = RideRequest.objects.create(
        passenger=passenger,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        passenger_count=1,

        pickup_node=pickup_node,

        destination_node=destination_node,

        status=(
            RideRequest.Status.ASSIGNED
        ),
    )


    ride = Ride.objects.create(
        vehicle=vehicle,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        status=ride_status,
    )


    ride_passenger = (
        RidePassenger.objects.create(
            ride=ride,
            ride_request=ride_request,
        )
    )


    route = Route.objects.create(
        ride=ride,

        status=Route.Status.ACTIVE,

        revision=1,
    )


    pickup_stop = (
        RouteStop.objects.create(
            route=route,

            ride_passenger=(
                ride_passenger
            ),

            node=pickup_node,

            stop_type=(
                RouteStop.StopType.PICKUP
            ),

            sequence_number=1,

            status=(
                RouteStop.Status.PENDING
            ),
        )
    )


    dropoff_stop = (
        RouteStop.objects.create(
            route=route,

            ride_passenger=(
                ride_passenger
            ),

            node=destination_node,

            stop_type=(
                RouteStop.StopType.DROPOFF
            ),

            sequence_number=2,

            status=(
                RouteStop.Status.PENDING
            ),
        )
    )


    return (
        vehicle,
        ride_request,
        ride,
        route,
        pickup_stop,
        dropoff_stop,
    )


# =========================================================
# 1. Movement Requires Accepted Ride
# =========================================================

def test_assigned_shared_ride_cannot_move():

    (
        n1,
        n2,
        _,
        n4,
    ) = create_network()


    (
        vehicle,
        _,
        _,
        _,
        _,
        _,
    ) = create_shared_ride(
        current_node=n1,

        pickup_node=n2,

        destination_node=n4,

        ride_status=(
            Ride.Status.ASSIGNED
        ),
    )


    with pytest.raises(
        SharedMovementError
    ):
        (
            SharedRouteMovementService
            .advance_shared_ride(
                vehicle.id
            )
        )


# =========================================================
# 2. Move Exactly One Graph Edge
# =========================================================

def test_shared_taxi_moves_only_one_edge():

    (
        n1,
        _,
        n3,
        n4,
    ) = create_network()


    (
        vehicle,
        _,
        _,
        _,
        pickup_stop,
        _,
    ) = create_shared_ride(
        current_node=n1,

        pickup_node=n3,

        destination_node=n4,
    )


    result = (
        SharedRouteMovementService
        .advance_shared_ride(
            vehicle.id
        )
    )


    vehicle.refresh_from_db()

    pickup_stop.refresh_from_db()


    # N1 → N2 only
    assert (
        vehicle.current_node.name
        == "N2"
    )


    assert (
        result.action
        == SharedMovementAction.MOVED
    )


    # هنوز به N3 نرسیده.
    assert (
        pickup_stop.status
        == RouteStop.Status.PENDING
    )


# =========================================================
# 3. Arrival At Pickup Completes Pickup
# =========================================================

def test_arriving_at_pickup_completes_stop():

    (
        n1,
        n2,
        _,
        n4,
    ) = create_network()


    (
        vehicle,
        _,
        ride,
        _,
        pickup_stop,
        dropoff_stop,
    ) = create_shared_ride(
        current_node=n1,

        pickup_node=n2,

        destination_node=n4,
    )


    result = (
        SharedRouteMovementService
        .advance_shared_ride(
            vehicle.id
        )
    )


    vehicle.refresh_from_db()

    ride.refresh_from_db()

    pickup_stop.refresh_from_db()


    assert (
        vehicle.current_node_id
        == n2.id
    )


    assert (
        pickup_stop.status
        == RouteStop.Status.COMPLETED
    )


    assert (
        pickup_stop.actual_arrival_time
        is not None
    )


    assert (
        ride.status
        == Ride.Status.IN_PROGRESS
    )


    assert (
        result.action
        == SharedMovementAction.STOP_COMPLETED
    )


    assert (
        result.completed_stop_id
        == pickup_stop.id
    )


    assert (
        result.next_stop_id
        == dropoff_stop.id
    )


# =========================================================
# 4. Stop At Current Node Requires No Movement
# =========================================================

def test_stop_at_current_node_is_completed_immediately():

    (
        _,
        n2,
        _,
        n4,
    ) = create_network()


    (
        vehicle,
        _,
        ride,
        _,
        pickup_stop,
        _,
    ) = create_shared_ride(
        current_node=n2,

        pickup_node=n2,

        destination_node=n4,
    )


    result = (
        SharedRouteMovementService
        .advance_shared_ride(
            vehicle.id
        )
    )


    vehicle.refresh_from_db()

    pickup_stop.refresh_from_db()

    ride.refresh_from_db()


    # Taxi stays at N2.
    assert (
        vehicle.current_node_id
        == n2.id
    )


    assert (
        pickup_stop.status
        == RouteStop.Status.COMPLETED
    )


    assert (
        ride.status
        == Ride.Status.IN_PROGRESS
    )


    assert (
        result.action
        == SharedMovementAction.STOP_COMPLETED
    )


# =========================================================
# 5. Final Dropoff Completes Everything
# =========================================================

def test_final_dropoff_completes_shared_ride():

    (
        _,
        n2,
        n3,
        _,
    ) = create_network()


    (
        vehicle,
        ride_request,
        ride,
        route,
        pickup_stop,
        dropoff_stop,
    ) = create_shared_ride(
        current_node=n2,

        pickup_node=n2,

        destination_node=n3,
    )


    # -----------------------------------------------------
    # First call:
    # complete pickup at current node.
    # -----------------------------------------------------

    (
        SharedRouteMovementService
        .advance_shared_ride(
            vehicle.id
        )
    )


    # -----------------------------------------------------
    # Second call:
    # N2 → N3
    # and final dropoff.
    # -----------------------------------------------------

    result = (
        SharedRouteMovementService
        .advance_shared_ride(
            vehicle.id
        )
    )


    vehicle.refresh_from_db()

    ride_request.refresh_from_db()

    ride.refresh_from_db()

    route.refresh_from_db()

    pickup_stop.refresh_from_db()

    dropoff_stop.refresh_from_db()


    assert (
        vehicle.current_node_id
        == n3.id
    )


    assert (
        dropoff_stop.status
        == RouteStop.Status.COMPLETED
    )


    assert (
        ride_request.status
        == RideRequest.Status.COMPLETED
    )


    assert (
        ride.status
        == Ride.Status.COMPLETED
    )


    assert (
        route.status
        == Route.Status.COMPLETED
    )


    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )


    assert (
        result.action
        == SharedMovementAction.RIDE_COMPLETED
    )


# =========================================================
# 6. Unreachable Next Stop Rejected
# =========================================================

def test_unreachable_shared_stop_is_rejected():

    n1 = create_node(
        "N1",
        1,
    )


    isolated = create_node(
        "ISOLATED",
        100,
    )


    (
        vehicle,
        _,
        _,
        _,
        pickup_stop,
        _,
    ) = create_shared_ride(
        current_node=n1,

        pickup_node=isolated,

        destination_node=isolated,
    )


    with pytest.raises(
        SharedMovementError
    ):
        (
            SharedRouteMovementService
            .advance_shared_ride(
                vehicle.id
            )
        )


    vehicle.refresh_from_db()

    pickup_stop.refresh_from_db()


    # Transaction rollback:
    # position unchanged
    assert (
        vehicle.current_node_id
        == n1.id
    )


    assert (
        pickup_stop.status
        == RouteStop.Status.PENDING
    )