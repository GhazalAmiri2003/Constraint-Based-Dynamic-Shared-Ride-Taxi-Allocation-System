from types import SimpleNamespace
from datetime import timedelta

import pytest

from django.test import (
    override_settings,
)
from django.utils import timezone

from road_network.models import (
    RoadEdge,
    RoadNode,
)
from shared_ride.models import (
    RouteStop,
)
from shared_ride.ranking import (
    SharedRouteRankingError,
    SharedRouteRankingService,
)
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
    time_minutes=2,
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


def make_baseline(
    *,
    direct_trip_time,
    expected_dropoff_at,
):
    return SimpleNamespace(
        direct_trip_time_minutes=(
            direct_trip_time
        ),

        baseline_expected_dropoff_at=(
            expected_dropoff_at
        ),
    )


def create_linear_network():
    """
    N1 --2--> N2 --2--> N3 --2--> N4
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

    n4 = create_node(
        "N4",
        3,
        0,
    )


    connect(
        n1,
        n2,
    )

    connect(
        n2,
        n3,
    )

    connect(
        n3,
        n4,
    )


    return (
        n1,
        n2,
        n3,
        n4,
    )


def create_shared_case():
    """
    Passenger A:
        already onboard
        Dropoff = N4

    Passenger B:
        Pickup = N2
        Dropoff = N3
    """

    (
        n1,
        n2,
        n3,
        n4,
    ) = create_linear_network()


    existing_stops = [
        make_stop(
            group_key="A",

            passenger_count=1,

            node=n4,

            stop_type=(
                RouteStop
                .StopType
                .DROPOFF
            ),
        )
    ]


    pickup_b = make_stop(
        group_key="B",

        passenger_count=1,

        node=n2,

        stop_type=(
            RouteStop
            .StopType
            .PICKUP
        ),
    )


    dropoff_b = make_stop(
        group_key="B",

        passenger_count=1,

        node=n3,

        stop_type=(
            RouteStop
            .StopType
            .DROPOFF
        ),
    )


    return (
        n1,
        existing_stops,
        pickup_b,
        dropoff_b,
    )


# =========================================================
# 1. Generate Multiple Candidates
# =========================================================

def test_ranking_evaluates_all_insertions():

    (
        n1,
        existing_stops,
        pickup_b,
        dropoff_b,
    ) = create_shared_case()


    now = timezone.now()


    result = (
        SharedRouteRankingService
        .evaluate_and_rank(
            current_node=n1,

            vehicle_capacity=4,

            existing_stops=(
                existing_stops
            ),

            new_pickup=(
                pickup_b
            ),

            new_dropoff=(
                dropoff_b
            ),

            initial_onboard={
                "A": 1,
            },

            existing_baselines={
                "A": make_baseline(
                    direct_trip_time=6,

                    expected_dropoff_at=(
                        now
                        + timedelta(
                            minutes=6
                        )
                    ),
                )
            },

            new_direct_trip_time_minutes=2,

            reference_time=now,
        )
    )


    # k = 1
    #
    # (k+1)(k+2)/2
    # = 3 candidates

    assert (
        result.generated_candidate_count
        == 3
    )


# =========================================================
# 2. Invalid Candidate Removed Before Ranking
# =========================================================

def test_constraint_invalid_candidate_not_ranked():

    (
        n1,
        existing_stops,
        pickup_b,
        dropoff_b,
    ) = create_shared_case()


    now = timezone.now()


    result = (
        SharedRouteRankingService
        .evaluate_and_rank(
            current_node=n1,

            vehicle_capacity=4,

            existing_stops=(
                existing_stops
            ),

            new_pickup=pickup_b,

            new_dropoff=dropoff_b,

            initial_onboard={
                "A": 1,
            },

            existing_baselines={
                "A": make_baseline(
                    direct_trip_time=6,

                    expected_dropoff_at=(
                        now
                        + timedelta(
                            minutes=6
                        )
                    ),
                )
            },

            new_direct_trip_time_minutes=2,

            reference_time=now,
        )
    )


    # Candidate:
    #
    # Pickup B
    # → Dropoff A
    # → Dropoff B
    #
    # B:
    # Direct = 2
    # Shared = 6
    # Detour = 4
    # Relative = 200%
    #
    # بنابراین reject.

    rejected_codes = []


    for evaluation in (
        result.candidate_evaluations
    ):

        if not evaluation.is_feasible:

            rejected_codes.extend(
                violation.code

                for violation
                in (
                    evaluation
                    .constraints
                    .violations
                )
            )


    assert (
        "NEW_PASSENGER_RELATIVE_DETOUR_EXCEEDED"
        in rejected_codes
    )


    assert (
        result.feasible_candidate_count
        == 2
    )


    assert (
        result.rejected_candidate_count
        == 1
    )


# =========================================================
# 3. Best Least-Disruptive Route Selected
# =========================================================

def test_least_disruptive_route_is_selected():

    (
        n1,
        existing_stops,
        pickup_b,
        dropoff_b,
    ) = create_shared_case()


    now = timezone.now()


    result = (
        SharedRouteRankingService
        .evaluate_and_rank(
            current_node=n1,

            vehicle_capacity=4,

            existing_stops=(
                existing_stops
            ),

            new_pickup=pickup_b,

            new_dropoff=dropoff_b,

            initial_onboard={
                "A": 1,
            },

            existing_baselines={
                "A": make_baseline(
                    direct_trip_time=6,

                    expected_dropoff_at=(
                        now
                        + timedelta(
                            minutes=6
                        )
                    ),
                )
            },

            new_direct_trip_time_minutes=2,

            reference_time=now,
        )
    )


    best = result.best_route


    assert best is not None

    assert best.rank == 1


    stops = (
        best.candidate.stops
    )


    # Best:
    #
    # Pickup B
    # → Dropoff B
    # → Dropoff A

    assert stops[0] == pickup_b

    assert stops[1] == dropoff_b

    assert (
        stops[2].group_key
        == "A"
    )

    assert (
        stops[2].stop_type
        == RouteStop.StopType.DROPOFF
    )


# =========================================================
# 4. Ranking Metrics Are Correct
# =========================================================

def test_best_route_metrics_are_correct():

    (
        n1,
        existing_stops,
        pickup_b,
        dropoff_b,
    ) = create_shared_case()


    now = timezone.now()


    result = (
        SharedRouteRankingService
        .evaluate_and_rank(
            current_node=n1,

            vehicle_capacity=4,

            existing_stops=(
                existing_stops
            ),

            new_pickup=pickup_b,

            new_dropoff=dropoff_b,

            initial_onboard={
                "A": 1,
            },

            existing_baselines={
                "A": make_baseline(
                    direct_trip_time=6,

                    expected_dropoff_at=(
                        now
                        + timedelta(
                            minutes=6
                        )
                    ),
                )
            },

            new_direct_trip_time_minutes=2,

            reference_time=now,
        )
    )


    metrics = (
        result
        .best_route
        .metrics
    )


    # Current route:
    # N1 → N4 = 6 min
    #
    # Best new route:
    # N1 → N2 → N3 → N4
    # = 6 min

    assert (
        metrics
        .additional_travel_time_minutes
        == 0
    )


    # A no delay
    # B no detour

    assert (
        metrics
        .total_passenger_delay_minutes
        == 0
    )


    # N1 → N2 = 2

    assert (
        metrics.pickup_wait_minutes
        == 2
    )


    # Current distance = 3 km
    # New distance = 3 km

    assert (
        metrics.route_extension_km
        == pytest.approx(0.0)
    )


# =========================================================
# 5. Feasible Routes Get Sequential Ranks
# =========================================================

def test_only_feasible_routes_receive_ranks():

    (
        n1,
        existing_stops,
        pickup_b,
        dropoff_b,
    ) = create_shared_case()


    now = timezone.now()


    result = (
        SharedRouteRankingService
        .evaluate_and_rank(
            current_node=n1,

            vehicle_capacity=4,

            existing_stops=(
                existing_stops
            ),

            new_pickup=pickup_b,

            new_dropoff=dropoff_b,

            initial_onboard={
                "A": 1,
            },

            existing_baselines={
                "A": make_baseline(
                    direct_trip_time=6,

                    expected_dropoff_at=(
                        now
                        + timedelta(
                            minutes=6
                        )
                    ),
                )
            },

            new_direct_trip_time_minutes=2,

            reference_time=now,
        )
    )


    ranks = [
        route.rank

        for route
        in result.feasible_routes
    ]


    assert ranks == [
        1,
        2,
    ]


# =========================================================
# 6. No Feasible Route
# =========================================================

@override_settings(
    MAX_SHARED_PICKUP_WAIT_MINUTES=1,
)
def test_no_feasible_route_returns_none():

    (
        n1,
        existing_stops,
        pickup_b,
        dropoff_b,
    ) = create_shared_case()


    now = timezone.now()


    result = (
        SharedRouteRankingService
        .evaluate_and_rank(
            current_node=n1,

            vehicle_capacity=4,

            existing_stops=(
                existing_stops
            ),

            new_pickup=pickup_b,

            new_dropoff=dropoff_b,

            initial_onboard={
                "A": 1,
            },

            existing_baselines={
                "A": make_baseline(
                    direct_trip_time=6,

                    expected_dropoff_at=(
                        now
                        + timedelta(
                            minutes=6
                        )
                    ),
                )
            },

            new_direct_trip_time_minutes=2,

            reference_time=now,
        )
    )


    assert (
        result.feasible_candidate_count
        == 0
    )

    assert (
        result.best_route is None
    )


# =========================================================
# 7. Missing Existing Baseline Rejected
# =========================================================

def test_missing_existing_passenger_baseline_rejected():

    (
        n1,
        existing_stops,
        pickup_b,
        dropoff_b,
    ) = create_shared_case()


    with pytest.raises(
        SharedRouteRankingError
    ):
        (
            SharedRouteRankingService
            .evaluate_and_rank(
                current_node=n1,

                vehicle_capacity=4,

                existing_stops=(
                    existing_stops
                ),

                new_pickup=pickup_b,

                new_dropoff=dropoff_b,

                initial_onboard={
                    "A": 1,
                },

                # A active است
                # ولی baseline ندارد.
                existing_baselines={},

                new_direct_trip_time_minutes=2,
            )
        )