import pytest

from django.contrib.auth.models import User

from accounts.models import (
    DriverProfile,
    PassengerProfile,
)
from fleet.models import Vehicle
from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)
from rides.services import (
    RideLifecycleError,
    cancel_ride_request,
)
from road_network.models import (
    RoadEdge,
    RoadNode,
)
from shared_ride.models import (
    Route,
    RouteStop,
)


pytestmark = pytest.mark.django_db


def create_node(name, x):
    return RoadNode.objects.create(
        name=name,
        x=x,
        y=0,
    )


def connect(a, b):
    RoadEdge.objects.create(
        from_node=a,
        to_node=b,
        distance_km=1.0,
        travel_time_minutes=2,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )


def create_network():
    n1 = create_node("C1", 1)
    n2 = create_node("C2", 2)
    n3 = create_node("C3", 3)
    n4 = create_node("C4", 4)

    connect(n1, n2)
    connect(n2, n3)
    connect(n3, n4)

    return n1, n2, n3, n4


def create_passenger(username):
    user = User.objects.create_user(
        username=username,
        password="StrongPass123!",
    )

    return PassengerProfile.objects.create(
        user=user
    )


def create_vehicle(current_node):
    user = User.objects.create_user(
        username="cancel_driver",
        password="StrongPass123!",
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


def create_request(
    *,
    passenger,
    pickup,
    destination,
    ride_type,
    status=RideRequest.Status.ASSIGNED,
):
    return RideRequest.objects.create(
        passenger=passenger,
        ride_type=ride_type,
        passenger_count=1,
        pickup_node=pickup,
        destination_node=destination,
        status=status,
    )


def add_passenger_to_shared_route(
    *,
    ride,
    route,
    request,
    pickup,
    destination,
    pickup_status=RouteStop.Status.PENDING,
    pickup_sequence,
    dropoff_sequence,
):
    group = RidePassenger.objects.create(
        ride=ride,
        ride_request=request,
    )

    RouteStop.objects.create(
        route=route,
        ride_passenger=group,
        node=pickup,
        stop_type=RouteStop.StopType.PICKUP,
        sequence_number=pickup_sequence,
        estimated_arrival_minutes=2,
        status=pickup_status,
    )

    RouteStop.objects.create(
        route=route,
        ride_passenger=group,
        node=destination,
        stop_type=RouteStop.StopType.DROPOFF,
        sequence_number=dropoff_sequence,
        estimated_arrival_minutes=6,
        status=RouteStop.Status.PENDING,
    )

    return group


def test_private_request_can_cancel_before_pickup():
    n1, n2, _, _ = create_network()

    passenger = create_passenger(
        "private_cancel_passenger"
    )

    vehicle = create_vehicle(n1)
    vehicle.ride_mode = Vehicle.RideMode.PRIVATE
    vehicle.save()

    request = create_request(
        passenger=passenger,
        pickup=n2,
        destination=n1,
        ride_type=RideRequest.RideType.PRIVATE,
    )

    ride = Ride.objects.create(
        vehicle=vehicle,
        ride_type=RideRequest.RideType.PRIVATE,
        status=Ride.Status.ACCEPTED,
    )

    RidePassenger.objects.create(
        ride=ride,
        ride_request=request,
    )

    cancel_ride_request(
        request,
        passenger,
    )

    request.refresh_from_db()
    ride.refresh_from_db()
    vehicle.refresh_from_db()

    assert request.status == RideRequest.Status.CANCELLED
    assert ride.status == Ride.Status.CANCELLED
    assert vehicle.ride_mode == Vehicle.RideMode.IDLE


def test_single_shared_passenger_cancel_before_pickup_closes_ride():
    n1, n2, n3, _ = create_network()

    passenger = create_passenger(
        "single_shared_cancel"
    )

    vehicle = create_vehicle(n1)
    vehicle.ride_mode = Vehicle.RideMode.SHARED
    vehicle.save()

    request = create_request(
        passenger=passenger,
        pickup=n2,
        destination=n3,
        ride_type=RideRequest.RideType.SHARED,
    )

    ride = Ride.objects.create(
        vehicle=vehicle,
        ride_type=RideRequest.RideType.SHARED,
        status=Ride.Status.ACCEPTED,
    )

    group = RidePassenger.objects.create(
        ride=ride,
        ride_request=request,
    )

    route = Route.objects.create(
        ride=ride,
        status=Route.Status.ACTIVE,
        revision=1,
        total_estimated_time_minutes=4,
        total_estimated_distance_km=2.0,
    )

    RouteStop.objects.create(
        route=route,
        ride_passenger=group,
        node=n2,
        stop_type=RouteStop.StopType.PICKUP,
        sequence_number=1,
        estimated_arrival_minutes=2,
        status=RouteStop.Status.PENDING,
    )

    RouteStop.objects.create(
        route=route,
        ride_passenger=group,
        node=n3,
        stop_type=RouteStop.StopType.DROPOFF,
        sequence_number=2,
        estimated_arrival_minutes=4,
        status=RouteStop.Status.PENDING,
    )

    cancel_ride_request(
        request,
        passenger,
    )

    request.refresh_from_db()
    ride.refresh_from_db()
    route.refresh_from_db()
    vehicle.refresh_from_db()

    assert request.status == RideRequest.Status.CANCELLED
    assert ride.status == Ride.Status.CANCELLED
    assert route.status == Route.Status.CANCELLED
    assert vehicle.ride_mode == Vehicle.RideMode.IDLE

    assert not RouteStop.objects.filter(
        route=route,
        status=RouteStop.Status.PENDING,
    ).exists()


def test_cancel_second_shared_passenger_keeps_first_passenger_active():
    n1, n2, n3, n4 = create_network()

    passenger_a = create_passenger(
        "shared_a"
    )

    passenger_b = create_passenger(
        "shared_b"
    )

    vehicle = create_vehicle(n1)
    vehicle.ride_mode = Vehicle.RideMode.SHARED
    vehicle.save()

    request_a = create_request(
        passenger=passenger_a,
        pickup=n1,
        destination=n4,
        ride_type=RideRequest.RideType.SHARED,
    )

    request_b = create_request(
        passenger=passenger_b,
        pickup=n2,
        destination=n3,
        ride_type=RideRequest.RideType.SHARED,
    )

    # Ride is IN_PROGRESS because A is already onboard.
    # B must STILL be allowed to cancel because B's own
    # pickup has not happened.
    ride = Ride.objects.create(
        vehicle=vehicle,
        ride_type=RideRequest.RideType.SHARED,
        status=Ride.Status.IN_PROGRESS,
    )

    route = Route.objects.create(
        ride=ride,
        status=Route.Status.ACTIVE,
        revision=1,
        total_estimated_time_minutes=6,
        total_estimated_distance_km=3.0,
    )

    add_passenger_to_shared_route(
        ride=ride,
        route=route,
        request=request_a,
        pickup=n1,
        destination=n4,
        pickup_status=RouteStop.Status.COMPLETED,
        pickup_sequence=1,
        dropoff_sequence=4,
    )

    group_b = add_passenger_to_shared_route(
        ride=ride,
        route=route,
        request=request_b,
        pickup=n2,
        destination=n3,
        pickup_status=RouteStop.Status.PENDING,
        pickup_sequence=2,
        dropoff_sequence=3,
    )

    cancel_ride_request(
        request_b,
        passenger_b,
    )

    request_a.refresh_from_db()
    request_b.refresh_from_db()
    ride.refresh_from_db()
    route.refresh_from_db()
    vehicle.refresh_from_db()

    assert request_b.status == RideRequest.Status.CANCELLED
    assert request_a.status == RideRequest.Status.ASSIGNED

    assert ride.status == Ride.Status.IN_PROGRESS
    assert route.status == Route.Status.ACTIVE
    assert route.revision == 2
    assert vehicle.ride_mode == Vehicle.RideMode.SHARED

    assert not RouteStop.objects.filter(
        route=route,
        ride_passenger=group_b,
        status=RouteStop.Status.PENDING,
    ).exists()

    # A still has a pending dropoff.
    assert RouteStop.objects.filter(
        route=route,
        ride_passenger__ride_request=request_a,
        stop_type=RouteStop.StopType.DROPOFF,
        status=RouteStop.Status.PENDING,
    ).exists()


def test_shared_passenger_cannot_cancel_after_own_pickup():
    n1, n2, n3, _ = create_network()

    passenger = create_passenger(
        "picked_up_passenger"
    )

    vehicle = create_vehicle(n1)
    vehicle.ride_mode = Vehicle.RideMode.SHARED
    vehicle.save()

    request = create_request(
        passenger=passenger,
        pickup=n1,
        destination=n3,
        ride_type=RideRequest.RideType.SHARED,
    )

    ride = Ride.objects.create(
        vehicle=vehicle,
        ride_type=RideRequest.RideType.SHARED,
        status=Ride.Status.IN_PROGRESS,
    )

    route = Route.objects.create(
        ride=ride,
        status=Route.Status.ACTIVE,
        revision=1,
    )

    add_passenger_to_shared_route(
        ride=ride,
        route=route,
        request=request,
        pickup=n1,
        destination=n3,
        pickup_status=RouteStop.Status.COMPLETED,
        pickup_sequence=1,
        dropoff_sequence=2,
    )

    with pytest.raises(
        RideLifecycleError,
        match="after pickup",
    ):
        cancel_ride_request(
            request,
            passenger,
        )

    request.refresh_from_db()

    assert request.status == RideRequest.Status.ASSIGNED
