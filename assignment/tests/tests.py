import pytest

from django.contrib.auth.models import User
from django.test import override_settings
from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from assignment.services import (
    AssignmentError,
    AssignmentService,
)
from fleet.models import Vehicle
from rides.models import RideRequest
from road_network.models import (
    RoadEdge,
    RoadNode,
)


# =========================================================
# Helper
# =========================================================

def create_driver_with_vehicle(
    username,
    current_node,
    capacity=4,
    availability_status=(
        DriverProfile.AvailabilityStatus.ONLINE
    ),
    is_available=True,
    ride_mode=Vehicle.RideMode.IDLE,
):
    # Driver
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
        availability_status=availability_status,
    )

    # Taxi
    vehicle = Vehicle.objects.create(
        driver=driver_profile,
        capacity=capacity,
        is_available=is_available,
        ride_mode=ride_mode,
        current_node=current_node,
    )

    return vehicle


# =========================================================
# Fixtures
# =========================================================

@pytest.fixture
def passenger():
    user = User.objects.create_user(
        username="assignment_passenger",
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
    # Pickup و Destination
    pickup = RoadNode.objects.create(
        name="PICKUP",
        x=0,
        y=0,
    )

    destination = RoadNode.objects.create(
        name="DESTINATION",
        x=5,
        y=5,
    )

    # موقعیت سه Taxi
    taxi_a_node = RoadNode.objects.create(
        name="TAXI_A_NODE",
        x=1,
        y=0,
    )

    taxi_b_node = RoadNode.objects.create(
        name="TAXI_B_NODE",
        x=2,
        y=0,
    )

    taxi_c_node = RoadNode.objects.create(
        name="TAXI_C_NODE",
        x=3,
        y=0,
    )

    # Taxi A → Pickup = 7 min
    RoadEdge.objects.create(
        from_node=taxi_a_node,
        to_node=pickup,
        distance_km=2.0,
        travel_time_minutes=7,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    # Taxi B → Pickup = 3 min
    RoadEdge.objects.create(
        from_node=taxi_b_node,
        to_node=pickup,
        distance_km=3.0,
        travel_time_minutes=3,
        road_type=RoadEdge.RoadType.MAIN,
        is_bidirectional=True,
    )

    # Taxi C → Pickup = 5 min
    RoadEdge.objects.create(
        from_node=taxi_c_node,
        to_node=pickup,
        distance_km=1.0,
        travel_time_minutes=5,
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
# Ranking Tests
# =========================================================

@pytest.mark.django_db
def test_all_feasible_taxis_are_returned_and_ranked(
    network,
    ride_request,
):
    taxi_a = create_driver_with_vehicle(
        username="driver_a",
        current_node=network["taxi_a_node"],
    )

    taxi_b = create_driver_with_vehicle(
        username="driver_b",
        current_node=network["taxi_b_node"],
    )

    taxi_c = create_driver_with_vehicle(
        username="driver_c",
        current_node=network["taxi_c_node"],
    )

    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )

    # همه Taxiهای feasible باید برگردند
    assert len(options) == 3

    # Ranking براساس ETA
    assert options[0].vehicle_id == taxi_b.id
    assert options[0].rank == 1
    assert options[0].pickup_eta_minutes == 3

    assert options[1].vehicle_id == taxi_c.id
    assert options[1].rank == 2
    assert options[1].pickup_eta_minutes == 5

    assert options[2].vehicle_id == taxi_a.id
    assert options[2].rank == 3
    assert options[2].pickup_eta_minutes == 7


@pytest.mark.django_db
def test_taxi_with_insufficient_capacity_is_excluded(
    network,
    ride_request,
):
    # ظرفیت 1 ولی Passenger Count برابر 2 است
    create_driver_with_vehicle(
        username="small_taxi_driver",
        current_node=network["taxi_a_node"],
        capacity=1,
    )

    valid_taxi = create_driver_with_vehicle(
        username="valid_driver",
        current_node=network["taxi_b_node"],
        capacity=4,
    )

    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )

    assert len(options) == 1

    assert (
        options[0].vehicle_id
        == valid_taxi.id
    )


@pytest.mark.django_db
def test_offline_driver_is_excluded(
    network,
    ride_request,
):
    create_driver_with_vehicle(
        username="offline_driver",
        current_node=network["taxi_a_node"],
        availability_status=(
            DriverProfile
            .AvailabilityStatus
            .OFFLINE
        ),
    )

    online_taxi = create_driver_with_vehicle(
        username="online_driver",
        current_node=network["taxi_b_node"],
    )

    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )

    assert len(options) == 1

    assert (
        options[0].vehicle_id
        == online_taxi.id
    )


@pytest.mark.django_db
def test_busy_taxi_is_excluded(
    network,
    ride_request,
):
    create_driver_with_vehicle(
        username="busy_driver",
        current_node=network["taxi_a_node"],
        ride_mode=Vehicle.RideMode.PRIVATE,
    )

    idle_taxi = create_driver_with_vehicle(
        username="idle_driver",
        current_node=network["taxi_c_node"],
        ride_mode=Vehicle.RideMode.IDLE,
    )

    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )

    assert len(options) == 1

    assert (
        options[0].vehicle_id
        == idle_taxi.id
    )


@pytest.mark.django_db
def test_unreachable_taxi_is_excluded(
    network,
    ride_request,
):
    # Node جدا از Graph
    disconnected_node = RoadNode.objects.create(
        name="DISCONNECTED",
        x=20,
        y=20,
    )

    create_driver_with_vehicle(
        username="disconnected_driver",
        current_node=disconnected_node,
    )

    reachable_taxi = create_driver_with_vehicle(
        username="reachable_driver",
        current_node=network["taxi_b_node"],
    )

    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )

    assert len(options) == 1

    assert (
        options[0].vehicle_id
        == reachable_taxi.id
    )


@pytest.mark.django_db
def test_non_pending_request_cannot_generate_options(
    ride_request,
):
    ride_request.status = RideRequest.Status.ASSIGNED
    ride_request.save(
        update_fields=["status"]
    )

    with pytest.raises(
        AssignmentError
    ):
        (
            AssignmentService
            .generate_private_taxi_options(
                ride_request
            )
        )

@pytest.mark.django_db
def test_taxi_option_contains_trip_and_total_metrics(
    network,
    ride_request,
):
    # Taxi B:
    # Taxi → Pickup = 3 min / 3 km
    vehicle = create_driver_with_vehicle(
        username="metrics_driver",
        current_node=network["taxi_b_node"],
    )

    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )

    assert len(options) == 1

    option = options[0]

    # ---------------------------------
    # Rank
    # ---------------------------------

    assert option.rank == 1
    assert option.vehicle_id == vehicle.id


    # ---------------------------------
    # Taxi → Pickup
    # ---------------------------------

    assert option.pickup_eta_minutes == 3
    assert option.pickup_distance_km == 3.0

    assert option.pickup_path_node_ids == [
        network["taxi_b_node"].id,
        network["pickup"].id,
    ]


    # ---------------------------------
    # Pickup → Destination
    # ---------------------------------

    assert option.trip_eta_minutes == 8
    assert option.trip_distance_km == 5.0

    assert option.trip_path_node_ids == [
        network["pickup"].id,
        network["destination"].id,
    ]


    # ---------------------------------
    # Total
    # ---------------------------------

    assert option.total_eta_minutes == 11
    assert option.total_distance_km == 8.0


@pytest.mark.django_db
def test_no_options_when_passenger_trip_is_unreachable(
    network,
    ride_request,
):
    # Destination جدا از Graph
    disconnected_destination = RoadNode.objects.create(
        name="UNREACHABLE_DESTINATION",
        x=50,
        y=50,
    )

    # Request را به مقصد غیرقابل دسترس وصل می‌کنیم
    ride_request.destination_node = (
        disconnected_destination
    )

    ride_request.save(
        update_fields=[
            "destination_node"
        ]
    )

    # Taxi خودش می‌تواند به Pickup برسد
    create_driver_with_vehicle(
        username="reachable_taxi_driver",
        current_node=network["taxi_b_node"],
    )

    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )

    # چون Pickup → Destination ممکن نیست،
    # هیچ Taxi Option معتبری نداریم
    assert options == []

@pytest.mark.django_db
def test_equal_eta_is_ranked_by_pickup_distance(
    network,
    ride_request,
):
    # سه موقعیت جدید برای Taxiها
    far_node = RoadNode.objects.create(
        name="TIE_FAR_NODE",
        x=10,
        y=1,
    )

    near_node = RoadNode.objects.create(
        name="TIE_NEAR_NODE",
        x=10,
        y=2,
    )

    middle_node = RoadNode.objects.create(
        name="TIE_MIDDLE_NODE",
        x=10,
        y=3,
    )


    # هر سه ETA برابر = 4 دقیقه
    # ولی Distance متفاوت است

    RoadEdge.objects.create(
        from_node=far_node,
        to_node=network["pickup"],
        distance_km=3.0,
        travel_time_minutes=4,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    RoadEdge.objects.create(
        from_node=near_node,
        to_node=network["pickup"],
        distance_km=1.0,
        travel_time_minutes=4,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    RoadEdge.objects.create(
        from_node=middle_node,
        to_node=network["pickup"],
        distance_km=2.0,
        travel_time_minutes=4,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )


    far_taxi = create_driver_with_vehicle(
        username="tie_far_driver",
        current_node=far_node,
    )

    near_taxi = create_driver_with_vehicle(
        username="tie_near_driver",
        current_node=near_node,
    )

    middle_taxi = create_driver_with_vehicle(
        username="tie_middle_driver",
        current_node=middle_node,
    )


    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )


    assert len(options) == 3


    # ETA همه برابر است
    assert options[0].pickup_eta_minutes == 4
    assert options[1].pickup_eta_minutes == 4
    assert options[2].pickup_eta_minutes == 4


    # پس Distance تعیین‌کننده Rank است
    assert options[0].vehicle_id == near_taxi.id
    assert options[0].pickup_distance_km == 1.0
    assert options[0].rank == 1

    assert options[1].vehicle_id == middle_taxi.id
    assert options[1].pickup_distance_km == 2.0
    assert options[1].rank == 2

    assert options[2].vehicle_id == far_taxi.id
    assert options[2].pickup_distance_km == 3.0
    assert options[2].rank == 3




@pytest.mark.django_db
def test_exact_tie_is_ranked_deterministically_by_vehicle_id(
    network,
    ride_request,
):
    tie_node = RoadNode.objects.create(
        name="EXACT_TIE_NODE",
        x=20,
        y=20,
    )

    RoadEdge.objects.create(
        from_node=tie_node,
        to_node=network["pickup"],
        distance_km=2.0,
        travel_time_minutes=4,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )


    first_taxi = create_driver_with_vehicle(
        username="exact_tie_driver_1",
        current_node=tie_node,
    )

    second_taxi = create_driver_with_vehicle(
        username="exact_tie_driver_2",
        current_node=tie_node,
    )


    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )


    assert len(options) == 2


    # ETA و Distance کاملاً برابر
    assert (
        options[0].pickup_eta_minutes
        == options[1].pickup_eta_minutes
    )

    assert (
        options[0].pickup_distance_km
        == options[1].pickup_distance_km
    )


    # ترتیب باید deterministic باشد
    assert options[0].vehicle_id == first_taxi.id
    assert options[0].rank == 1

    assert options[1].vehicle_id == second_taxi.id
    assert options[1].rank == 2




@pytest.mark.django_db
def test_taxi_option_contains_estimated_price(
    network,
    ride_request,
):
    create_driver_with_vehicle(
        username="price_driver",
        current_node=network["taxi_b_node"],
    )

    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )

    assert len(options) == 1

    option = options[0]

    # Trip:
    # 5 km
    # 8 min
    #
    # 2.00 + (5 × 1.50) + (8 × 0.20)
    # = 11.10

    assert option.estimated_price == 11.10



@override_settings(
    MAX_PRIVATE_PICKUP_WAIT_MINUTES=10
)
@pytest.mark.django_db
def test_taxi_exceeding_max_pickup_wait_is_excluded(
    network,
    ride_request,
):
    slow_node = RoadNode.objects.create(
        name="SLOW_TAXI_NODE",
        x=30,
        y=30,
    )

    # Taxi → Pickup = 11 min
    RoadEdge.objects.create(
        from_node=slow_node,
        to_node=network["pickup"],
        distance_km=4.0,
        travel_time_minutes=11,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    create_driver_with_vehicle(
        username="slow_pickup_driver",
        current_node=slow_node,
    )

    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )

    # حد مجاز 10 دقیقه است
    # ETA = 11 باید حذف شود
    assert options == []


@override_settings(
    MAX_PRIVATE_PICKUP_WAIT_MINUTES=10
)
@pytest.mark.django_db
def test_taxi_at_exact_max_pickup_wait_is_allowed(
    network,
    ride_request,
):
    limit_node = RoadNode.objects.create(
        name="LIMIT_TAXI_NODE",
        x=31,
        y=31,
    )

    # دقیقاً روی Limit
    RoadEdge.objects.create(
        from_node=limit_node,
        to_node=network["pickup"],
        distance_km=4.0,
        travel_time_minutes=10,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    vehicle = create_driver_with_vehicle(
        username="limit_pickup_driver",
        current_node=limit_node,
    )

    options = (
        AssignmentService
        .generate_private_taxi_options(
            ride_request
        )
    )

    assert len(options) == 1

    assert (
        options[0].vehicle_id
        == vehicle.id
    )

    assert (
        options[0].pickup_eta_minutes
        == 10
    )

    assert options[0].rank == 1