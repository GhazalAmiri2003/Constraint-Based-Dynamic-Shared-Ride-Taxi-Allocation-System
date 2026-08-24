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
from road_network.models import RoadNode


@pytest.fixture
def api_client():
    # Client برای تست API
    return APIClient()


@pytest.fixture
def driver():
    # ساخت راننده تستی
    user = User.objects.create_user(
        username="driver_test",
        email="driver_test@example.com",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.DRIVER,
    )

    DriverProfile.objects.create(
        user=user,
    )

    return user


@pytest.fixture
def passenger():
    # ساخت مسافر تستی
    user = User.objects.create_user(
        username="passenger_test",
        email="passenger_test@example.com",
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
def road_node():
    # موقعیت تستی Taxi
    return RoadNode.objects.create(
        name="VEHICLE_N1",
        x=0,
        y=0,
    )


def authenticate_client(api_client, user):
    # Token Authentication
    token = Token.objects.create(
        user=user,
    )

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Token {token.key}"
    )


@pytest.mark.django_db
def test_driver_can_register_vehicle(api_client, driver):
    authenticate_client(api_client, driver)

    response = api_client.post(
        "/api/vehicles/me/",
        {
            "capacity": 4,
            "is_available": True,
        },
        format="json",
    )

    assert response.status_code == 201

    # Vehicle باید ساخته شده باشد
    assert Vehicle.objects.filter(
        driver=driver.driver_profile
    ).exists()

    vehicle = Vehicle.objects.get(
        driver=driver.driver_profile
    )

    assert vehicle.capacity == 4
    assert vehicle.is_available is True
    assert vehicle.ride_mode == Vehicle.RideMode.IDLE

    # موقعیت اولیه هنوز می‌تواند خالی باشد
    assert vehicle.current_node is None

    assert response.data["driver_username"] == "driver_test"


@pytest.mark.django_db
def test_passenger_cannot_register_vehicle(
    api_client,
    passenger,
):
    authenticate_client(api_client, passenger)

    response = api_client.post(
        "/api/vehicles/me/",
        {
            "capacity": 4,
            "is_available": True,
        },
        format="json",
    )

    # Passenger اجازه ساخت Vehicle ندارد
    assert response.status_code == 403

    assert Vehicle.objects.count() == 0


@pytest.mark.django_db
def test_unauthenticated_user_cannot_register_vehicle(
    api_client,
):
    response = api_client.post(
        "/api/vehicles/me/",
        {
            "capacity": 4,
            "is_available": True,
        },
        format="json",
    )

    # بدون Token اجازه ندارد
    assert response.status_code == 401

    assert Vehicle.objects.count() == 0


@pytest.mark.django_db
def test_vehicle_capacity_above_four_is_rejected(
    api_client,
    driver,
):
    authenticate_client(api_client, driver)

    response = api_client.post(
        "/api/vehicles/me/",
        {
            "capacity": 5,
            "is_available": True,
        },
        format="json",
    )

    assert response.status_code == 400
    assert "capacity" in response.data
    assert Vehicle.objects.count() == 0


@pytest.mark.django_db
def test_vehicle_capacity_zero_is_rejected(
    api_client,
    driver,
):
    authenticate_client(api_client, driver)

    response = api_client.post(
        "/api/vehicles/me/",
        {
            "capacity": 0,
            "is_available": True,
        },
        format="json",
    )

    assert response.status_code == 400
    assert "capacity" in response.data
    assert Vehicle.objects.count() == 0


@pytest.mark.django_db
def test_driver_cannot_register_two_vehicles(
    api_client,
    driver,
):
    authenticate_client(api_client, driver)

    # Vehicle اول
    Vehicle.objects.create(
        driver=driver.driver_profile,
        capacity=4,
        is_available=True,
    )

    # تلاش برای Vehicle دوم
    response = api_client.post(
        "/api/vehicles/me/",
        {
            "capacity": 3,
            "is_available": True,
        },
        format="json",
    )

    assert response.status_code == 400

    assert Vehicle.objects.filter(
        driver=driver.driver_profile
    ).count() == 1


@pytest.mark.django_db
def test_driver_can_get_own_vehicle(
    api_client,
    driver,
):
    authenticate_client(api_client, driver)

    Vehicle.objects.create(
        driver=driver.driver_profile,
        capacity=4,
        is_available=True,
    )

    response = api_client.get(
        "/api/vehicles/me/"
    )

    assert response.status_code == 200

    assert response.data["driver_username"] == "driver_test"
    assert response.data["capacity"] == 4
    assert response.data["ride_mode"] == "IDLE"


@pytest.mark.django_db
def test_get_vehicle_returns_404_when_driver_has_no_vehicle(
    api_client,
    driver,
):
    authenticate_client(api_client, driver)

    response = api_client.get(
        "/api/vehicles/me/"
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_driver_can_change_vehicle_availability(
    api_client,
    driver,
):
    authenticate_client(api_client, driver)

    vehicle = Vehicle.objects.create(
        driver=driver.driver_profile,
        capacity=4,
        is_available=True,
    )

    response = api_client.patch(
        "/api/vehicles/me/availability/",
        {
            "is_available": False,
        },
        format="json",
    )

    assert response.status_code == 200

    vehicle.refresh_from_db()

    assert vehicle.is_available is False
    assert response.data["is_available"] is False


@pytest.mark.django_db
def test_invalid_availability_value_is_rejected(
    api_client,
    driver,
):
    authenticate_client(api_client, driver)

    Vehicle.objects.create(
        driver=driver.driver_profile,
        capacity=4,
        is_available=True,
    )

    response = api_client.patch(
        "/api/vehicles/me/availability/",
        {
            "is_available": "maybe",
        },
        format="json",
    )

    # فقط Boolean معتبر است
    assert response.status_code == 400


@pytest.mark.django_db
def test_vehicle_can_have_current_node(
    driver,
    road_node,
):
    # Taxi می‌تواند روی یک RoadNode قرار داشته باشد
    vehicle = Vehicle.objects.create(
        driver=driver.driver_profile,
        capacity=4,
        is_available=True,
        current_node=road_node,
    )

    vehicle.refresh_from_db()

    assert vehicle.current_node == road_node
    assert vehicle.current_node.name == "VEHICLE_N1"


@pytest.mark.django_db
def test_vehicle_api_returns_current_node(
    api_client,
    driver,
    road_node,
):
    authenticate_client(api_client, driver)

    Vehicle.objects.create(
        driver=driver.driver_profile,
        capacity=4,
        is_available=True,
        current_node=road_node,
    )

    response = api_client.get(
        "/api/vehicles/me/"
    )

    assert response.status_code == 200

    # API باید ID و نام Node فعلی را برگرداند
    assert response.data["current_node"] == road_node.id
    assert response.data["current_node_name"] == "VEHICLE_N1"


@pytest.mark.django_db
def test_driver_cannot_set_current_node_during_registration(
    api_client,
    driver,
    road_node,
):
    authenticate_client(api_client, driver)

    response = api_client.post(
        "/api/vehicles/me/",
        {
            "capacity": 4,
            "is_available": True,

            # Driver نباید بتواند خودش موقعیت تعیین کند
            "current_node": road_node.id,
        },
        format="json",
    )

    assert response.status_code == 201

    vehicle = Vehicle.objects.get(
        driver=driver.driver_profile
    )

    # current_node باید فقط توسط سیستم تغییر کند
    assert vehicle.current_node is None