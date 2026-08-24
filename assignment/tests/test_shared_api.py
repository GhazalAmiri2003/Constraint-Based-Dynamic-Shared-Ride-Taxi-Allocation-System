from datetime import timedelta

import pytest

from django.contrib.auth.models import User
from django.utils import timezone

from rest_framework.test import APIClient

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from assignment.models import TaxiHold
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
    N1 --2-- N2 --2-- N3 --2-- N4
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

    passenger = (
        PassengerProfile.objects.create(
            user=user
        )
    )

    return (
        user,
        passenger,
    )


def create_driver_vehicle(
    *,
    username,
    current_node,
    mode=Vehicle.RideMode.IDLE,
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

    vehicle = Vehicle.objects.create(
        driver=driver,

        capacity=4,

        is_available=True,

        ride_mode=mode,

        current_node=current_node,
    )

    return (
        user,
        driver,
        vehicle,
    )


def create_shared_request(
    *,
    passenger,
    pickup,
    destination,
):
    return RideRequest.objects.create(
        passenger=passenger,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        passenger_count=1,

        pickup_node=pickup,

        destination_node=destination,

        status=(
            RideRequest.Status.PENDING
        ),
    )


def create_active_shared_ride(
    *,
    vehicle,
    passenger,
    pickup,
    destination,
    ride_status=Ride.Status.ACCEPTED,
):
    """
    Shared Ride ساده برای تست Driver API.

    Pickup = pending
    Dropoff = pending
    """

    ride_request = (
        RideRequest.objects.create(
            passenger=passenger,

            ride_type=(
                RideRequest.RideType.SHARED
            ),

            passenger_count=1,

            pickup_node=pickup,

            destination_node=destination,

            status=(
                RideRequest.Status.ASSIGNED
            ),
        )
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

        total_estimated_time_minutes=4,

        total_estimated_distance_km=2.0,
    )

    pickup_stop = (
        RouteStop.objects.create(
            route=route,

            ride_passenger=(
                ride_passenger
            ),

            node=pickup,

            stop_type=(
                RouteStop.StopType.PICKUP
            ),

            sequence_number=1,

            estimated_arrival_minutes=2,

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

            node=destination,

            stop_type=(
                RouteStop.StopType.DROPOFF
            ),

            sequence_number=2,

            estimated_arrival_minutes=4,

            status=(
                RouteStop.Status.PENDING
            ),
        )
    )

    return (
        ride_request,
        ride,
        route,
        pickup_stop,
        dropoff_stop,
    )


# =========================================================
# 1. Passenger Can Get Shared Taxi Options
# =========================================================

def test_passenger_can_get_shared_taxi_options():

    (
        n1,
        n2,
        _,
        n4,
    ) = create_network()

    (
        passenger_user,
        passenger,
    ) = create_passenger(
        "passenger_options"
    )

    (
        _,
        _,
        vehicle,
    ) = create_driver_vehicle(
        username="driver_options",
        current_node=n1,
    )

    ride_request = (
        create_shared_request(
            passenger=passenger,
            pickup=n2,
            destination=n4,
        )
    )

    client = APIClient()

    client.force_authenticate(
        user=passenger_user
    )

    response = client.get(
        (
            f"/api/assignment/"
            f"ride-requests/"
            f"{ride_request.id}/"
            f"shared-options/"
        )
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["ride_request_id"]
        == ride_request.id
    )

    assert data["count"] == 1

    assert len(
        data["options"]
    ) == 1

    option = data["options"][0]

    assert (
        option["vehicle_id"]
        == vehicle.id
    )

    assert (
        option["rank"]
        == 1
    )

    assert (
        option["pickup_eta_minutes"]
        == 2
    )

    assert (
        len(
            option["proposed_route"]
        )
        == 2
    )


# =========================================================
# 2. Passenger Cannot Access Another Passenger Request
# =========================================================

def test_passenger_cannot_access_another_passenger_request():

    (
        _,
        n2,
        _,
        n4,
    ) = create_network()

    (
        user_a,
        _,
    ) = create_passenger(
        "passenger_a"
    )

    (
        _,
        passenger_b,
    ) = create_passenger(
        "passenger_b"
    )

    request_b = (
        create_shared_request(
            passenger=passenger_b,
            pickup=n2,
            destination=n4,
        )
    )

    client = APIClient()

    client.force_authenticate(
        user=user_a
    )

    response = client.get(
        (
            f"/api/assignment/"
            f"ride-requests/"
            f"{request_b.id}/"
            f"shared-options/"
        )
    )

    assert (
        response.status_code
        == 404
    )


# =========================================================
# 3. Passenger Can Create Shared Hold
# =========================================================

def test_passenger_can_create_shared_hold():

    (
        n1,
        n2,
        _,
        n4,
    ) = create_network()

    (
        passenger_user,
        passenger,
    ) = create_passenger(
        "passenger_hold_api"
    )

    (
        _,
        _,
        vehicle,
    ) = create_driver_vehicle(
        username="driver_hold_api",
        current_node=n1,
    )

    ride_request = (
        create_shared_request(
            passenger=passenger,
            pickup=n2,
            destination=n4,
        )
    )

    client = APIClient()

    client.force_authenticate(
        user=passenger_user
    )

    response = client.post(
        (
            f"/api/assignment/"
            f"ride-requests/"
            f"{ride_request.id}/"
            f"shared-hold/"
        ),
        {
            "vehicle_id": (
                vehicle.id
            )
        },
        format="json",
    )

    assert (
        response.status_code
        == 201
    )

    data = response.json()

    hold = TaxiHold.objects.get(
        pk=data["hold_id"]
    )

    assert (
        hold.status
        == TaxiHold.Status.ACTIVE
    )

    assert (
        hold.vehicle_id
        == vehicle.id
    )

    assert (
        hold.ride_request_id
        == ride_request.id
    )

    # Hold is not final assignment.
    ride_request.refresh_from_db()

    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )


# =========================================================
# 4. Passenger Can Confirm Shared Hold
# =========================================================

def test_passenger_can_confirm_shared_hold():

    (
        n1,
        n2,
        _,
        n4,
    ) = create_network()

    (
        passenger_user,
        passenger,
    ) = create_passenger(
        "passenger_confirm_api"
    )

    (
        _,
        _,
        vehicle,
    ) = create_driver_vehicle(
        username="driver_confirm_api",
        current_node=n1,
    )

    ride_request = (
        create_shared_request(
            passenger=passenger,
            pickup=n2,
            destination=n4,
        )
    )

    client = APIClient()

    client.force_authenticate(
        user=passenger_user
    )

    # -----------------------------------------------------
    # Create Hold
    # -----------------------------------------------------

    hold_response = client.post(
        (
            f"/api/assignment/"
            f"ride-requests/"
            f"{ride_request.id}/"
            f"shared-hold/"
        ),
        {
            "vehicle_id": (
                vehicle.id
            )
        },
        format="json",
    )

    assert (
        hold_response.status_code
        == 201
    )

    hold_id = (
        hold_response.json()[
            "hold_id"
        ]
    )

    # -----------------------------------------------------
    # Confirm
    # -----------------------------------------------------

    response = client.post(
        (
            f"/api/assignment/"
            f"shared-holds/"
            f"{hold_id}/confirm/"
        ),
        {},
        format="json",
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["hold_status"]
        == TaxiHold.Status.CONFIRMED
    )

    assert data["ride_id"] is not None

    assert (
        data["ride_passenger_id"]
        is not None
    )

    assert (
        data["route_id"]
        is not None
    )

    assert (
        data["route_revision"]
        == 1
    )

    # -----------------------------------------------------
    # DB State
    # -----------------------------------------------------

    ride_request.refresh_from_db()
    vehicle.refresh_from_db()

    assert (
        ride_request.status
        == RideRequest.Status.ASSIGNED
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.SHARED
    )

    assert Ride.objects.count() == 1

    assert (
        RidePassenger.objects.count()
        == 1
    )

    assert Route.objects.count() == 1

    assert (
        RouteStop.objects.count()
        == 2
    )


# =========================================================
# 5. Passenger Can Release Shared Hold
# =========================================================

def test_passenger_can_release_shared_hold():

    (
        n1,
        n2,
        _,
        n4,
    ) = create_network()

    (
        passenger_user,
        passenger,
    ) = create_passenger(
        "passenger_release_api"
    )

    (
        _,
        _,
        vehicle,
    ) = create_driver_vehicle(
        username="driver_release_api",
        current_node=n1,
    )

    ride_request = (
        create_shared_request(
            passenger=passenger,
            pickup=n2,
            destination=n4,
        )
    )

    client = APIClient()

    client.force_authenticate(
        user=passenger_user
    )

    hold_response = client.post(
        (
            f"/api/assignment/"
            f"ride-requests/"
            f"{ride_request.id}/"
            f"shared-hold/"
        ),
        {
            "vehicle_id": (
                vehicle.id
            )
        },
        format="json",
    )

    assert (
        hold_response.status_code
        == 201
    )

    hold_id = (
        hold_response.json()[
            "hold_id"
        ]
    )

    response = client.post(
        (
            f"/api/assignment/"
            f"shared-holds/"
            f"{hold_id}/release/"
        ),
        {},
        format="json",
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["status"]
        == TaxiHold.Status.RELEASED
    )

    hold = TaxiHold.objects.get(
        pk=hold_id
    )

    assert (
        hold.status
        == TaxiHold.Status.RELEASED
    )

    ride_request.refresh_from_db()

    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )

    assert Ride.objects.count() == 0


# =========================================================
# 6. Driver Can Read Active Shared Ride
# =========================================================

def test_driver_can_get_active_shared_ride():

    (
        n1,
        n2,
        _,
        n4,
    ) = create_network()

    (
        driver_user,
        _,
        vehicle,
    ) = create_driver_vehicle(
        username="driver_active_api",
        current_node=n1,
        mode=Vehicle.RideMode.SHARED,
    )

    (
        _,
        passenger,
    ) = create_passenger(
        "passenger_active_api"
    )

    (
        _,
        ride,
        route,
        pickup_stop,
        dropoff_stop,
    ) = (
        create_active_shared_ride(
            vehicle=vehicle,
            passenger=passenger,
            pickup=n2,
            destination=n4,
        )
    )

    client = APIClient()

    client.force_authenticate(
        user=driver_user
    )

    response = client.get(
        (
            "/api/assignment/"
            "driver/shared-ride/active/"
        )
    )

    assert response.status_code == 200

    data = response.json()[
        "active_shared_ride"
    ]

    assert data is not None

    assert (
        data["ride_id"]
        == ride.id
    )

    assert (
        data["route"]["id"]
        == route.id
    )

    assert (
        data["route"]["revision"]
        == 1
    )

    assert len(
        data["stops"]
    ) == 2

    assert (
        data["stops"][0]["id"]
        == pickup_stop.id
    )

    assert (
        data["stops"][1]["id"]
        == dropoff_stop.id
    )

    assert (
        data["stops"][0][
            "stop_type"
        ]
        == RouteStop.StopType.PICKUP
    )


# =========================================================
# 7. Driver Move-Next Uses Shared Movement Engine
# =========================================================

def test_driver_can_move_shared_taxi_one_step():

    (
        n1,
        n2,
        _,
        n4,
    ) = create_network()

    (
        driver_user,
        _,
        vehicle,
    ) = create_driver_vehicle(
        username="driver_move_api",
        current_node=n1,
        mode=Vehicle.RideMode.SHARED,
    )

    (
        _,
        passenger,
    ) = create_passenger(
        "passenger_move_api"
    )

    (
        _,
        ride,
        _,
        pickup_stop,
        dropoff_stop,
    ) = (
        create_active_shared_ride(
            vehicle=vehicle,
            passenger=passenger,
            pickup=n2,
            destination=n4,
            ride_status=(
                Ride.Status.ACCEPTED
            ),
        )
    )

    client = APIClient()

    client.force_authenticate(
        user=driver_user
    )

    response = client.post(
        (
            "/api/assignment/"
            "driver/shared-ride/move-next/"
        ),
        {},
        format="json",
    )

    assert response.status_code == 200

    data = response.json()

    # N1 → N2
    # N2 is Pickup,
    # so movement + pickup completion
    # happens in same call.

    assert (
        data["current_node_id"]
        == n2.id
    )

    assert (
        data["completed_stop_id"]
        == pickup_stop.id
    )

    assert (
        data["next_stop_id"]
        == dropoff_stop.id
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
        ride.status
        == Ride.Status.IN_PROGRESS
    )