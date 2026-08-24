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
from rides.models import RideRequest
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
    user = User.objects.create_user(
        username="api_passenger",
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
    user = User.objects.create_user(
        username="second_api_passenger",
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
        name="API_PICKUP",
        x=0,
        y=0,
    )

    destination = RoadNode.objects.create(
        name="API_DESTINATION",
        x=4,
        y=4,
    )

    taxi_a_node = RoadNode.objects.create(
        name="API_TAXI_A",
        x=1,
        y=0,
    )

    taxi_b_node = RoadNode.objects.create(
        name="API_TAXI_B",
        x=2,
        y=0,
    )

    taxi_c_node = RoadNode.objects.create(
        name="API_TAXI_C",
        x=3,
        y=0,
    )

    # Taxi A → ETA 7
    RoadEdge.objects.create(
        from_node=taxi_a_node,
        to_node=pickup,
        distance_km=2.0,
        travel_time_minutes=7,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    # Taxi B → ETA 3
    RoadEdge.objects.create(
        from_node=taxi_b_node,
        to_node=pickup,
        distance_km=3.0,
        travel_time_minutes=3,
        road_type=RoadEdge.RoadType.MAIN,
        is_bidirectional=True,
    )

    # Taxi C → ETA 5
    RoadEdge.objects.create(
        from_node=taxi_c_node,
        to_node=pickup,
        distance_km=1.0,
        travel_time_minutes=5,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    # مسیر خود Ride
    RoadEdge.objects.create(
        from_node=pickup,
        to_node=destination,
        distance_km=4.0,
        travel_time_minutes=8,
        road_type=RoadEdge.RoadType.MAIN,
        is_bidirectional=True,
    )

    return {
        "pickup": pickup,
        "destination": destination,
        "taxi_a_node": taxi_a_node,
        "taxi_b_node": taxi_b_node,
        "taxi_c_node": taxi_c_node,
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
# API Tests
# =========================================================

@pytest.mark.django_db
def test_passenger_receives_all_ranked_taxi_options(
    api_client,
    passenger,
    network,
    ride_request,
):
    taxi_a = create_driver_with_vehicle(
        username="api_driver_a",
        current_node=network["taxi_a_node"],
    )

    taxi_b = create_driver_with_vehicle(
        username="api_driver_b",
        current_node=network["taxi_b_node"],
    )

    taxi_c = create_driver_with_vehicle(
        username="api_driver_c",
        current_node=network["taxi_c_node"],
    )

    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.get(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "taxi-options/"
    )

    assert response.status_code == 200

    assert (
        response.data["ride_request_id"]
        == ride_request.id
    )

    # باید هر سه گزینه برگردند
    assert response.data["option_count"] == 3

    options = response.data["options"]

    assert len(options) == 3

    # Rank 1 → Taxi B → ETA 3
    assert options[0]["rank"] == 1
    assert options[0]["vehicle_id"] == taxi_b.id
    assert options[0]["pickup_eta_minutes"] == 3

    # Rank 2 → Taxi C → ETA 5
    assert options[1]["rank"] == 2
    assert options[1]["vehicle_id"] == taxi_c.id
    assert options[1]["pickup_eta_minutes"] == 5

    # Rank 3 → Taxi A → ETA 7
    assert options[2]["rank"] == 3
    assert options[2]["vehicle_id"] == taxi_a.id
    assert options[2]["pickup_eta_minutes"] == 7


@pytest.mark.django_db
def test_api_returns_empty_list_when_no_taxi_is_feasible(
    api_client,
    passenger,
    ride_request,
):
    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.get(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "taxi-options/"
    )

    assert response.status_code == 200

    assert response.data["option_count"] == 0
    assert response.data["options"] == []


@pytest.mark.django_db
def test_passenger_cannot_view_another_passengers_options(
    api_client,
    second_passenger,
    ride_request,
):
    authenticate_client(
        api_client,
        second_passenger,
    )

    response = api_client.get(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "taxi-options/"
    )

    # Request متعلق به Passenger دیگری است
    assert response.status_code == 404


@pytest.mark.django_db
def test_non_pending_request_cannot_get_taxi_options(
    api_client,
    passenger,
    ride_request,
):
    ride_request.status = (
        RideRequest.Status.ASSIGNED
    )

    ride_request.save(
        update_fields=["status"]
    )

    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.get(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "taxi-options/"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_unauthenticated_user_cannot_get_taxi_options(
    api_client,
    ride_request,
):
    response = api_client.get(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "taxi-options/"
    )

    assert response.status_code in [
        401,
        403,
    ]

@pytest.mark.django_db
def test_api_returns_trip_and_total_metrics(
    api_client,
    passenger,
    network,
    ride_request,
):
    # Taxi B:
    # Taxi → Pickup = 3 min / 3 km
    vehicle = create_driver_with_vehicle(
        username="api_metrics_driver",
        current_node=network["taxi_b_node"],
    )

    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.get(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "taxi-options/"
    )

    assert response.status_code == 200
    assert response.data["option_count"] == 1

    option = response.data["options"][0]

    # ---------------------------------
    # Rank
    # ---------------------------------

    assert option["rank"] == 1
    assert option["vehicle_id"] == vehicle.id


    # ---------------------------------
    # Taxi → Pickup
    # ---------------------------------

    assert option["pickup_eta_minutes"] == 3
    assert option["pickup_distance_km"] == 3.0

    assert option["pickup_path_node_ids"] == [
        network["taxi_b_node"].id,
        network["pickup"].id,
    ]


    # ---------------------------------
    # Pickup → Destination
    # ---------------------------------

    assert option["trip_eta_minutes"] == 8
    assert option["trip_distance_km"] == 4.0

    assert option["trip_path_node_ids"] == [
        network["pickup"].id,
        network["destination"].id,
    ]


    # ---------------------------------
    # Total
    # ---------------------------------

    assert option["total_eta_minutes"] == 11
    assert option["total_distance_km"] == 7.0


@pytest.mark.django_db
def test_api_returns_no_options_when_trip_is_unreachable(
    api_client,
    passenger,
    network,
    ride_request,
):
    # Destination جدید که هیچ Edgeای ندارد
    disconnected_destination = RoadNode.objects.create(
        name="API_UNREACHABLE_DESTINATION",
        x=50,
        y=50,
    )

    ride_request.destination_node = (
        disconnected_destination
    )

    ride_request.save(
        update_fields=[
            "destination_node"
        ]
    )


    # Taxi می‌تواند به Pickup برسد
    create_driver_with_vehicle(
        username="api_reachable_taxi",
        current_node=network["taxi_b_node"],
    )

    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.get(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "taxi-options/"
    )

    assert response.status_code == 200

    # خود Trip غیرممکن است
    assert response.data["option_count"] == 0
    assert response.data["options"] == []




@pytest.mark.django_db
def test_api_returns_estimated_price(
    api_client,
    passenger,
    network,
    ride_request,
):
    create_driver_with_vehicle(
        username="api_price_driver",
        current_node=network["taxi_b_node"],
    )

    authenticate_client(
        api_client,
        passenger,
    )

    response = api_client.get(
        "/api/assignment/"
        f"ride-requests/{ride_request.id}/"
        "taxi-options/"
    )

    assert response.status_code == 200
    assert response.data["option_count"] == 1

    option = response.data["options"][0]

    # API fixture:
    # Trip = 4 km / 8 min
    #
    # 2.00 + (4 × 1.50) + (8 × 0.20)
    # = 9.60

    assert option["estimated_price"] == 9.6