from types import SimpleNamespace

import pytest

from django.contrib.auth.models import User
from django.utils import timezone

from accounts.models import (
    PassengerProfile,
    UserProfile,
)
from assignment.services import (
    AssignmentService,
)
from assignment.shared_services import (
    SharedTaxiOptionService,
)
from recovery.planning import (
    RecoveryPlanService,
)
from recovery.services import (
    AffectedPassengerGroup,
)
from rides.models import (
    RideRequest,
)
from road_network.models import (
    RoadNode,
)


pytestmark = pytest.mark.django_db


# =========================================================
# Helpers
# =========================================================

def create_node(
    name,
    x,
):

    return RoadNode.objects.create(
        name=name,
        x=x,
        y=0,
    )


def create_passenger(
    username,
):

    user = User.objects.create_user(
        username=username,
        password="StrongPass123!",
    )


    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.PASSENGER,
    )


    return PassengerProfile.objects.create(
        user=user
    )


def create_request(
    *,
    username,
    ride_type,
    pickup,
    destination,
):

    passenger = create_passenger(
        username
    )


    return RideRequest.objects.create(

        passenger=passenger,

        ride_type=ride_type,

        passenger_count=1,

        pickup_node=pickup,

        destination_node=destination,

        status=(
            RideRequest.Status.ASSIGNED
        ),
    )


def create_group(
    ride_request,
    ride_passenger_id,
    pickup_slack_minutes=10.0,
):

    return AffectedPassengerGroup(

        ride_passenger_id=(
            ride_passenger_id
        ),

        ride_request_id=(
            ride_request.id
        ),

        ride_type=(
            ride_request.ride_type
        ),

        passenger_count=(
            ride_request.passenger_count
        ),

        pickup_node_id=(
            ride_request.pickup_node_id
        ),

        destination_node_id=(
            ride_request.destination_node_id
        ),

        original_request_time=(
            ride_request.created_at
        ),

        pickup_slack_minutes=(
            pickup_slack_minutes
        ),
    )


# =========================================================
# 1. PRIVATE Recovery reuses AssignmentService
# =========================================================

def test_private_recovery_reuses_private_assignment_engine(
    monkeypatch,
):

    n1 = create_node(
        "PRIVATE_PLAN_N1",
        1,
    )

    n2 = create_node(
        "PRIVATE_PLAN_N2",
        2,
    )


    ride_request = create_request(

        username="private_plan_passenger",

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        pickup=n1,

        destination=n2,
    )


    group = create_group(
        ride_request,
        ride_passenger_id=101,
        pickup_slack_minutes=10,
    )


    called = {
        "value": False,
    }


    def fake_private_engine(
        request,
    ):

        called["value"] = True

        # Recovery must NOT save PENDING to DB.
        assert (
            request.status
            == RideRequest.Status.PENDING
        )

        return [

            SimpleNamespace(
                rank=1,
                vehicle_id=50,
                pickup_eta_minutes=2,
            ),

            SimpleNamespace(
                rank=2,
                vehicle_id=60,
                pickup_eta_minutes=4,
            ),
        ]


    monkeypatch.setattr(

        AssignmentService,

        "generate_private_taxi_options",

        staticmethod(
            fake_private_engine
        ),
    )


    candidates = (
        RecoveryPlanService
        .generate_candidates_for_group(
            group=group,
            failed_vehicle_id=50,
        )
    )


    assert called["value"] is True

    # Vehicle 50 was the failed vehicle.
    assert len(candidates) == 1

    assert (
        candidates[0].vehicle_id
        == 60
    )


    # Database state must still be ASSIGNED.
    ride_request.refresh_from_db()

    assert (
        ride_request.status
        == RideRequest.Status.ASSIGNED
    )


# =========================================================
# 2. SHARED Recovery reuses SharedTaxiOptionService
# =========================================================

def test_shared_recovery_reuses_shared_assignment_engine(
    monkeypatch,
):

    n1 = create_node(
        "SHARED_PLAN_N1",
        1,
    )

    n2 = create_node(
        "SHARED_PLAN_N2",
        2,
    )


    ride_request = create_request(

        username="shared_plan_passenger",

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        pickup=n1,

        destination=n2,
    )


    group = create_group(
        ride_request,
        ride_passenger_id=201,
        pickup_slack_minutes=10,
    )


    called = {
        "value": False,
    }


    def fake_shared_engine(
        request,
    ):

        called["value"] = True

        return [

            SimpleNamespace(
                rank=1,
                vehicle_id=70,
                pickup_eta_minutes=3,

                # Existing Shared Ride disruption
                total_passenger_delay_minutes=2,
            )
        ]


    monkeypatch.setattr(

        SharedTaxiOptionService,

        "generate_shared_taxi_options",

        staticmethod(
            fake_shared_engine
        ),
    )


    candidates = (
        RecoveryPlanService
        .generate_candidates_for_group(
            group=group,
            failed_vehicle_id=999,
        )
    )


    assert called["value"] is True

    assert len(candidates) == 1

    assert (
        candidates[0].vehicle_id
        == 70
    )


    # 3 pickup ETA + 2 shared disruption
    assert (
        candidates[0]
        .additional_delay_minutes
        == 5
    )


# =========================================================
# 3. Recovery uses remaining ORIGINAL pickup budget
# =========================================================

def test_recovery_rejects_option_beyond_remaining_pickup_budget(
    monkeypatch,
):

    n1 = create_node(
        "WAIT_PLAN_N1",
        1,
    )

    n2 = create_node(
        "WAIT_PLAN_N2",
        2,
    )


    ride_request = create_request(

        username="wait_plan_passenger",

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        pickup=n1,

        destination=n2,
    )


    # Passenger has only 3 minutes remaining.
    group = create_group(
        ride_request,
        ride_passenger_id=301,
        pickup_slack_minutes=3,
    )


    def fake_private_engine(
        request,
    ):

        return [

            SimpleNamespace(
                rank=1,
                vehicle_id=80,

                # Normal Assignment Engine would allow it
                # because 4 <= normal max 10.
                #
                # Recovery must reject because only
                # 3 minutes remain.
                pickup_eta_minutes=4,
            )
        ]


    monkeypatch.setattr(

        AssignmentService,

        "generate_private_taxi_options",

        staticmethod(
            fake_private_engine
        ),
    )


    candidates = (
        RecoveryPlanService
        .generate_candidates_for_group(
            group=group,
            failed_vehicle_id=999,
        )
    )


    assert candidates == []


# =========================================================
# 4. Prefer plan that recovers BOTH groups
# =========================================================

def test_recovery_prefers_plan_recovering_greatest_number(
    monkeypatch,
):

    n1 = create_node(
        "COUNT_PLAN_N1",
        1,
    )

    n2 = create_node(
        "COUNT_PLAN_N2",
        2,
    )


    request_one = create_request(

        username="count_passenger_one",

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        pickup=n1,

        destination=n2,
    )


    request_two = create_request(

        username="count_passenger_two",

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        pickup=n1,

        destination=n2,
    )


    group_one = create_group(
        request_one,
        ride_passenger_id=401,
    )

    group_two = create_group(
        request_two,
        ride_passenger_id=402,
    )


    def fake_private_engine(
        request,
    ):

        if request.id == request_one.id:

            return [
                SimpleNamespace(
                    rank=1,
                    vehicle_id=10,
                    pickup_eta_minutes=2,
                )
            ]


        return [
            SimpleNamespace(
                rank=1,
                vehicle_id=20,
                pickup_eta_minutes=3,
            )
        ]


    monkeypatch.setattr(

        AssignmentService,

        "generate_private_taxi_options",

        staticmethod(
            fake_private_engine
        ),
    )


    result = (
        RecoveryPlanService
        .generate_recovery_plans(
            affected_groups=[
                group_one,
                group_two,
            ],
            failed_vehicle_id=999,
        )
    )


    assert (
        result.best_plan
        is not None
    )

    assert (
        result.best_plan
        .recovered_group_count
        == 2
    )

    assert set(
        result.best_plan.vehicle_ids
    ) == {
        10,
        20,
    }


# =========================================================
# 5. Lowest additional delay wins
# =========================================================

def test_recovery_selects_lowest_delay_plan(
    monkeypatch,
):

    n1 = create_node(
        "DELAY_PLAN_N1",
        1,
    )

    n2 = create_node(
        "DELAY_PLAN_N2",
        2,
    )


    request_one = create_request(

        username="delay_passenger_one",

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        pickup=n1,

        destination=n2,
    )


    request_two = create_request(

        username="delay_passenger_two",

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        pickup=n1,

        destination=n2,
    )


    group_one = create_group(
        request_one,
        ride_passenger_id=501,
    )

    group_two = create_group(
        request_two,
        ride_passenger_id=502,
    )


    def fake_private_engine(
        request,
    ):

        if request.id == request_one.id:

            return [

                SimpleNamespace(
                    rank=1,
                    vehicle_id=11,
                    pickup_eta_minutes=1,
                ),

                SimpleNamespace(
                    rank=2,
                    vehicle_id=12,
                    pickup_eta_minutes=5,
                ),
            ]


        return [

            SimpleNamespace(
                rank=1,
                vehicle_id=21,
                pickup_eta_minutes=1,
            ),

            SimpleNamespace(
                rank=2,
                vehicle_id=22,
                pickup_eta_minutes=5,
            ),
        ]


    monkeypatch.setattr(

        AssignmentService,

        "generate_private_taxi_options",

        staticmethod(
            fake_private_engine
        ),
    )


    result = (
        RecoveryPlanService
        .generate_recovery_plans(
            affected_groups=[
                group_one,
                group_two,
            ],
            failed_vehicle_id=999,
        )
    )


    best_plan = (
        result.best_plan
    )


    assert (
        best_plan
        .recovered_group_count
        == 2
    )


    assert (
        best_plan
        .total_additional_delay_minutes
        == 2
    )


    assert set(
        best_plan.vehicle_ids
    ) == {
        11,
        21,
    }


# =========================================================
# 6. If only one group can be recovered,
#    passenger priority wins
# =========================================================

def test_recovery_priority_wins_when_only_one_group_can_be_recovered(
    monkeypatch,
):

    n1 = create_node(
        "PRIORITY_PLAN_N1",
        1,
    )

    n2 = create_node(
        "PRIORITY_PLAN_N2",
        2,
    )


    urgent_request = create_request(

        username="urgent_recovery_passenger",

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        pickup=n1,

        destination=n2,
    )


    less_urgent_request = create_request(

        username="less_urgent_recovery_passenger",

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        pickup=n1,

        destination=n2,
    )


    now = timezone.now()


    urgent_group = (
        AffectedPassengerGroup(

            ride_passenger_id=601,

            ride_request_id=(
                urgent_request.id
            ),

            ride_type=(
                urgent_request.ride_type
            ),

            passenger_count=1,

            pickup_node_id=n1.id,

            destination_node_id=n2.id,

            original_request_time=(
                now
            ),

            pickup_slack_minutes=2,
        )
    )


    less_urgent_group = (
        AffectedPassengerGroup(

            ride_passenger_id=602,

            ride_request_id=(
                less_urgent_request.id
            ),

            ride_type=(
                less_urgent_request
                .ride_type
            ),

            passenger_count=1,

            pickup_node_id=n1.id,

            destination_node_id=n2.id,

            original_request_time=(
                now
            ),

            pickup_slack_minutes=8,
        )
    )


    def fake_private_engine(
        request,
    ):

        if request.id == urgent_request.id:

            return [
                SimpleNamespace(
                    rank=1,
                    vehicle_id=30,
                    pickup_eta_minutes=2,
                )
            ]


        # Same taxi.
        #
        # Therefore both passengers cannot be placed
        # in the same Recovery transaction.
        return [
            SimpleNamespace(
                rank=1,
                vehicle_id=30,
                pickup_eta_minutes=1,
            )
        ]


    monkeypatch.setattr(

        AssignmentService,

        "generate_private_taxi_options",

        staticmethod(
            fake_private_engine
        ),
    )


    result = (
        RecoveryPlanService
        .generate_recovery_plans(
            affected_groups=[
                less_urgent_group,
                urgent_group,
            ],
            failed_vehicle_id=999,
        )
    )


    # There is no valid two-group plan.
    assert (
        result.best_plan
        .recovered_group_count
        == 1
    )


    recovered_request_id = (
        result
        .best_plan
        .assignments[0]
        .ride_request_id
    )


    assert (
        recovered_request_id
        == urgent_request.id
    )