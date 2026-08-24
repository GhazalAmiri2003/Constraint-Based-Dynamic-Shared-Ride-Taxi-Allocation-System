import pytest

from django.contrib.auth.models import User

from accounts.models import (
    DriverProfile,
    UserProfile,
)
from fleet.models import Vehicle
from fleet.services import (
    VehicleMovementError,
    VehicleMovementService,
)
from road_network.models import (
    RoadEdge,
    RoadNode,
)


@pytest.fixture
def movement_setup():
    # Driver تستی
    user = User.objects.create_user(
        username="movement_driver",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.DRIVER,
    )

    driver = DriverProfile.objects.create(
        user=user,
        availability_status=(
            DriverProfile.AvailabilityStatus.ONLINE
        ),
    )

    # Nodeها
    n1 = RoadNode.objects.create(
        name="MOVE_N1",
        x=0,
        y=0,
    )

    n2 = RoadNode.objects.create(
        name="MOVE_N2",
        x=1,
        y=0,
    )

    n3 = RoadNode.objects.create(
        name="MOVE_N3",
        x=2,
        y=0,
    )

    n4 = RoadNode.objects.create(
        name="MOVE_N4",
        x=3,
        y=0,
    )

    # N1 ↔ N2
    RoadEdge.objects.create(
        from_node=n1,
        to_node=n2,
        distance_km=1,
        travel_time_minutes=2,
        is_bidirectional=True,
    )

    # N2 ↔ N3
    RoadEdge.objects.create(
        from_node=n2,
        to_node=n3,
        distance_km=1,
        travel_time_minutes=2,
        is_bidirectional=True,
    )

    # N3 → N4 فقط یک‌طرفه
    RoadEdge.objects.create(
        from_node=n3,
        to_node=n4,
        distance_km=1,
        travel_time_minutes=2,
        is_bidirectional=False,
    )

    # Taxi ابتدا روی N1
    vehicle = Vehicle.objects.create(
        driver=driver,
        capacity=4,
        is_available=True,
        current_node=n1,
    )

    return {
        "driver": driver,
        "vehicle": vehicle,
        "n1": n1,
        "n2": n2,
        "n3": n3,
        "n4": n4,
    }


@pytest.mark.django_db
def test_vehicle_can_move_to_adjacent_node(
    movement_setup,
):
    vehicle = movement_setup["vehicle"]
    n2 = movement_setup["n2"]

    VehicleMovementService.move_to_adjacent_node(
        vehicle,
        n2,
    )

    vehicle.refresh_from_db()

    assert vehicle.current_node == n2


@pytest.mark.django_db
def test_vehicle_cannot_skip_nodes(
    movement_setup,
):
    vehicle = movement_setup["vehicle"]
    n3 = movement_setup["n3"]

    # N1 → N3 Edge مستقیم ندارد
    with pytest.raises(VehicleMovementError):
        VehicleMovementService.move_to_adjacent_node(
            vehicle,
            n3,
        )

    vehicle.refresh_from_db()

    # Taxi باید روی N1 بماند
    assert (
        vehicle.current_node
        == movement_setup["n1"]
    )


@pytest.mark.django_db
def test_bidirectional_edge_allows_reverse_movement(
    movement_setup,
):
    vehicle = movement_setup["vehicle"]
    n1 = movement_setup["n1"]
    n2 = movement_setup["n2"]

    # ابتدا Taxi را روی N2 قرار می‌دهیم
    vehicle.current_node = n2
    vehicle.save()

    VehicleMovementService.move_to_adjacent_node(
        vehicle,
        n1,
    )

    vehicle.refresh_from_db()

    assert vehicle.current_node == n1


@pytest.mark.django_db
def test_one_way_edge_blocks_reverse_movement(
    movement_setup,
):
    vehicle = movement_setup["vehicle"]
    n3 = movement_setup["n3"]
    n4 = movement_setup["n4"]

    # Taxi روی N4
    vehicle.current_node = n4
    vehicle.save()

    # Edge فقط N3 → N4 است
    with pytest.raises(VehicleMovementError):
        VehicleMovementService.move_to_adjacent_node(
            vehicle,
            n3,
        )

    vehicle.refresh_from_db()

    assert vehicle.current_node == n4


@pytest.mark.django_db
def test_offline_driver_cannot_move_vehicle(
    movement_setup,
):
    driver = movement_setup["driver"]
    vehicle = movement_setup["vehicle"]
    n2 = movement_setup["n2"]

    driver.availability_status = (
        DriverProfile.AvailabilityStatus.OFFLINE
    )
    driver.save()

    with pytest.raises(VehicleMovementError):
        VehicleMovementService.move_to_adjacent_node(
            vehicle,
            n2,
        )

    vehicle.refresh_from_db()

    assert (
        vehicle.current_node
        == movement_setup["n1"]
    )


@pytest.mark.django_db
def test_vehicle_without_position_cannot_move(
    movement_setup,
):
    vehicle = movement_setup["vehicle"]
    n2 = movement_setup["n2"]

    vehicle.current_node = None
    vehicle.save()

    with pytest.raises(VehicleMovementError):
        VehicleMovementService.move_to_adjacent_node(
            vehicle,
            n2,
        )


@pytest.mark.django_db
def test_move_towards_destination_moves_only_one_node(
    movement_setup,
):
    vehicle = movement_setup["vehicle"]
    n2 = movement_setup["n2"]
    n3 = movement_setup["n3"]

    # Route کامل: N1 → N2 → N3
    VehicleMovementService.move_towards_destination(
        vehicle,
        n3,
    )

    vehicle.refresh_from_db()

    # فقط یک Step باید حرکت کرده باشد
    assert vehicle.current_node == n2


@pytest.mark.django_db
def test_vehicle_at_destination_does_not_move(
    movement_setup,
):
    vehicle = movement_setup["vehicle"]
    n1 = movement_setup["n1"]

    VehicleMovementService.move_towards_destination(
        vehicle,
        n1,
    )

    vehicle.refresh_from_db()

    assert vehicle.current_node == n1