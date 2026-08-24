import pytest

from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from fleet.models import Vehicle
from rides.models import Ride, RideRequest
from rides.services import assign_private_ride
from road_network.models import RoadNode


@pytest.fixture
def api_client():
    return APIClient()


def authenticate(api_client, user):
    # Token Authentication
    token = Token.objects.create(user=user)

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Token {token.key}"
    )


@pytest.fixture
def passenger():
    # Passenger تستی
    user = User.objects.create_user(
        username="cancel_passenger",
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
def driver():
    # Driver آماده Assignment
    user = User.objects.create_user(
        username="cancel_driver",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.DRIVER,
    )

    profile = DriverProfile.objects.create(
        user=user,
        availability_status=DriverProfile.AvailabilityStatus.ONLINE,
    )

    Vehicle.objects.create(
        driver=profile,
        capacity=4,
        is_available=True,
        ride_mode=Vehicle.RideMode.IDLE,
    )

    return user


@pytest.fixture
def nodes():
    # Nodeهای تست
    n1 = RoadNode.objects.create(
        name="N1",
        x=10,
        y=10,
    )

    n2 = RoadNode.objects.create(
        name="N2",
        x=20,
        y=20,
    )

    return n1, n2


@pytest.fixture
def ride_request(passenger, nodes):
    n1, n2 = nodes

    return RideRequest.objects.create(
        passenger=passenger.passenger_profile,
        ride_type=RideRequest.RideType.PRIVATE,
        passenger_count=1,
        pickup_node=n1,
        destination_node=n2,
    )


@pytest.mark.django_db
def test_pending_request_can_be_cancelled(
    api_client,
    passenger,
    ride_request,
):
    authenticate(api_client, passenger)

    response = api_client.post(
        f"/api/ride-requests/{ride_request.id}/cancel/"
    )

    assert response.status_code == 200

    ride_request.refresh_from_db()

    assert ride_request.status == RideRequest.Status.CANCELLED


@pytest.mark.django_db
def test_assigned_private_ride_can_be_cancelled_before_pickup(
    api_client,
    passenger,
    driver,
    ride_request,
):
    vehicle = driver.driver_profile.vehicle

    ride = assign_private_ride(
        ride_request,
        vehicle,
    )

    authenticate(api_client, passenger)

    response = api_client.post(
        f"/api/ride-requests/{ride_request.id}/cancel/"
    )

    assert response.status_code == 200

    ride.refresh_from_db()
    ride_request.refresh_from_db()
    vehicle.refresh_from_db()

    # همه Stateها باید Sync باشند
    assert ride.status == Ride.Status.CANCELLED
    assert ride_request.status == RideRequest.Status.CANCELLED
    assert vehicle.ride_mode == Vehicle.RideMode.IDLE


@pytest.mark.django_db
def test_accepted_ride_can_be_cancelled_before_pickup(
    api_client,
    passenger,
    driver,
    ride_request,
):
    vehicle = driver.driver_profile.vehicle

    ride = assign_private_ride(
        ride_request,
        vehicle,
    )

    ride.status = Ride.Status.ACCEPTED
    ride.save()

    authenticate(api_client, passenger)

    response = api_client.post(
        f"/api/ride-requests/{ride_request.id}/cancel/"
    )

    assert response.status_code == 200

    ride.refresh_from_db()
    vehicle.refresh_from_db()

    assert ride.status == Ride.Status.CANCELLED
    assert vehicle.ride_mode == Vehicle.RideMode.IDLE


@pytest.mark.django_db
def test_in_progress_ride_cannot_be_cancelled(
    api_client,
    passenger,
    driver,
    ride_request,
):
    vehicle = driver.driver_profile.vehicle

    ride = assign_private_ride(
        ride_request,
        vehicle,
    )

    ride.status = Ride.Status.IN_PROGRESS
    ride.save()

    authenticate(api_client, passenger)

    response = api_client.post(
        f"/api/ride-requests/{ride_request.id}/cancel/"
    )

    assert response.status_code == 400

    ride.refresh_from_db()
    ride_request.refresh_from_db()
    vehicle.refresh_from_db()

    # Stateها نباید تغییر کنند
    assert ride.status == Ride.Status.IN_PROGRESS
    assert ride_request.status == RideRequest.Status.ASSIGNED
    assert vehicle.ride_mode == Vehicle.RideMode.PRIVATE


@pytest.mark.django_db
def test_cancelled_request_cannot_be_cancelled_again(
    api_client,
    passenger,
    ride_request,
):
    ride_request.status = RideRequest.Status.CANCELLED
    ride_request.save()

    authenticate(api_client, passenger)

    response = api_client.post(
        f"/api/ride-requests/{ride_request.id}/cancel/"
    )

    assert response.status_code == 400