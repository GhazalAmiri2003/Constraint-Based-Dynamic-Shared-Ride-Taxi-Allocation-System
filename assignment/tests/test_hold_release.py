from datetime import timedelta

import pytest

from django.contrib.auth.models import User
from django.utils import timezone

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

    PassengerProfile.objects.create(
        user=user,
    )

    return user


def create_driver_with_vehicle(
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

    driver_profile = DriverProfile.objects.create(
        user=user,
        availability_status=(
            DriverProfile
            .AvailabilityStatus
            .ONLINE
        ),
    )

    return Vehicle.objects.create(
        driver=driver_profile,
        capacity=4,
        is_available=True,
        ride_mode=Vehicle.RideMode.IDLE,
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
    return create_passenger(
        "release_passenger"
    )


@pytest.fixture
def second_passenger():
    return create_passenger(
        "release_second_passenger"
    )


@pytest.fixture
def network():
    pickup = RoadNode.objects.create(
        name="RELEASE_PICKUP",
        x=0,
        y=0,
    )

    destination = RoadNode.objects.create(
        name="RELEASE_DESTINATION",
        x=5,
        y=0,
    )

    taxi_node = RoadNode.objects.create(
        name="RELEASE_TAXI_NODE",
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


@pytest.fixture
def vehicle(
    network,
):
    return create_driver_with_vehicle(
        "release_driver",
        network["taxi_node"],
    )


# =========================================================
# 1. ACTIVE → RELEASED
# =========================================================

@pytest.mark.django_db
def test_passenger_can_release_active_hold(
    api_client,
    passenger,
    ride_request,
    vehicle,
):
    authenticate_client(
        api_client,
        passenger,
    )

    # Hold
    hold_response = api_client.post(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "hold-taxi/",
        {
            "vehicle_id": vehicle.id
        },
        format="json",
    )

    assert hold_response.status_code == 201

    hold_id = hold_response.data["hold_id"]

    # Release
    response = api_client.post(
        "/api/assignment/"
        f"holds/{hold_id}/release/"
    )

    assert response.status_code == 200
    assert response.data["status"] == "RELEASED"

    hold = TaxiHold.objects.get(
        pk=hold_id
    )

    ride_request.refresh_from_db()
    vehicle.refresh_from_db()

    assert (
        hold.status
        == TaxiHold.Status.RELEASED
    )

    # Release نباید Assignment ایجاد کند
    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )

    assert Ride.objects.count() == 0


# =========================================================
# 2. Other Passenger → 404
# =========================================================

@pytest.mark.django_db
def test_other_passenger_cannot_release_hold(
    api_client,
    passenger,
    second_passenger,
    ride_request,
    vehicle,
):
    # Passenger اصلی Hold می‌سازد
    authenticate_client(
        api_client,
        passenger,
    )

    hold_response = api_client.post(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "hold-taxi/",
        {
            "vehicle_id": vehicle.id
        },
        format="json",
    )

    hold_id = hold_response.data["hold_id"]

    # Passenger دوم
    api_client.credentials()

    authenticate_client(
        api_client,
        second_passenger,
    )

    response = api_client.post(
        "/api/assignment/"
        f"holds/{hold_id}/release/"
    )

    assert response.status_code == 404

    hold = TaxiHold.objects.get(
        pk=hold_id
    )

    assert (
        hold.status
        == TaxiHold.Status.ACTIVE
    )


# =========================================================
# 3. CONFIRMED Hold cannot be released
# =========================================================

@pytest.mark.django_db
def test_confirmed_hold_cannot_be_released(
    api_client,
    passenger,
    ride_request,
    vehicle,
):
    authenticate_client(
        api_client,
        passenger,
    )

    # Create Hold
    hold_response = api_client.post(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "hold-taxi/",
        {
            "vehicle_id": vehicle.id
        },
        format="json",
    )

    hold_id = hold_response.data["hold_id"]

    # Confirm
    confirm_response = api_client.post(
        "/api/assignment/"
        f"holds/{hold_id}/confirm/"
    )

    assert confirm_response.status_code == 200

    # حالا Release نباید ممکن باشد
    response = api_client.post(
        "/api/assignment/"
        f"holds/{hold_id}/release/"
    )

    assert response.status_code == 400

    hold = TaxiHold.objects.get(
        pk=hold_id
    )

    assert (
        hold.status
        == TaxiHold.Status.CONFIRMED
    )

    # فقط همان Ride قبلی وجود دارد
    assert Ride.objects.count() == 1


# =========================================================
# 4. Expired Hold → EXPIRED + 400
# =========================================================

@pytest.mark.django_db
def test_expired_hold_cannot_be_released(
    api_client,
    passenger,
    ride_request,
    vehicle,
):
    authenticate_client(
        api_client,
        passenger,
    )

    hold_response = api_client.post(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "hold-taxi/",
        {
            "vehicle_id": vehicle.id
        },
        format="json",
    )

    hold_id = hold_response.data["hold_id"]

    # زمان را به گذشته می‌بریم
    TaxiHold.objects.filter(
        pk=hold_id
    ).update(
        expires_at=(
            timezone.now()
            - timedelta(seconds=1)
        )
    )

    response = api_client.post(
        "/api/assignment/"
        f"holds/{hold_id}/release/"
    )

    assert response.status_code == 400

    assert (
        "expired"
        in response.data["detail"].lower()
    )

    hold = TaxiHold.objects.get(
        pk=hold_id
    )

    ride_request.refresh_from_db()
    vehicle.refresh_from_db()

    # EXPIRED باید واقعاً در DB مانده باشد
    assert (
        hold.status
        == TaxiHold.Status.EXPIRED
    )

    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )

    assert Ride.objects.count() == 0