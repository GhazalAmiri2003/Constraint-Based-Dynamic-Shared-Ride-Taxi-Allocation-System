import pytest

from django.contrib.auth.models import User
from django.test import override_settings

from rest_framework.authtoken.models import Token
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
    RideRequest,
)
from road_network.models import (
    RoadEdge,
    RoadNode,
)


# =========================================================
# Helpers
# =========================================================

def authenticate_client(
    api_client,
    user,
):
    token = Token.objects.create(
        user=user
    )

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Token {token.key}"
    )


def create_driver_with_vehicle(
    username,
    current_node,
    capacity=4,
    availability_status=(
        DriverProfile.AvailabilityStatus.ONLINE
    ),
    is_available=True,
    ride_mode=Vehicle.RideMode.IDLE,
):
    user = User.objects.create_user(
        username=username,
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.DRIVER,
    )

    driver_profile = DriverProfile.objects.create(
        user=user,
        availability_status=availability_status,
    )

    return Vehicle.objects.create(
        driver=driver_profile,
        capacity=capacity,
        is_available=is_available,
        ride_mode=ride_mode,
        current_node=current_node,
    )


# =========================================================
# Fixtures
# =========================================================

@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def passenger():
    user = User.objects.create_user(
        username="selection_passenger",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.PASSENGER,
    )

    PassengerProfile.objects.create(
        user=user,
    )

    return user


@pytest.fixture
def network():
    pickup = RoadNode.objects.create(
        name="SELECTION_PICKUP",
        x=0,
        y=0,
    )

    destination = RoadNode.objects.create(
        name="SELECTION_DESTINATION",
        x=5,
        y=0,
    )

    taxi_node = RoadNode.objects.create(
        name="SELECTION_TAXI_NODE",
        x=1,
        y=0,
    )

    # Taxi → Pickup
    RoadEdge.objects.create(
        from_node=taxi_node,
        to_node=pickup,
        distance_km=1.0,
        travel_time_minutes=2,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    # Pickup → Destination
    RoadEdge.objects.create(
        from_node=pickup,
        to_node=destination,
        distance_km=5.0,
        travel_time_minutes=8,
        road_type=RoadEdge.RoadType.MAIN,
        is_bidirectional=True,
    )

    return {
        "pickup": pickup,
        "destination": destination,
        "taxi_node": taxi_node,
    }


@pytest.fixture
def ride_request(
    passenger,
    network,
):
    return RideRequest.objects.create(
        passenger=passenger.passenger_profile,
        ride_type=RideRequest.RideType.PRIVATE,
        passenger_count=2,
        pickup_node=network["pickup"],
        destination_node=network["destination"],
        status=RideRequest.Status.PENDING,
    )


# =========================================================
# Hold Selection Tests
# =========================================================

@pytest.mark.django_db
def test_passenger_can_hold_feasible_taxi(
    api_client,
    passenger,
    network,
    ride_request,
):
    vehicle = create_driver_with_vehicle(
        username="selection_driver",
        current_node=network["taxi_node"],
    )

    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.post(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "hold-taxi/",
        {
            "vehicle_id": vehicle.id
        },
        format="json",
    )

    assert response.status_code == 201

    assert response.data["status"] == "ACTIVE"

    assert (
        response.data["vehicle_id"]
        == vehicle.id
    )

    ride_request.refresh_from_db()
    vehicle.refresh_from_db()

    # Hold هنوز Assignment نیست
    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )

    assert Ride.objects.count() == 0

    assert TaxiHold.objects.filter(
        ride_request=ride_request,
        vehicle=vehicle,
        status=TaxiHold.Status.ACTIVE,
    ).exists()


@pytest.mark.django_db
def test_busy_taxi_cannot_be_held(
    api_client,
    passenger,
    network,
    ride_request,
):
    vehicle = create_driver_with_vehicle(
        username="busy_selection_driver",
        current_node=network["taxi_node"],
        ride_mode=Vehicle.RideMode.PRIVATE,
    )

    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.post(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "hold-taxi/",
        {
            "vehicle_id": vehicle.id
        },
        format="json",
    )

    assert response.status_code == 400

    assert TaxiHold.objects.count() == 0
    assert Ride.objects.count() == 0


@pytest.mark.django_db
def test_offline_taxi_cannot_be_held(
    api_client,
    passenger,
    network,
    ride_request,
):
    vehicle = create_driver_with_vehicle(
        username="offline_selection_driver",
        current_node=network["taxi_node"],
        availability_status=(
            DriverProfile
            .AvailabilityStatus
            .OFFLINE
        ),
    )

    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.post(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "hold-taxi/",
        {
            "vehicle_id": vehicle.id
        },
        format="json",
    )

    assert response.status_code == 400

    assert TaxiHold.objects.count() == 0
    assert Ride.objects.count() == 0


@pytest.mark.django_db
def test_taxi_with_insufficient_capacity_cannot_be_held(
    api_client,
    passenger,
    network,
    ride_request,
):
    vehicle = create_driver_with_vehicle(
        username="small_selection_driver",
        current_node=network["taxi_node"],
        capacity=1,
    )

    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.post(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "hold-taxi/",
        {
            "vehicle_id": vehicle.id
        },
        format="json",
    )

    assert response.status_code == 400

    assert TaxiHold.objects.count() == 0
    assert Ride.objects.count() == 0


@override_settings(
    MAX_PRIVATE_PICKUP_WAIT_MINUTES=10
)
@pytest.mark.django_db
def test_taxi_exceeding_pickup_wait_cannot_be_held(
    api_client,
    passenger,
    network,
    ride_request,
):
    slow_node = RoadNode.objects.create(
        name="SELECTION_SLOW_NODE",
        x=40,
        y=40,
    )

    # Taxi → Pickup = 11 min
    RoadEdge.objects.create(
        from_node=slow_node,
        to_node=network["pickup"],
        distance_km=5.0,
        travel_time_minutes=11,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    vehicle = create_driver_with_vehicle(
        username="slow_selection_driver",
        current_node=slow_node,
    )

    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.post(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "hold-taxi/",
        {
            "vehicle_id": vehicle.id
        },
        format="json",
    )

    assert response.status_code == 400

    assert (
        "maximum pickup wait"
        in response.data["detail"].lower()
    )

    assert TaxiHold.objects.count() == 0
    assert Ride.objects.count() == 0