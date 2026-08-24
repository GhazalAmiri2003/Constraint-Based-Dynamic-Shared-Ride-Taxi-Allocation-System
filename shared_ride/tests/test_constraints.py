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


# =========================================================
# Helpers
# =========================================================

def make_baseline(
    *,
    direct_trip_time,
    expected_dropoff_at,
):
    """
    برای این Unit Test لازم نیست
    Baseline واقعی در DB بسازیم.

    فقط Attributeهایی که Constraint Engine
    استفاده می‌کند لازم هستند.
    """

    return SimpleNamespace(
        direct_trip_time_minutes=(
            direct_trip_time
        ),

        baseline_expected_dropoff_at=(
            expected_dropoff_at
        ),
    )


def make_simulation(
    *,
    pickup_etas=None,
    dropoff_etas=None,
    is_valid=True,
    violations=None,
):
    if pickup_etas is None:
        pickup_etas = {}

    if dropoff_etas is None:
        dropoff_etas = {}

    if violations is None:
        violations = []


    return RouteSimulationResult(
        is_valid=is_valid,

        total_time_minutes=0,

        total_distance_km=0.0,

        violations=violations,

        pickup_eta_by_group=(
            pickup_etas
        ),

        dropoff_eta_by_group=(
            dropoff_etas
        ),
    )


# =========================================================
# 1. Fully Feasible Candidate
# =========================================================

@override_settings(
    MAX_SHARED_PICKUP_WAIT_MINUTES=10,
    MAX_SHARED_ABSOLUTE_DELAY_MINUTES=10,
    MAX_SHARED_RELATIVE_DELAY=0.30,
)
def test_fully_feasible_candidate():

    now = timezone.now()


    baseline_a = make_baseline(
        direct_trip_time=20,

        expected_dropoff_at=(
            now
            + timedelta(
                minutes=15
            )
        ),
    )


    simulation = make_simulation(
        pickup_etas={
            "B": 5,
        },

        dropoff_etas={
            # A arrives 5 min late
            "A": 20,

            # B:
            # pickup 5
            # dropoff 20
            # shared trip = 15
            "B": 20,
        },
    )


    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=simulation,

            existing_baselines={
                "A": baseline_a,
            },

            new_group_key="B",

            new_direct_trip_time_minutes=15,

            reference_time=now,
        )
    )


    assert result.is_feasible is True

    assert result.violations == []


# =========================================================
# 2. Exact Relative Delay Limit Accepted
# =========================================================

@override_settings(
    MAX_SHARED_ABSOLUTE_DELAY_MINUTES=10,
    MAX_SHARED_RELATIVE_DELAY=0.30,
)
def test_exact_30_percent_relative_delay_is_allowed():

    now = timezone.now()


    baseline = make_baseline(
        direct_trip_time=20,

        expected_dropoff_at=(
            now
            + timedelta(
                minutes=10
            )
        ),
    )


    # Candidate dropoff at minute 16
    #
    # Absolute delay = 6
    # Relative = 6 / 20 = 30%

    simulation = make_simulation(
        pickup_etas={
            "B": 1,
        },

        dropoff_etas={
            "A": 16,
            "B": 11,
        },
    )


    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=simulation,

            existing_baselines={
                "A": baseline,
            },

            new_group_key="B",

            new_direct_trip_time_minutes=10,

            reference_time=now,
        )
    )


    assert result.is_feasible is True


# =========================================================
# 3. Relative Delay > 30% Rejected
# =========================================================

@override_settings(
    MAX_SHARED_ABSOLUTE_DELAY_MINUTES=10,
    MAX_SHARED_RELATIVE_DELAY=0.30,
)
def test_relative_delay_over_30_percent_is_rejected():

    now = timezone.now()


    baseline = make_baseline(
        direct_trip_time=20,

        expected_dropoff_at=(
            now
            + timedelta(
                minutes=10
            )
        ),
    )


    # Absolute delay = 7
    # Relative = 7 / 20 = 35%

    simulation = make_simulation(
        pickup_etas={
            "B": 1,
        },

        dropoff_etas={
            "A": 17,
            "B": 11,
        },
    )


    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=simulation,

            existing_baselines={
                "A": baseline,
            },

            new_group_key="B",

            new_direct_trip_time_minutes=10,

            reference_time=now,
        )
    )


    codes = [
        violation.code
        for violation
        in result.violations
    ]


    assert result.is_feasible is False

    assert (
        "RELATIVE_DELAY_EXCEEDED"
        in codes
    )


# =========================================================
# 4. Absolute Delay > 10 min Rejected
# =========================================================

@override_settings(
    MAX_SHARED_ABSOLUTE_DELAY_MINUTES=10,
    MAX_SHARED_RELATIVE_DELAY=1.0,
)
def test_absolute_delay_over_10_minutes_is_rejected():

    now = timezone.now()


    baseline = make_baseline(
        direct_trip_time=100,

        expected_dropoff_at=(
            now
            + timedelta(
                minutes=10
            )
        ),
    )


    # Delay = 11 minutes.
    #
    # Relative delay = 11%
    # so only absolute constraint should fail.

    simulation = make_simulation(
        pickup_etas={
            "B": 1,
        },

        dropoff_etas={
            "A": 21,
            "B": 11,
        },
    )


    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=simulation,

            existing_baselines={
                "A": baseline,
            },

            new_group_key="B",

            new_direct_trip_time_minutes=10,

            reference_time=now,
        )
    )


    codes = [
        violation.code
        for violation
        in result.violations
    ]


    assert result.is_feasible is False

    assert (
        "ABSOLUTE_DELAY_EXCEEDED"
        in codes
    )


# =========================================================
# 5. Early Arrival Has Zero Delay
# =========================================================

def test_early_existing_passenger_arrival_has_zero_delay():

    now = timezone.now()


    baseline = make_baseline(
        direct_trip_time=20,

        expected_dropoff_at=(
            now
            + timedelta(
                minutes=20
            )
        ),
    )


    simulation = make_simulation(
        pickup_etas={
            "B": 1,
        },

        dropoff_etas={
            # Candidate arrives earlier
            "A": 15,

            "B": 11,
        },
    )


    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=simulation,

            existing_baselines={
                "A": baseline,
            },

            new_group_key="B",

            new_direct_trip_time_minutes=10,

            reference_time=now,
        )
    )


    delay = (
        result
        .existing_passenger_delays[
            "A"
        ]
    )


    assert (
        delay.absolute_delay_minutes
        == 0
    )

    assert (
        delay.relative_delay
        == 0
    )


# =========================================================
# 6. Pickup Wait Too High
# =========================================================

@override_settings(
    MAX_SHARED_PICKUP_WAIT_MINUTES=10,
)
def test_new_passenger_pickup_wait_over_limit_rejected():

    simulation = make_simulation(
        pickup_etas={
            "B": 11,
        },

        dropoff_etas={
            "B": 21,
        },
    )


    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=simulation,

            existing_baselines={},

            new_group_key="B",

            new_direct_trip_time_minutes=10,
        )
    )


    codes = [
        violation.code
        for violation
        in result.violations
    ]


    assert result.is_feasible is False

    assert (
        "PICKUP_WAIT_EXCEEDED"
        in codes
    )


# =========================================================
# 7. Exact Pickup Wait Limit Accepted
# =========================================================

@override_settings(
    MAX_SHARED_PICKUP_WAIT_MINUTES=10,
)
def test_exact_pickup_wait_limit_is_allowed():

    simulation = make_simulation(
        pickup_etas={
            "B": 10,
        },

        dropoff_etas={
            "B": 20,
        },
    )


    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=simulation,

            existing_baselines={},

            new_group_key="B",

            new_direct_trip_time_minutes=10,
        )
    )


    assert result.is_feasible is True


# =========================================================
# 8. New Passenger Relative Detour Rejected
# =========================================================

@override_settings(
    MAX_SHARED_PICKUP_WAIT_MINUTES=10,
    MAX_SHARED_ABSOLUTE_DELAY_MINUTES=10,
    MAX_SHARED_RELATIVE_DELAY=0.30,
)
def test_new_passenger_relative_detour_rejected():

    # Direct = 10
    #
    # Shared:
    # Pickup = 2
    # Dropoff = 16
    #
    # In-vehicle = 14
    # Detour = 4
    # Relative = 40%

    simulation = make_simulation(
        pickup_etas={
            "B": 2,
        },

        dropoff_etas={
            "B": 16,
        },
    )


    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=simulation,

            existing_baselines={},

            new_group_key="B",

            new_direct_trip_time_minutes=10,
        )
    )


    codes = [
        violation.code
        for violation
        in result.violations
    ]


    assert result.is_feasible is False

    assert (
        "NEW_PASSENGER_RELATIVE_DETOUR_EXCEEDED"
        in codes
    )


# =========================================================
# 9. New Passenger Absolute Detour Rejected
# =========================================================

@override_settings(
    MAX_SHARED_PICKUP_WAIT_MINUTES=10,
    MAX_SHARED_ABSOLUTE_DELAY_MINUTES=10,
    MAX_SHARED_RELATIVE_DELAY=10.0,
)
def test_new_passenger_absolute_detour_rejected():

    # Direct = 5
    #
    # Shared trip:
    # 20 - 2 = 18
    #
    # Detour:
    # 18 - 5 = 13 > 10

    simulation = make_simulation(
        pickup_etas={
            "B": 2,
        },

        dropoff_etas={
            "B": 20,
        },
    )


    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=simulation,

            existing_baselines={},

            new_group_key="B",

            new_direct_trip_time_minutes=5,
        )
    )


    codes = [
        violation.code
        for violation
        in result.violations
    ]


    assert result.is_feasible is False

    assert (
        "NEW_PASSENGER_ABSOLUTE_DETOUR_EXCEEDED"
        in codes
    )


# =========================================================
# 10. Invalid Simulation Rejected Immediately
# =========================================================

def test_invalid_simulation_is_never_feasible():

    simulation = make_simulation(
        is_valid=False,

        violations=[
            "CAPACITY_EXCEEDED:B"
        ],
    )


    result = (
        SharedConstraintEvaluationService
        .evaluate(
            simulation=simulation,

            existing_baselines={},

            new_group_key="B",

            new_direct_trip_time_minutes=10,
        )
    )


    assert result.is_feasible is False

    assert len(result.violations) == 1

    assert (
        result.violations[0].code
        == "SIMULATION_INVALID"
    )