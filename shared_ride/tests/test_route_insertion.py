import pytest

from road_network.models import (
    RoadEdge,
    RoadNode,
)
from shared_ride.insertion import (
    SharedRouteInsertionError,
    SharedRouteInsertionService,
)
from shared_ride.models import RouteStop
from shared_ride.simulation import (
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
    time_minutes=1,
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


def make_stop(
    *,
    group_key,
    passenger_count,
    node,
    stop_type,
):
    return SimulatedStop(
        group_key=group_key,
        passenger_count=passenger_count,
        node=node,
        stop_type=stop_type,
    )


# =========================================================
# 1. Empty Existing Route
# =========================================================

def test_empty_route_generates_one_candidate():

    pickup = create_node(
        "Pickup",
        0,
        0,
    )

    dropoff = create_node(
        "Dropoff",
        1,
        0,
    )


    new_pickup = make_stop(
        group_key="B",
        passenger_count=1,
        node=pickup,
        stop_type=(
            RouteStop.StopType.PICKUP
        ),
    )


    new_dropoff = make_stop(
        group_key="B",
        passenger_count=1,
        node=dropoff,
        stop_type=(
            RouteStop.StopType.DROPOFF
        ),
    )


    candidates = (
        SharedRouteInsertionService
        .generate_candidates(
            existing_stops=[],
            new_pickup=new_pickup,
            new_dropoff=new_dropoff,
        )
    )


    assert len(candidates) == 1

    assert (
        candidates[0].stops
        == (
            new_pickup,
            new_dropoff,
        )
    )

    assert (
        candidates[0].pickup_index
        == 0
    )

    assert (
        candidates[0].dropoff_index
        == 1
    )


# =========================================================
# 2. One Existing Stop → 3 Candidates
# =========================================================

def test_one_existing_stop_generates_three_candidates():

    n1 = create_node("N1", 0, 0)
    n2 = create_node("N2", 1, 0)
    n3 = create_node("N3", 2, 0)


    existing = [
        make_stop(
            group_key="A",
            passenger_count=1,
            node=n2,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        )
    ]


    pickup = make_stop(
        group_key="B",
        passenger_count=1,
        node=n1,
        stop_type=(
            RouteStop.StopType.PICKUP
        ),
    )


    dropoff = make_stop(
        group_key="B",
        passenger_count=1,
        node=n3,
        stop_type=(
            RouteStop.StopType.DROPOFF
        ),
    )


    candidates = (
        SharedRouteInsertionService
        .generate_candidates(
            existing_stops=existing,
            new_pickup=pickup,
            new_dropoff=dropoff,
        )
    )


    assert len(candidates) == 3


# =========================================================
# 3. Two Existing Stops → 6 Candidates
# =========================================================

def test_two_existing_stops_generate_six_candidates():

    n1 = create_node("N1", 0, 0)
    n2 = create_node("N2", 1, 0)
    n3 = create_node("N3", 2, 0)
    n4 = create_node("N4", 3, 0)


    existing = [
        make_stop(
            group_key="A",
            passenger_count=1,
            node=n1,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),

        make_stop(
            group_key="A",
            passenger_count=1,
            node=n4,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),
    ]


    pickup = make_stop(
        group_key="B",
        passenger_count=1,
        node=n2,
        stop_type=(
            RouteStop.StopType.PICKUP
        ),
    )


    dropoff = make_stop(
        group_key="B",
        passenger_count=1,
        node=n3,
        stop_type=(
            RouteStop.StopType.DROPOFF
        ),
    )


    candidates = (
        SharedRouteInsertionService
        .generate_candidates(
            existing_stops=existing,
            new_pickup=pickup,
            new_dropoff=dropoff,
        )
    )


    assert len(candidates) == 6


# =========================================================
# 4. Formula Is Correct
# =========================================================

def test_candidate_count_formula():

    assert (
        SharedRouteInsertionService
        .expected_candidate_count(0)
        == 1
    )

    assert (
        SharedRouteInsertionService
        .expected_candidate_count(1)
        == 3
    )

    assert (
        SharedRouteInsertionService
        .expected_candidate_count(2)
        == 6
    )

    assert (
        SharedRouteInsertionService
        .expected_candidate_count(3)
        == 10
    )

    assert (
        SharedRouteInsertionService
        .expected_candidate_count(4)
        == 15
    )


# =========================================================
# 5. Existing Stop Order Must Be Preserved
# =========================================================

def test_existing_stop_order_is_preserved():

    nodes = [
        create_node(
            f"N{i}",
            i,
            0,
        )
        for i in range(1, 6)
    ]


    existing = [
        make_stop(
            group_key="A",
            passenger_count=1,
            node=nodes[0],
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),

        make_stop(
            group_key="A",
            passenger_count=1,
            node=nodes[3],
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),
    ]


    pickup = make_stop(
        group_key="B",
        passenger_count=1,
        node=nodes[1],
        stop_type=(
            RouteStop.StopType.PICKUP
        ),
    )


    dropoff = make_stop(
        group_key="B",
        passenger_count=1,
        node=nodes[2],
        stop_type=(
            RouteStop.StopType.DROPOFF
        ),
    )


    candidates = (
        SharedRouteInsertionService
        .generate_candidates(
            existing_stops=existing,
            new_pickup=pickup,
            new_dropoff=dropoff,
        )
    )


    for candidate in candidates:

        existing_in_candidate = [
            stop
            for stop in candidate.stops
            if stop.group_key == "A"
        ]

        assert (
            existing_in_candidate
            == existing
        )


# =========================================================
# 6. Pickup Always Before Dropoff
# =========================================================

def test_new_pickup_is_always_before_dropoff():

    n1 = create_node("N1", 0, 0)
    n2 = create_node("N2", 1, 0)
    n3 = create_node("N3", 2, 0)
    n4 = create_node("N4", 3, 0)


    existing = [
        make_stop(
            group_key="A",
            passenger_count=1,
            node=n1,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),

        make_stop(
            group_key="A",
            passenger_count=1,
            node=n4,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),
    ]


    pickup = make_stop(
        group_key="B",
        passenger_count=1,
        node=n2,
        stop_type=(
            RouteStop.StopType.PICKUP
        ),
    )


    dropoff = make_stop(
        group_key="B",
        passenger_count=1,
        node=n3,
        stop_type=(
            RouteStop.StopType.DROPOFF
        ),
    )


    candidates = (
        SharedRouteInsertionService
        .generate_candidates(
            existing_stops=existing,
            new_pickup=pickup,
            new_dropoff=dropoff,
        )
    )


    for candidate in candidates:

        pickup_position = (
            candidate.stops.index(
                pickup
            )
        )

        dropoff_position = (
            candidate.stops.index(
                dropoff
            )
        )

        assert (
            pickup_position
            < dropoff_position
        )


# =========================================================
# 7. Mismatched Group Keys Rejected
# =========================================================

def test_mismatched_group_keys_are_rejected():

    n1 = create_node("N1", 0, 0)
    n2 = create_node("N2", 1, 0)


    pickup = make_stop(
        group_key="B",
        passenger_count=1,
        node=n1,
        stop_type=(
            RouteStop.StopType.PICKUP
        ),
    )


    dropoff = make_stop(
        group_key="C",
        passenger_count=1,
        node=n2,
        stop_type=(
            RouteStop.StopType.DROPOFF
        ),
    )


    with pytest.raises(
        SharedRouteInsertionError
    ):
        (
            SharedRouteInsertionService
            .generate_candidates(
                existing_stops=[],
                new_pickup=pickup,
                new_dropoff=dropoff,
            )
        )


# =========================================================
# 8. Mismatched Passenger Counts Rejected
# =========================================================

def test_mismatched_passenger_counts_are_rejected():

    n1 = create_node("N1", 0, 0)
    n2 = create_node("N2", 1, 0)


    pickup = make_stop(
        group_key="B",
        passenger_count=2,
        node=n1,
        stop_type=(
            RouteStop.StopType.PICKUP
        ),
    )


    dropoff = make_stop(
        group_key="B",
        passenger_count=1,
        node=n2,
        stop_type=(
            RouteStop.StopType.DROPOFF
        ),
    )


    with pytest.raises(
        SharedRouteInsertionError
    ):
        (
            SharedRouteInsertionService
            .generate_candidates(
                existing_stops=[],
                new_pickup=pickup,
                new_dropoff=dropoff,
            )
        )


# =========================================================
# 9. Existing Passenger Cannot Be Inserted Again
# =========================================================

def test_existing_group_cannot_be_inserted_again():

    n1 = create_node("N1", 0, 0)
    n2 = create_node("N2", 1, 0)
    n3 = create_node("N3", 2, 0)


    existing = [
        make_stop(
            group_key="B",
            passenger_count=1,
            node=n3,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        )
    ]


    pickup = make_stop(
        group_key="B",
        passenger_count=1,
        node=n1,
        stop_type=(
            RouteStop.StopType.PICKUP
        ),
    )


    dropoff = make_stop(
        group_key="B",
        passenger_count=1,
        node=n2,
        stop_type=(
            RouteStop.StopType.DROPOFF
        ),
    )


    with pytest.raises(
        SharedRouteInsertionError
    ):
        (
            SharedRouteInsertionService
            .generate_candidates(
                existing_stops=existing,
                new_pickup=pickup,
                new_dropoff=dropoff,
            )
        )


# =========================================================
# 10. Complex Case:
# Some Insertions Fail Capacity,
# Another Insertion Succeeds
# =========================================================

def test_algorithm_finds_valid_alternative_after_capacity_failures():

    # Route:
    #
    # N1 → N2 → N3 → N4

    n1 = create_node("N1", 0, 0)
    n2 = create_node("N2", 1, 0)
    n3 = create_node("N3", 2, 0)
    n4 = create_node("N4", 3, 0)


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


    # Passenger A:
    # already onboard with 3 persons.
    #
    # Remaining stop:
    # Dropoff A at N2

    existing = [
        make_stop(
            group_key="A",
            passenger_count=3,
            node=n2,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        )
    ]


    # Passenger B = 2 persons

    pickup_b = make_stop(
        group_key="B",
        passenger_count=2,
        node=n3,
        stop_type=(
            RouteStop.StopType.PICKUP
        ),
    )


    dropoff_b = make_stop(
        group_key="B",
        passenger_count=2,
        node=n4,
        stop_type=(
            RouteStop.StopType.DROPOFF
        ),
    )


    evaluated = (
        SharedRouteInsertionService
        .evaluate_candidates(
            current_node=n1,

            vehicle_capacity=4,

            existing_stops=existing,

            new_pickup=pickup_b,

            new_dropoff=dropoff_b,

            initial_onboard={
                "A": 3,
            },
        )
    )


    # k = 1
    # بنابراین باید 3 candidate تولید شود.
    assert len(evaluated) == 3


    valid = [
        item
        for item in evaluated
        if item.simulation.is_valid
    ]


    invalid = [
        item
        for item in evaluated
        if not item.simulation.is_valid
    ]


    # دو حالت B را قبل از Dropoff A
    # Pickup می‌کنند:
    #
    # occupancy:
    # 3 + 2 = 5 > capacity 4
    #
    # پس رد می‌شوند.
    assert len(invalid) == 2


    # فقط این حالت feasible است:
    #
    # Dropoff A
    # → Pickup B
    # → Dropoff B
    assert len(valid) == 1


    valid_stops = (
        valid[0]
        .candidate
        .stops
    )


    assert (
        valid_stops[0].group_key
        == "A"
    )

    assert (
        valid_stops[0].stop_type
        == RouteStop.StopType.DROPOFF
    )


    assert (
        valid_stops[1]
        == pickup_b
    )


    assert (
        valid_stops[2]
        == dropoff_b
    )



# =========================================================
# 11. Third Active Assigned Group Rejected
# =========================================================

def test_third_active_assigned_group_is_rejected():

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


    # A الان داخل Taxi است.
    #
    # B هنوز Pickup نشده ولی در Route
    # assignment فعال دارد.

    existing = [

        make_stop(
            group_key="A",
            passenger_count=1,
            node=n2,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),

        make_stop(
            group_key="B",
            passenger_count=1,
            node=n3,
            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        ),

        make_stop(
            group_key="B",
            passenger_count=1,
            node=n4,
            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        ),
    ]


    pickup_c = make_stop(
        group_key="C",
        passenger_count=1,
        node=n2,
        stop_type=(
            RouteStop.StopType.PICKUP
        ),
    )


    dropoff_c = make_stop(
        group_key="C",
        passenger_count=1,
        node=n4,
        stop_type=(
            RouteStop.StopType.DROPOFF
        ),
    )


    with pytest.raises(
        SharedRouteInsertionError
    ):

        (
            SharedRouteInsertionService
            .generate_candidates(
                existing_stops=existing,

                new_pickup=pickup_c,

                new_dropoff=dropoff_c,

                initial_onboard={
                    "A": 1,
                },
            )
        )