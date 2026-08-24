import pytest

from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from rides.models import RideRequest
from road_network.models import RoadNode


@pytest.fixture
def api_client():
    # Client برای تست API
    return APIClient()


@pytest.fixture
def nodes():
    # Nodeهای تستی
    n1 = RoadNode.objects.create(name="N1", x=10, y=10)
    n2 = RoadNode.objects.create(name="N2", x=20, y=10)
    n3 = RoadNode.objects.create(name="N3", x=30, y=20)

    return n1, n2, n3


@pytest.fixture
def passenger():
    # ساخت Passenger تستی
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
def second_passenger():
    # Passenger دوم برای تست Ownership
    user = User.objects.create_user(
        username="passenger_two",
        email="passenger_two@example.com",
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
    # Driver برای تست Permission
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


def authenticate_client(api_client, user):
    # Token Authentication
    token = Token.objects.create(user=user)

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Token {token.key}"
    )


@pytest.mark.django_db
def test_passenger_can_create_private_ride_request(
    api_client,
    passenger,
    nodes,
):
    authenticate_client(api_client, passenger)

    n1, _, n3 = nodes

    response = api_client.post(
        "/api/ride-requests/",
        {
            "ride_type": "PRIVATE",
            "passenger_count": 2,
            "pickup_node": n1.id,
            "destination_node": n3.id,
            "notes": "Private test",
        },
        format="json",
    )

    assert response.status_code == 201

    ride_request = RideRequest.objects.get()

    assert ride_request.passenger == passenger.passenger_profile
    assert ride_request.ride_type == RideRequest.RideType.PRIVATE
    assert ride_request.passenger_count == 2
    assert ride_request.pickup_node == n1
    assert ride_request.destination_node == n3
    assert ride_request.status == RideRequest.Status.PENDING


@pytest.mark.django_db
def test_passenger_can_create_shared_ride_request(
    api_client,
    passenger,
    nodes,
):
    authenticate_client(api_client, passenger)

    n1, n2, _ = nodes

    response = api_client.post(
        "/api/ride-requests/",
        {
            "ride_type": "SHARED",
            "passenger_count": 1,
            "pickup_node": n1.id,
            "destination_node": n2.id,
            "notes": "",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["ride_type"] == "SHARED"
    assert response.data["status"] == "PENDING"


@pytest.mark.django_db
def test_same_pickup_and_destination_is_rejected(
    api_client,
    passenger,
    nodes,
):
    authenticate_client(api_client, passenger)

    n1, _, _ = nodes

    response = api_client.post(
        "/api/ride-requests/",
        {
            "ride_type": "PRIVATE",
            "passenger_count": 1,
            "pickup_node": n1.id,
            "destination_node": n1.id,
        },
        format="json",
    )

    # N1 → N1 مجاز نیست
    assert response.status_code == 400
    assert RideRequest.objects.count() == 0


@pytest.mark.django_db
def test_passenger_count_above_four_is_rejected(
    api_client,
    passenger,
    nodes,
):
    authenticate_client(api_client, passenger)

    n1, n2, _ = nodes

    response = api_client.post(
        "/api/ride-requests/",
        {
            "ride_type": "SHARED",
            "passenger_count": 5,
            "pickup_node": n1.id,
            "destination_node": n2.id,
        },
        format="json",
    )

    # حداکثر Passenger Count = 4
    assert response.status_code == 400
    assert "passenger_count" in response.data


@pytest.mark.django_db
def test_invalid_ride_type_is_rejected(
    api_client,
    passenger,
    nodes,
):
    authenticate_client(api_client, passenger)

    n1, n2, _ = nodes

    response = api_client.post(
        "/api/ride-requests/",
        {
            "ride_type": "FLYING",
            "passenger_count": 1,
            "pickup_node": n1.id,
            "destination_node": n2.id,
        },
        format="json",
    )

    # فقط PRIVATE یا SHARED
    assert response.status_code == 400
    assert "ride_type" in response.data


@pytest.mark.django_db
def test_unauthenticated_user_cannot_create_ride_request(
    api_client,
    nodes,
):
    n1, n2, _ = nodes

    response = api_client.post(
        "/api/ride-requests/",
        {
            "ride_type": "PRIVATE",
            "passenger_count": 1,
            "pickup_node": n1.id,
            "destination_node": n2.id,
        },
        format="json",
    )

    # بدون Token
    assert response.status_code == 401


@pytest.mark.django_db
def test_driver_cannot_create_ride_request(
    api_client,
    driver,
    nodes,
):
    authenticate_client(api_client, driver)

    n1, n2, _ = nodes

    response = api_client.post(
        "/api/ride-requests/",
        {
            "ride_type": "PRIVATE",
            "passenger_count": 1,
            "pickup_node": n1.id,
            "destination_node": n2.id,
        },
        format="json",
    )

    # RideRequest مخصوص Passenger است
    assert response.status_code == 403


@pytest.mark.django_db
def test_passenger_only_sees_own_requests(
    api_client,
    passenger,
    second_passenger,
    nodes,
):
    n1, n2, n3 = nodes

    # Request Passenger اول
    RideRequest.objects.create(
        passenger=passenger.passenger_profile,
        ride_type=RideRequest.RideType.PRIVATE,
        passenger_count=1,
        pickup_node=n1,
        destination_node=n2,
    )

    # Request Passenger دوم
    RideRequest.objects.create(
        passenger=second_passenger.passenger_profile,
        ride_type=RideRequest.RideType.SHARED,
        passenger_count=1,
        pickup_node=n2,
        destination_node=n3,
    )

    authenticate_client(api_client, passenger)

    response = api_client.get(
        "/api/ride-requests/"
    )

    assert response.status_code == 200

    # فقط Request خودش
    assert len(response.data) == 1
    assert response.data[0]["passenger_username"] == "passenger_test"


@pytest.mark.django_db
def test_passenger_cannot_access_another_passengers_request(
    api_client,
    passenger,
    second_passenger,
    nodes,
):
    n1, n2, _ = nodes

    ride_request = RideRequest.objects.create(
        passenger=second_passenger.passenger_profile,
        ride_type=RideRequest.RideType.PRIVATE,
        passenger_count=1,
        pickup_node=n1,
        destination_node=n2,
    )

    authenticate_client(api_client, passenger)

    response = api_client.get(
        f"/api/ride-requests/{ride_request.id}/"
    )

    # Ownership protection
    assert response.status_code == 404


@pytest.mark.django_db
def test_passenger_can_cancel_own_pending_request(
    api_client,
    passenger,
    nodes,
):
    n1, n2, _ = nodes

    ride_request = RideRequest.objects.create(
        passenger=passenger.passenger_profile,
        ride_type=RideRequest.RideType.PRIVATE,
        passenger_count=2,
        pickup_node=n1,
        destination_node=n2,
    )

    authenticate_client(api_client, passenger)

    response = api_client.post(
        f"/api/ride-requests/{ride_request.id}/cancel/"
    )

    assert response.status_code == 200

    # مقدار جدید را از DB بخوان
    ride_request.refresh_from_db()

    assert ride_request.status == RideRequest.Status.CANCELLED
    assert response.data["status"] == "CANCELLED"


@pytest.mark.django_db
def test_cancelled_request_cannot_be_cancelled_again(
    api_client,
    passenger,
    nodes,
):
    n1, n2, _ = nodes

    ride_request = RideRequest.objects.create(
        passenger=passenger.passenger_profile,
        ride_type=RideRequest.RideType.PRIVATE,
        passenger_count=1,
        pickup_node=n1,
        destination_node=n2,
        status=RideRequest.Status.CANCELLED,
    )

    authenticate_client(api_client, passenger)

    response = api_client.post(
        f"/api/ride-requests/{ride_request.id}/cancel/"
    )

    # Cancel تکراری مجاز نیست
    assert response.status_code == 400