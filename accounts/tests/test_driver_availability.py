import pytest

from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import DriverProfile, PassengerProfile, UserProfile
from fleet.models import Vehicle


@pytest.fixture
def api_client():
    # Client تست API
    return APIClient()


def authenticate(api_client, user):
    # Token Authentication
    token = Token.objects.create(user=user)

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Token {token.key}"
    )


@pytest.fixture
def driver():
    # Driver تستی
    user = User.objects.create_user(
        username="availability_driver",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.DRIVER,
    )

    profile = DriverProfile.objects.create(
        user=user,
    )

    Vehicle.objects.create(
        driver=profile,
        capacity=4,
        is_available=True,
        ride_mode=Vehicle.RideMode.IDLE,
    )

    return user


@pytest.mark.django_db
def test_driver_can_go_online(api_client, driver):
    authenticate(api_client, driver)

    response = api_client.patch(
        "/api/driver/availability/",
        {
            "availability_status": "ONLINE"
        },
        format="json",
    )

    assert response.status_code == 200

    driver.driver_profile.refresh_from_db()

    assert (
        driver.driver_profile.availability_status
        == DriverProfile.AvailabilityStatus.ONLINE
    )


@pytest.mark.django_db
def test_idle_driver_can_go_offline(api_client, driver):
    authenticate(api_client, driver)

    driver.driver_profile.availability_status = (
        DriverProfile.AvailabilityStatus.ONLINE
    )
    driver.driver_profile.save()

    response = api_client.patch(
        "/api/driver/availability/",
        {
            "availability_status": "OFFLINE"
        },
        format="json",
    )

    assert response.status_code == 200

    driver.driver_profile.refresh_from_db()

    assert (
        driver.driver_profile.availability_status
        == DriverProfile.AvailabilityStatus.OFFLINE
    )


@pytest.mark.django_db
def test_driver_cannot_go_offline_during_active_ride(
    api_client,
    driver,
):
    authenticate(api_client, driver)

    driver.driver_profile.availability_status = (
        DriverProfile.AvailabilityStatus.ONLINE
    )
    driver.driver_profile.save()

    vehicle = driver.driver_profile.vehicle
    vehicle.ride_mode = Vehicle.RideMode.PRIVATE
    vehicle.save()

    response = api_client.patch(
        "/api/driver/availability/",
        {
            "availability_status": "OFFLINE"
        },
        format="json",
    )

    assert response.status_code == 400

    driver.driver_profile.refresh_from_db()

    # Driver باید Online بماند
    assert (
        driver.driver_profile.availability_status
        == DriverProfile.AvailabilityStatus.ONLINE
    )


@pytest.mark.django_db
def test_invalid_driver_availability_is_rejected(
    api_client,
    driver,
):
    authenticate(api_client, driver)

    response = api_client.patch(
        "/api/driver/availability/",
        {
            "availability_status": "BUSY"
        },
        format="json",
    )

    assert response.status_code == 400