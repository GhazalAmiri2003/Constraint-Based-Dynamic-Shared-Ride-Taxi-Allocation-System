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
    RidePassenger,
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
        "confirm_passenger"
    )


@pytest.fixture
def second_passenger():
    return create_passenger(
        "confirm_passenger_two"
    )


@pytest.fixture
def network():
    pickup = RoadNode.objects.create(
        name="CONFIRM_PICKUP",
        x=0,
        y=0,
    )

    destination = RoadNode.objects.create(
        name="CONFIRM_DESTINATION",
        x=5,
        y=0,
    )

    taxi_node = RoadNode.objects.create(
        name="CONFIRM_TAXI_NODE",
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
        "confirm_driver",
        network["taxi_node"],
    )


# =========================================================
# 1. Hold does not immediately assign Ride
# =========================================================

@pytest.mark.django_db
def test_creating_hold_does_not_assign_ride_immediately(
    api_client,
    passenger,
    ride_request,
    vehicle,
):
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

    ride_request.refresh_from_db()
    vehicle.refresh_from_db()


    # Hold ساخته شده
    hold = TaxiHold.objects.get(
        pk=response.data["hold_id"]
    )

    assert (
        hold.status
        == TaxiHold.Status.ACTIVE
    )


    # هنوز Assignment انجام نشده
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
# 2. Active Hold can be confirmed
# =========================================================

@pytest.mark.django_db
def test_passenger_can_confirm_active_hold(
    api_client,
    passenger,
    ride_request,
    vehicle,
):
    authenticate_client(
        api_client,
        passenger,
    )


    # ---------------------------------
    # Create Hold
    # ---------------------------------

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


    # ---------------------------------
    # Confirm Hold
    # ---------------------------------

    confirm_response = api_client.post(
        "/api/assignment/"
        f"holds/{hold_id}/confirm/"
    )


    assert confirm_response.status_code == 200

    assert (
        confirm_response.data["hold_status"]
        == "CONFIRMED"
    )

    assert (
        confirm_response.data["ride_status"]
        == "ASSIGNED"
    )

    assert (
        confirm_response.data["vehicle_id"]
        == vehicle.id
    )

    assert (
        confirm_response.data["ride_request_id"]
        == ride_request.id
    )


    # ---------------------------------
    # Refresh DB
    # ---------------------------------

    hold = TaxiHold.objects.get(
        pk=hold_id
    )

    ride_request.refresh_from_db()
    vehicle.refresh_from_db()


    # Hold Confirmed
    assert (
        hold.status
        == TaxiHold.Status.CONFIRMED
    )


    # RideRequest Assigned
    assert (
        ride_request.status
        == RideRequest.Status.ASSIGNED
    )


    # Taxi enters PRIVATE mode
    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.PRIVATE
    )


    # دقیقاً یک Ride ساخته شده
    assert Ride.objects.count() == 1


    ride = Ride.objects.get()

    assert (
        ride.status
        == Ride.Status.ASSIGNED
    )

    assert (
        ride.vehicle_id
        == vehicle.id
    )


    # RideRequest به Ride وصل شده
    assert RidePassenger.objects.filter(
        ride=ride,
        ride_request=ride_request,
    ).exists()


# =========================================================
# 3. Hold cannot be confirmed twice
# =========================================================

@pytest.mark.django_db
def test_hold_cannot_be_confirmed_twice(
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


    # Confirm اول
    first_response = api_client.post(
        "/api/assignment/"
        f"holds/{hold_id}/confirm/"
    )

    assert first_response.status_code == 200


    # Confirm دوم
    second_response = api_client.post(
        "/api/assignment/"
        f"holds/{hold_id}/confirm/"
    )

    assert second_response.status_code == 400


    hold = TaxiHold.objects.get(
        pk=hold_id
    )

    assert (
        hold.status
        == TaxiHold.Status.CONFIRMED
    )


    # نباید Ride دوم ساخته شود
    assert Ride.objects.count() == 1


# =========================================================
# 4. Expired Hold cannot be confirmed
# =========================================================

@pytest.mark.django_db
def test_expired_hold_cannot_be_confirmed(
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


    # Hold را منقضی می‌کنیم
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
        f"holds/{hold_id}/confirm/"
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


    # باید EXPIRED ذخیره شده باشد
    assert (
        hold.status
        == TaxiHold.Status.EXPIRED
    )


    # Assignment نباید انجام شده باشد
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
# 5. Another passenger cannot confirm hold
# =========================================================

@pytest.mark.django_db
def test_other_passenger_cannot_confirm_hold(
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

    assert hold_response.status_code == 201

    hold_id = hold_response.data["hold_id"]


    # Passenger دوم Login می‌کند
    api_client.credentials()

    authenticate_client(
        api_client,
        second_passenger,
    )


    response = api_client.post(
        "/api/assignment/"
        f"holds/{hold_id}/confirm/"
    )


    # Hold متعلق به Passenger دوم نیست
    assert response.status_code == 404


    hold = TaxiHold.objects.get(
        pk=hold_id
    )

    ride_request.refresh_from_db()
    vehicle.refresh_from_db()


    # Hold هنوز Active
    assert (
        hold.status
        == TaxiHold.Status.ACTIVE
    )


    # هیچ Assignment انجام نشده
    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )

    assert Ride.objects.count() == 0