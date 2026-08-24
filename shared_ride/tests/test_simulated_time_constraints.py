from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.test import override_settings
from django.utils import timezone

from shared_ride.constraints import (
    SharedConstraintEvaluationService,
)
from shared_ride.simulation import (
    RouteSimulationResult,
)


def make_simulation(
    *,
    existing_dropoff,
    new_pickup=2,
    new_dropoff=7,
):
    return RouteSimulationResult(
        is_valid=True,
        total_time_minutes=max(
            existing_dropoff,
            new_dropoff,
        ),
        total_distance_km=1.0,
        pickup_eta_by_group={
            "request:2": new_pickup,
        },
        dropoff_eta_by_group={
            "rp:1": existing_dropoff,
            "request:2": new_dropoff,
        },
    )


@override_settings(
    MAX_SHARED_PICKUP_WAIT_MINUTES=10,
    MAX_SHARED_ABSOLUTE_DELAY_MINUTES=10,
    MAX_SHARED_RELATIVE_DELAY=0.30,
)
def test_real_wall_clock_wait_does_not_reject_simulated_shared_insertion():
    """
    The existing passenger's stored absolute baseline may be old in
    real time, but the simulator must compare candidate ETA against
    the current route ETA from the same taxi position.
    """

    baseline = SimpleNamespace(
        direct_trip_time_minutes=10,

        # Deliberately one day old.
        baseline_expected_dropoff_at=(
            timezone.now()
            - timedelta(days=1)
        ),
    )

    baseline_route = RouteSimulationResult(
        is_valid=True,
        total_time_minutes=10,
        total_distance_km=1.0,
        dropoff_eta_by_group={
            "rp:1": 10,
        },
    )

    candidate = make_simulation(
        existing_dropoff=12,
    )

    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=candidate,

            existing_baselines={
                "rp:1": baseline,
            },

            new_group_key=(
                "request:2"
            ),

            new_direct_trip_time_minutes=5,

            reference_time=(
                timezone.now()
            ),

            baseline_simulation=(
                baseline_route
            ),
        )
    )

    assert result.is_feasible is True

    delay = (
        result
        .existing_passenger_delays[
            "rp:1"
        ]
    )

    assert (
        delay.absolute_delay_minutes
        == pytest.approx(2.0)
    )

    assert (
        delay.relative_delay
        == pytest.approx(0.20)
    )


@override_settings(
    MAX_SHARED_PICKUP_WAIT_MINUTES=10,
    MAX_SHARED_ABSOLUTE_DELAY_MINUTES=10,
    MAX_SHARED_RELATIVE_DELAY=0.30,
)
def test_simulated_relative_delay_is_still_enforced():
    baseline = SimpleNamespace(
        direct_trip_time_minutes=10,
        baseline_expected_dropoff_at=(
            timezone.now()
        ),
    )

    baseline_route = RouteSimulationResult(
        is_valid=True,
        total_time_minutes=10,
        total_distance_km=1.0,
        dropoff_eta_by_group={
            "rp:1": 10,
        },
    )

    # +4 minutes on a 10-minute direct trip = 40% > 30%.
    candidate = make_simulation(
        existing_dropoff=14,
    )

    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=candidate,

            existing_baselines={
                "rp:1": baseline,
            },

            new_group_key=(
                "request:2"
            ),

            new_direct_trip_time_minutes=5,

            baseline_simulation=(
                baseline_route
            ),
        )
    )

    assert result.is_feasible is False

    codes = {
        violation.code
        for violation
        in result.violations
    }

    assert (
        "RELATIVE_DELAY_EXCEEDED"
        in codes
    )
