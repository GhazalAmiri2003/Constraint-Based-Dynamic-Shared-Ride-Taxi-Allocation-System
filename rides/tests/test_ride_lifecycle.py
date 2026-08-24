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
from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)
from rides.services import (
    RideLifecycleError,
    assign_private_ride,
)
from road_network.models import RoadNode


@pytest.fixture
def api_client():
    # Client برای تست API
    return APIClient()


@pytest.fixture
def passenger():
    # Passenger تستی
    user = User.objects.create_user(
        username="passenger_lifecycle",
        email="passenger_lifecycle@example.com",
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
    # Driver اصلی تست
    user = User.objects.create_user(
        username="driver_lifecycle",
        email="driver_lifecycle@example.com",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.DRIVER,
    )

    driver_profile = DriverProfile.objects.create(
        user=user,
        availability_status=(
            DriverProfile.AvailabilityStatus.ONLINE
        ),
    )

    # Taxi آماده Assignment
    Vehicle.objects.create(
        driver=driver_profile,
        capacity=4,
        is_available=True,
        ride_mode=Vehicle.RideMode.IDLE,
    )

    return user


@pytest.fixture
def second_driver():
    # Driver دوم برای تست Ownership
    user = User.objects.create_user(
        username="driver_two",
        email="driver_two@example.com",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.DRIVER,
    )

    driver_profile = DriverProfile.objects.create(
        user=user,
        availability_status=(
            DriverProfile.AvailabilityStatus.ONLINE
        ),
    )

    Vehicle.objects.create(
        driver=driver_profile,
        capacity=4,
        is_available=True,
        ride_mode=Vehicle.RideMode.IDLE,
    )

    return user


@pytest.fixture
def nodes():
    # Pickup و Destination تست
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
def ride_request(
    passenger,
    nodes,
):
    # Private Request آماده Assignment
    n1, n2 = nodes

    return RideRequest.objects.create(
        passenger=passenger.passenger_profile,
        ride_type=RideRequest.RideType.PRIVATE,
        passenger_count=2,
        pickup_node=n1,
        destination_node=n2,
        status=RideRequest.Status.PENDING,
    )


@pytest.fixture
def assigned_ride(
    driver,
    ride_request,
):
    # Assignment اولیه
    vehicle = driver.driver_profile.vehicle

    return assign_private_ride(
        ride_request,
        vehicle,
    )


def authenticate_client(
    api_client,
    user,
):
    # Token Authentication
    token = Token.objects.create(
        user=user
    )

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Token {token.key}"
    )


@pytest.mark.django_db
def test_private_ride_assignment_updates_all_states(
    driver,
    ride_request,
):
    vehicle = driver.driver_profile.vehicle

    ride = assign_private_ride(
        ride_request,
        vehicle,
    )

    ride_request.refresh_from_db()
    vehicle.refresh_from_db()

    assert ride.status == Ride.Status.ASSIGNED

    assert (
        ride_request.status
        == RideRequest.Status.ASSIGNED
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.PRIVATE
    )

    # Request باید به Ride وصل شده باشد
    assert RidePassenger.objects.filter(
        ride=ride,
        ride_request=ride_request,
    ).exists()


@pytest.mark.django_db
def test_driver_can_accept_assigned_ride(
    api_client,
    driver,
    assigned_ride,
):
    authenticate_client(
        api_client,
        driver,
    )

    response = api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/accept/"
    )

    assert response.status_code == 200
    assert response.data["status"] == "ACCEPTED"

    assigned_ride.refresh_from_db()

    assert (
        assigned_ride.status
        == Ride.Status.ACCEPTED
    )

    # زمان Accept باید ثبت شود
    assert assigned_ride.accepted_at is not None


@pytest.mark.django_db
def test_ride_cannot_start_before_accept(
    api_client,
    driver,
    assigned_ride,
):
    authenticate_client(
        api_client,
        driver,
    )

    response = api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/start/"
    )

    # باید اول Accept شود
    assert response.status_code == 400

    assigned_ride.refresh_from_db()

    assert (
        assigned_ride.status
        == Ride.Status.ASSIGNED
    )


@pytest.mark.django_db
def test_driver_can_start_accepted_ride(
    api_client,
    driver,
    assigned_ride,
    ride_request,
):
    authenticate_client(
        api_client,
        driver,
    )

    vehicle = driver.driver_profile.vehicle

    # ابتدا Accept
    accept_response = api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/accept/"
    )

    assert accept_response.status_code == 200

    # Taxi باید اول به Pickup برسد
    vehicle.current_node = ride_request.pickup_node

    vehicle.save(
        update_fields=[
            "current_node",
            "updated_at",
        ]
    )

    # حالا Start مجاز است
    response = api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/start/"
    )

    assert response.status_code == 200
    assert response.data["status"] == "IN_PROGRESS"

    assigned_ride.refresh_from_db()

    assert (
        assigned_ride.status
        == Ride.Status.IN_PROGRESS
    )

    assert assigned_ride.started_at is not None


@pytest.mark.django_db
def test_ride_cannot_complete_before_start(
    api_client,
    driver,
    assigned_ride,
):
    authenticate_client(
        api_client,
        driver,
    )

    # فقط Accept
    api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/accept/"
    )

    # بدون Start مستقیماً Complete
    response = api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/complete/"
    )

    assert response.status_code == 400

    assigned_ride.refresh_from_db()

    assert (
        assigned_ride.status
        == Ride.Status.ACCEPTED
    )


@pytest.mark.django_db
def test_driver_can_complete_private_ride(
    api_client,
    driver,
    assigned_ride,
    ride_request,
):
    authenticate_client(
        api_client,
        driver,
    )

    vehicle = driver.driver_profile.vehicle

    # ---------------------------------
    # 1. Accept
    # ---------------------------------

    accept_response = api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/accept/"
    )

    assert accept_response.status_code == 200


    # ---------------------------------
    # 2. Taxi reaches Pickup
    # ---------------------------------

    vehicle.current_node = (
        ride_request.pickup_node
    )

    vehicle.save(
        update_fields=[
            "current_node",
            "updated_at",
        ]
    )


    # ---------------------------------
    # 3. Start Ride
    # ---------------------------------

    start_response = api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/start/"
    )

    assert start_response.status_code == 200
    assert (
        start_response.data["status"]
        == "IN_PROGRESS"
    )


    # ---------------------------------
    # 4. Taxi reaches Destination
    # ---------------------------------

    vehicle.current_node = (
        ride_request.destination_node
    )

    vehicle.save(
        update_fields=[
            "current_node",
            "updated_at",
        ]
    )


    # ---------------------------------
    # 5. Complete Ride
    # ---------------------------------

    response = api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/complete/"
    )

    assert response.status_code == 200
    assert response.data["status"] == "COMPLETED"


    # Stateها را دوباره از DB می‌خوانیم
    assigned_ride.refresh_from_db()
    ride_request.refresh_from_db()
    vehicle.refresh_from_db()


    # Ride تمام شده
    assert (
        assigned_ride.status
        == Ride.Status.COMPLETED
    )

    assert assigned_ride.completed_at is not None


    # Request هم Completed
    assert (
        ride_request.status
        == RideRequest.Status.COMPLETED
    )


    # Taxi دوباره آزاد
    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )


    # Taxi در آخرین مقصد باقی می‌ماند
    assert (
        vehicle.current_node
        == ride_request.destination_node
    )


@pytest.mark.django_db
def test_driver_can_reject_assigned_ride(
    api_client,
    driver,
    assigned_ride,
    ride_request,
):
    authenticate_client(
        api_client,
        driver,
    )

    response = api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/reject/"
    )

    assert response.status_code == 200
    assert response.data["status"] == "REJECTED"

    assigned_ride.refresh_from_db()
    ride_request.refresh_from_db()

    vehicle = driver.driver_profile.vehicle
    vehicle.refresh_from_db()

    # Ride رد شده
    assert (
        assigned_ride.status
        == Ride.Status.REJECTED
    )

    # Request دوباره Pending
    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )

    # Taxi دوباره آزاد
    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )


@pytest.mark.django_db
def test_wrong_driver_cannot_access_ride(
    api_client,
    second_driver,
    assigned_ride,
):
    authenticate_client(
        api_client,
        second_driver,
    )

    response = api_client.get(
        f"/api/driver/rides/{assigned_ride.id}/"
    )

    # Ride متعلق به Driver دیگری است
    assert response.status_code == 404


@pytest.mark.django_db
def test_ride_cannot_be_accepted_twice(
    api_client,
    driver,
    assigned_ride,
):
    authenticate_client(
        api_client,
        driver,
    )

    # Accept اول
    first_response = api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/accept/"
    )

    assert first_response.status_code == 200

    # Accept دوم باید Reject شود
    second_response = api_client.post(
        f"/api/driver/rides/{assigned_ride.id}/accept/"
    )

    assert second_response.status_code == 400


@pytest.mark.django_db
def test_offline_driver_cannot_receive_private_assignment(
    driver,
    ride_request,
):
    driver_profile = driver.driver_profile

    # Driver را Offline می‌کنیم
    driver_profile.availability_status = (
        DriverProfile.AvailabilityStatus.OFFLINE
    )

    driver_profile.save()

    vehicle = driver_profile.vehicle

    # Assignment باید Fail شود
    with pytest.raises(
        RideLifecycleError
    ):
        assign_private_ride(
            ride_request,
            vehicle,
        )

    # هیچ Ride نباید ساخته شود
    assert Ride.objects.count() == 0

    ride_request.refresh_from_db()
    vehicle.refresh_from_db()

    # Stateها نباید تغییر کرده باشند
    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )