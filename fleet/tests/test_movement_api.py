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
from road_network.models import (
    RoadEdge,
    RoadNode,
)


@pytest.fixture
def api_client():
    return APIClient()


def authenticate_client(api_client, user):
    token = Token.objects.create(
        user=user
    )

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Token {token.key}"
    )


@pytest.fixture
def movement_api_setup():
    # Driver
    driver_user = User.objects.create_user(
        username="move_api_driver",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=driver_user,
        role=UserProfile.Role.DRIVER,
    )

    driver = DriverProfile.objects.create(
        user=driver_user,
        availability_status=(
            DriverProfile.AvailabilityStatus.ONLINE
        ),
    )

    # Passenger
    passenger_user = User.objects.create_user(
        username="move_api_passenger",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=passenger_user,
        role=UserProfile.Role.PASSENGER,
    )

    passenger = PassengerProfile.objects.create(
        user=passenger_user,
    )

    # Road Network
    n1 = RoadNode.objects.create(
        name="MOVE_API_N1",
        x=0,
        y=0,
    )

    n2 = RoadNode.objects.create(
        name="MOVE_API_N2",
        x=1,
        y=0,
    )

    n3 = RoadNode.objects.create(
        name="MOVE_API_N3",
        x=2,
        y=0,
    )

    n4 = RoadNode.objects.create(
        name="MOVE_API_N4",
        x=3,
        y=0,
    )

    RoadEdge.objects.create(
        from_node=n1,
        to_node=n2,
        distance_km=1,
        travel_time_minutes=2,
        is_bidirectional=True,
    )

    RoadEdge.objects.create(
        from_node=n2,
        to_node=n3,
        distance_km=1,
        travel_time_minutes=2,
        is_bidirectional=True,
    )

    RoadEdge.objects.create(
        from_node=n3,
        to_node=n4,
        distance_km=1,
        travel_time_minutes=2,
        is_bidirectional=True,
    )

    # Taxi ابتدا N1
    vehicle = Vehicle.objects.create(
        driver=driver,
        capacity=4,
        is_available=True,
        ride_mode=Vehicle.RideMode.PRIVATE,
        current_node=n1,
    )

    # Passenger: N3 → N4
    ride_request = RideRequest.objects.create(
        passenger=passenger,
        ride_type=RideRequest.RideType.PRIVATE,
        passenger_count=1,
        pickup_node=n3,
        destination_node=n4,
        status=RideRequest.Status.ASSIGNED,
    )

    ride = Ride.objects.create(
        vehicle=vehicle,
        ride_type=RideRequest.RideType.PRIVATE,
        status=Ride.Status.ACCEPTED,
    )

    RidePassenger.objects.create(
        ride=ride,
        ride_request=ride_request,
    )

    return {
        "driver_user": driver_user,
        "passenger_user": passenger_user,
        "driver": driver,
        "vehicle": vehicle,
        "ride": ride,
        "ride_request": ride_request,
        "n1": n1,
        "n2": n2,
        "n3": n3,
        "n4": n4,
    }


@pytest.mark.django_db
def test_move_next_moves_one_node_towards_pickup(
    api_client,
    movement_api_setup,
):
    setup = movement_api_setup

    authenticate_client(
        api_client,
        setup["driver_user"],
    )

    response = api_client.post(
        "/api/vehicles/me/move-next/",
        {},
        format="json",
    )

    assert response.status_code == 200

    setup["vehicle"].refresh_from_db()

    # N1 → N2 فقط یک Step
    assert setup["vehicle"].current_node == setup["n2"]

    assert response.data["target_type"] == "PICKUP"
    assert response.data["current_node"]["name"] == "MOVE_API_N2"


@pytest.mark.django_db
def test_move_next_does_not_teleport_to_pickup(
    api_client,
    movement_api_setup,
):
    setup = movement_api_setup

    authenticate_client(
        api_client,
        setup["driver_user"],
    )

    api_client.post(
        "/api/vehicles/me/move-next/",
        {},
        format="json",
    )

    setup["vehicle"].refresh_from_db()

    # Pickup روی N3 است ولی فقط تا N2 حرکت می‌کند
    assert setup["vehicle"].current_node != setup["n3"]
    assert setup["vehicle"].current_node == setup["n2"]


@pytest.mark.django_db
def test_in_progress_ride_moves_towards_dropoff(
    api_client,
    movement_api_setup,
):
    setup = movement_api_setup

    # فرض می‌کنیم Passenger pickup شده
    setup["vehicle"].current_node = setup["n3"]
    setup["vehicle"].save()

    setup["ride"].status = Ride.Status.IN_PROGRESS
    setup["ride"].save()

    authenticate_client(
        api_client,
        setup["driver_user"],
    )

    response = api_client.post(
        "/api/vehicles/me/move-next/",
        {},
        format="json",
    )

    assert response.status_code == 200

    setup["vehicle"].refresh_from_db()

    assert setup["vehicle"].current_node == setup["n4"]
    assert response.data["target_type"] == "DROPOFF"


@pytest.mark.django_db
def test_assigned_ride_must_be_accepted_before_movement(
    api_client,
    movement_api_setup,
):
    setup = movement_api_setup

    setup["ride"].status = Ride.Status.ASSIGNED
    setup["ride"].save()

    authenticate_client(
        api_client,
        setup["driver_user"],
    )

    response = api_client.post(
        "/api/vehicles/me/move-next/",
        {},
        format="json",
    )

    assert response.status_code == 400

    setup["vehicle"].refresh_from_db()

    # Taxi نباید حرکت کند
    assert setup["vehicle"].current_node == setup["n1"]


@pytest.mark.django_db
def test_vehicle_without_active_ride_cannot_move(
    api_client,
    movement_api_setup,
):
    setup = movement_api_setup

    setup["ride"].status = Ride.Status.COMPLETED
    setup["ride"].save()

    authenticate_client(
        api_client,
        setup["driver_user"],
    )

    response = api_client.post(
        "/api/vehicles/me/move-next/",
        {},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_offline_driver_cannot_move_through_api(
    api_client,
    movement_api_setup,
):
    setup = movement_api_setup

    setup["driver"].availability_status = (
        DriverProfile.AvailabilityStatus.OFFLINE
    )
    setup["driver"].save()

    authenticate_client(
        api_client,
        setup["driver_user"],
    )

    response = api_client.post(
        "/api/vehicles/me/move-next/",
        {},
        format="json",
    )

    assert response.status_code == 400

    setup["vehicle"].refresh_from_db()

    assert setup["vehicle"].current_node == setup["n1"]


@pytest.mark.django_db
def test_passenger_cannot_use_movement_api(
    api_client,
    movement_api_setup,
):
    setup = movement_api_setup

    authenticate_client(
        api_client,
        setup["passenger_user"],
    )

    response = api_client.post(
        "/api/vehicles/me/move-next/",
        {},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_unauthenticated_user_cannot_move_vehicle(
    api_client,
):
    response = api_client.post(
        "/api/vehicles/me/move-next/",
        {},
        format="json",
    )

    assert response.status_code == 401