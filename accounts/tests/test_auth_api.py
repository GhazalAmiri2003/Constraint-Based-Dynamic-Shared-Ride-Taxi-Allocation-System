import pytest

from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
def test_passenger_registration(api_client):
    payload = {
        "username": "passenger_test",
        "email": "passenger_test@example.com",
        "password": "StrongPass123!",
        "first_name": "Test",
        "last_name": "Passenger",
    }

    response = api_client.post(
        "/api/auth/register/passenger/",
        payload,
        format="json",
    )

    assert response.status_code == 201

    user = User.objects.get(username="passenger_test")

    assert user.email == "passenger_test@example.com"

    # Password must be hashed, not stored directly.
    assert user.password != "StrongPass123!"
    assert user.check_password("StrongPass123!")

    assert user.profile.role == UserProfile.Role.PASSENGER

    assert PassengerProfile.objects.filter(
        user=user
    ).exists()

    assert not DriverProfile.objects.filter(
        user=user
    ).exists()

    assert Token.objects.filter(
        user=user
    ).exists()

    assert response.data["user"]["role"] == "PASSENGER"

    assert "password" not in response.data



@pytest.mark.django_db
def test_driver_registration(api_client):
    payload = {
        "username": "driver_test",
        "email": "driver_test@example.com",
        "password": "StrongPass123!",
        "first_name": "Test",
        "last_name": "Driver",
    }

    response = api_client.post(
        "/api/auth/register/driver/",
        payload,
        format="json",
    )

    assert response.status_code == 201

    user = User.objects.get(username="driver_test")

    assert user.profile.role == UserProfile.Role.DRIVER

    assert DriverProfile.objects.filter(
        user=user
    ).exists()

    assert not PassengerProfile.objects.filter(
        user=user
    ).exists()

    assert (
        user.driver_profile.availability_status
        == DriverProfile.AvailabilityStatus.OFFLINE
    )

    assert Token.objects.filter(
        user=user
    ).exists()

    assert response.data["user"]["role"] == "DRIVER"

@pytest.mark.django_db
def test_duplicate_username_is_rejected(api_client):
    User.objects.create_user(
        username="existing_user",
        email="first@example.com",
        password="StrongPass123!",
    )

    payload = {
        "username": "existing_user",
        "email": "second@example.com",
        "password": "StrongPass123!",
    }

    response = api_client.post(
        "/api/auth/register/passenger/",
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert "username" in response.data


@pytest.mark.django_db
def test_duplicate_email_is_rejected(api_client):
    User.objects.create_user(
        username="first_user",
        email="same@example.com",
        password="StrongPass123!",
    )

    payload = {
        "username": "second_user",
        "email": "same@example.com",
        "password": "StrongPass123!",
    }

    response = api_client.post(
        "/api/auth/register/passenger/",
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert "email" in response.data



@pytest.mark.django_db
def test_login_success(api_client):
    user = User.objects.create_user(
        username="login_test",
        email="login@example.com",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.PASSENGER,
    )

    PassengerProfile.objects.create(
        user=user,
    )

    response = api_client.post(
        "/api/auth/login/",
        {
            "username": "login_test",
            "password": "StrongPass123!",
        },
        format="json",
    )

    assert response.status_code == 200

    assert "token" in response.data

    assert response.data["user"]["username"] == "login_test"
    assert response.data["user"]["role"] == "PASSENGER"




@pytest.mark.django_db
def test_login_with_wrong_password_is_rejected(api_client):
    User.objects.create_user(
        username="login_test",
        email="login@example.com",
        password="StrongPass123!",
    )

    response = api_client.post(
        "/api/auth/login/",
        {
            "username": "login_test",
            "password": "WrongPassword!",
        },
        format="json",
    )

    assert response.status_code == 401



@pytest.mark.django_db
def test_me_requires_authentication(api_client):
    response = api_client.get(
        "/api/auth/me/"
    )

    assert response.status_code == 401




@pytest.mark.django_db
def test_authenticated_user_can_access_me(api_client):
    user = User.objects.create_user(
        username="me_test",
        email="me@example.com",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.PASSENGER,
    )

    PassengerProfile.objects.create(
        user=user,
    )

    token = Token.objects.create(user=user)

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Token {token.key}"
    )

    response = api_client.get(
        "/api/auth/me/"
    )

    assert response.status_code == 200

    assert response.data["username"] == "me_test"
    assert response.data["role"] == "PASSENGER"


@pytest.mark.django_db
def test_logout_deletes_token(api_client):
    user = User.objects.create_user(
        username="logout_test",
        email="logout@example.com",
        password="StrongPass123!",
    )

    token = Token.objects.create(user=user)

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Token {token.key}"
    )

    response = api_client.post(
        "/api/auth/logout/"
    )

    assert response.status_code == 200

    assert not Token.objects.filter(
        user=user
    ).exists()