import pytest

from django.test import override_settings

from road_network.models import (
    RoadEdge,
    RoadNode,
)
from shared_ride.models import RouteStop
from shared_ride.simulation import (
    SharedRouteSimulationService,
    SimulatedStop,
)


pytestmark = pytest.mark.django_db


# =========================================================
# Helpers
# =========================================================

def create_node(
    name,
    x,
    y,
):
    return RoadNode.objects.create(
        name=name,
        x=x,
        y=y,
    )


def connect(
    from_node,
    to_node,
    *,
    time_minutes,
    distance_km=1.0,
):
    return RoadEdge.objects.create(
        from_node=from_node,
        to_node=to_node,
        distance_km=distance_km,
        travel_time_minutes=time_minutes,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )


def create_basic_network():
    """
    N1 --3min--> N2 --4min--> N3
    """

    n1 = create_node(
        "N1",
        0,
        0,
    )

    n2 = create_node(
        "N2",
        1,
        0,
    )

    n3 = create_node(
        "N3",
        2,
        0,
    )


    connect(
        n1,
        n2,
        time_minutes=3,
        distance_km=1.0,
    )

    connect(
        n2,
        n3,
        time_minutes=4,
        distance_km=2.0,
    )


    return n1, n2, n3


# =========================================================
# 1. Valid Route
# =========================================================

def test_valid_multi_stop_route():

    n1, n2, n3 = (
        create_basic_network()
    )


    stops = [
        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n2,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),

        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n3,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n1,
            vehicle_capacity=4,
            stops=stops,
        )
    )


    assert result.is_valid is True

    assert result.violations == []

    assert (
        result.total_time_minutes
        == 7
    )

    assert (
        result.total_distance_km
        == pytest.approx(3.0)
    )


# =========================================================
# 2. Correct Cumulative ETA
# =========================================================

def test_cumulative_eta_is_calculated_correctly():

    n1, n2, n3 = (
        create_basic_network()
    )


    stops = [
        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n2,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),

        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n3,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n1,
            vehicle_capacity=4,
            stops=stops,
        )
    )


    assert (
        result.stop_results[0]
        .arrival_minutes
        == 3
    )

    assert (
        result.stop_results[1]
        .arrival_minutes
        == 7
    )


    assert (
        result.pickup_eta_by_group["A"]
        == 3
    )

    assert (
        result.dropoff_eta_by_group["A"]
        == 7
    )


# =========================================================
# 3. Occupancy After Every Stop
# =========================================================

def test_occupancy_is_updated_after_every_stop():

    n1, n2, n3 = (
        create_basic_network()
    )


    stops = [
        SimulatedStop(
            group_key="A",
            passenger_count=2,
            node=n2,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),

        SimulatedStop(
            group_key="A",
            passenger_count=2,
            node=n3,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n1,
            vehicle_capacity=4,
            stops=stops,
        )
    )


    assert result.is_valid is True


    assert (
        result.stop_results[0]
        .occupancy_after_stop
        == 2
    )


    assert (
        result.stop_results[1]
        .occupancy_after_stop
        == 0
    )


    assert result.peak_occupancy == 2


# =========================================================
# 4. Existing Onboard Passenger
# =========================================================

def test_existing_onboard_passenger_is_supported():

    n1, n2, n3 = (
        create_basic_network()
    )


    stops = [
        SimulatedStop(
            group_key="A",
            passenger_count=2,
            node=n3,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n2,
            vehicle_capacity=4,
            stops=stops,

            initial_onboard={
                "A": 2,
            },
        )
    )


    assert result.is_valid is True

    assert (
        result.dropoff_eta_by_group["A"]
        == 4
    )

    assert (
        result.stop_results[0]
        .occupancy_after_stop
        == 0
    )


# =========================================================
# 5. Capacity Violation
# =========================================================

def test_capacity_exceeded_is_rejected():

    n1, n2, _ = (
        create_basic_network()
    )


    stops = [
        SimulatedStop(
            group_key="A",
            passenger_count=3,
            node=n2,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n1,
            vehicle_capacity=2,
            stops=stops,
        )
    )


    assert result.is_valid is False

    assert (
        "CAPACITY_EXCEEDED:A"
        in result.violations
    )


# =========================================================
# 6. More Than Two Passenger Groups
# =========================================================

@override_settings(
    MAX_SHARED_PASSENGER_GROUPS=2
)
def test_third_active_passenger_group_is_rejected():

    n1 = create_node(
        "N1",
        0,
        0,
    )

    n2 = create_node(
        "N2",
        1,
        0,
    )

    n3 = create_node(
        "N3",
        2,
        0,
    )

    n4 = create_node(
        "N4",
        3,
        0,
    )


    connect(
        n1,
        n2,
        time_minutes=1,
    )

    connect(
        n2,
        n3,
        time_minutes=1,
    )

    connect(
        n3,
        n4,
        time_minutes=1,
    )


    stops = [
        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n2,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),

        SimulatedStop(
            group_key="B",
            passenger_count=1,
            node=n3,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),

        SimulatedStop(
            group_key="C",
            passenger_count=1,
            node=n4,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n1,
            vehicle_capacity=4,
            stops=stops,
        )
    )


    assert result.is_valid is False

    assert (
        "PASSENGER_GROUP_LIMIT_EXCEEDED:C"
        in result.violations
    )


# =========================================================
# 7. Dropoff Before Pickup
# =========================================================

def test_dropoff_before_pickup_is_rejected():

    n1, n2, _ = (
        create_basic_network()
    )


    stops = [
        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n2,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n1,
            vehicle_capacity=4,
            stops=stops,
        )
    )


    assert result.is_valid is False

    assert (
        "DROPOFF_BEFORE_PICKUP:A"
        in result.violations
    )


# =========================================================
# 8. Duplicate Pickup
# =========================================================

def test_duplicate_pickup_is_rejected():

    n1, n2, n3 = (
        create_basic_network()
    )


    stops = [
        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n2,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),

        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n3,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n1,
            vehicle_capacity=4,
            stops=stops,
        )
    )


    assert result.is_valid is False

    assert (
        "DUPLICATE_PICKUP:A"
        in result.violations
    )


# =========================================================
# 9. Duplicate Dropoff
# =========================================================

def test_duplicate_dropoff_is_rejected():

    n1, n2, n3 = (
        create_basic_network()
    )


    stops = [
        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n2,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),

        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n3,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),

        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n2,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n1,
            vehicle_capacity=4,
            stops=stops,
        )
    )


    assert result.is_valid is False

    assert (
        "DUPLICATE_DROPOFF:A"
        in result.violations
    )


# =========================================================
# 10. Passenger Count Mismatch
# =========================================================

def test_passenger_count_mismatch_is_rejected():

    n1, n2, _ = (
        create_basic_network()
    )


    stops = [
        SimulatedStop(
            group_key="A",

            # واقعی داخل Taxi = 2
            # ولی Dropoff می‌گوید 1
            passenger_count=1,

            node=n2,

            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n1,
            vehicle_capacity=4,
            stops=stops,

            initial_onboard={
                "A": 2,
            },
        )
    )


    assert result.is_valid is False

    assert (
        "PASSENGER_COUNT_MISMATCH:A"
        in result.violations
    )


# =========================================================
# 11. Unreachable Stop
# =========================================================

def test_unreachable_stop_is_rejected():

    n1 = create_node(
        "N1",
        0,
        0,
    )

    n2 = create_node(
        "N2",
        10,
        10,
    )


    # عمداً هیچ Edge نمی‌سازیم.


    stops = [
        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n2,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n1,
            vehicle_capacity=4,
            stops=stops,
        )
    )


    assert result.is_valid is False

    assert (
        f"UNREACHABLE_STOP:A:{n2.id}"
        in result.violations
    )


# =========================================================
# 12. Missing Dropoff
# =========================================================

def test_missing_dropoff_is_rejected():

    n1, n2, _ = (
        create_basic_network()
    )


    stops = [
        SimulatedStop(
            group_key="A",
            passenger_count=1,
            node=n2,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),
    ]


    result = (
        SharedRouteSimulationService.simulate(
            current_node=n1,
            vehicle_capacity=4,
            stops=stops,
        )
    )


    assert result.is_valid is False

    assert (
        "MISSING_DROPOFF:A"
        in result.violations
    )