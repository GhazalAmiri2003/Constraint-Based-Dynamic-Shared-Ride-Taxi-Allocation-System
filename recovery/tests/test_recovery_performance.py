import time
from datetime import timedelta

import pytest

from django.contrib.auth.models import User
from django.utils import timezone

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from fleet.models import Vehicle

from recovery.models import (
    RecoveryEvent,
)
from recovery.orchestrator import (
    RecoveryOrchestrator,
)
from recovery.planning import (
    RecoveryPlanService,
)
from recovery.services import (
    RecoveryDetectionService,
)

from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)

from road_network.models import (
    RoadEdge,
    RoadNode,
)

from shared_ride.models import (
    Route,
    RouteStop,
    SharedPassengerBaseline,
)


pytestmark = pytest.mark.django_db


# =========================================================
# Road Network
# =========================================================

def create_network():
    """
    Create a road network with exactly 20 nodes.

    Structure:

    N1 -- N2 -- N3 -- ... -- N20

    Every edge is bidirectional.

    This gives the routing engine enough nodes to perform
    multiple Dijkstra shortest-path calculations during
    Shared Ride feasibility evaluation.
    """

    nodes = []


    # =====================================================
    # Create 20 Nodes
    # =====================================================

    for index in range(
        1,
        21,
    ):

        node = (
            RoadNode.objects.create(
                name=f"REC_PERF_N{index}",
                x=index,
                y=0,
            )
        )


        nodes.append(
            node
        )


    # =====================================================
    # Connect Nodes
    # =====================================================

    for index in range(
        len(nodes) - 1
    ):

        RoadEdge.objects.create(

            from_node=(
                nodes[index]
            ),

            to_node=(
                nodes[index + 1]
            ),

            distance_km=1.0,

            travel_time_minutes=1,

            road_type=(
                RoadEdge.RoadType.LOCAL
            ),

            is_bidirectional=True,
        )


    return nodes


# =========================================================
# Passenger
# =========================================================

def create_passenger(
    username,
):
    """
    Create Passenger User + UserProfile + PassengerProfile.
    """

    user = (
        User.objects.create_user(
            username=username,
            password="StrongPass123!",
        )
    )


    UserProfile.objects.create(

        user=user,

        role=(
            UserProfile.Role.PASSENGER
        ),
    )


    passenger = (
        PassengerProfile.objects.create(
            user=user
        )
    )


    return passenger


# =========================================================
# Vehicle
# =========================================================

def create_vehicle(
    *,
    username,
    current_node,
):
    """
    Create an ONLINE Driver with an available SHARED taxi.
    """

    user = (
        User.objects.create_user(
            username=username,
            password="StrongPass123!",
        )
    )


    UserProfile.objects.create(

        user=user,

        role=(
            UserProfile.Role.DRIVER
        ),
    )


    driver = (
        DriverProfile.objects.create(

            user=user,

            availability_status=(
                DriverProfile
                .AvailabilityStatus
                .ONLINE
            ),
        )
    )


    vehicle = (
        Vehicle.objects.create(

            driver=driver,

            capacity=4,

            is_available=True,

            ride_mode=(
                Vehicle.RideMode.SHARED
            ),

            current_node=(
                current_node
            ),
        )
    )


    return vehicle


# =========================================================
# Shared Ride Request
# =========================================================

def create_shared_request(
    *,
    username,
    pickup_node,
    destination_node,
    status=RideRequest.Status.ASSIGNED,
):
    """
    Create one SHARED RideRequest with one passenger.
    """

    passenger = (
        create_passenger(
            username
        )
    )


    ride_request = (
        RideRequest.objects.create(

            passenger=passenger,

            ride_type=(
                RideRequest
                .RideType
                .SHARED
            ),

            passenger_count=1,

            pickup_node=(
                pickup_node
            ),

            destination_node=(
                destination_node
            ),

            status=status,
        )
    )


    return ride_request


# =========================================================
# Active Shared Taxi
# =========================================================

def create_active_shared_taxi(
    *,
    taxi_index,
    current_node,
    pickup_node,
    destination_node,
    group_count,
):
    """
    Create an active SHARED taxi.

    group_count = 1
        Taxi currently has one Passenger Group.
        Therefore it can potentially accept one recovered
        Passenger Group.

    group_count = 2
        Taxi already has the maximum allowed number
        of Passenger Groups.

        Recovery should reject it as a replacement
        candidate.
    """

    # =====================================================
    # Vehicle
    # =====================================================

    vehicle = (
        create_vehicle(

            username=(
                f"recovery_perf_driver_"
                f"{taxi_index}"
            ),

            current_node=(
                current_node
            ),
        )
    )


    # =====================================================
    # Operational Shared Ride
    # =====================================================

    ride = (
        Ride.objects.create(

            vehicle=vehicle,

            ride_type=(
                RideRequest
                .RideType
                .SHARED
            ),

            status=(
                Ride.Status.ACCEPTED
            ),
        )
    )


    # =====================================================
    # Active Route
    # =====================================================

    route = (
        Route.objects.create(

            ride=ride,

            status=(
                Route.Status.ACTIVE
            ),

            revision=1,

            total_estimated_time_minutes=4,

            total_estimated_distance_km=4,
        )
    )


    memberships = []


    # =====================================================
    # Passenger Groups
    # =====================================================

    for group_index in range(
        1,
        group_count + 1,
    ):

        request = (
            create_shared_request(

                username=(
                    f"recovery_perf_"
                    f"passenger_"
                    f"{taxi_index}_"
                    f"{group_index}"
                ),

                pickup_node=(
                    pickup_node
                ),

                destination_node=(
                    destination_node
                ),
            )
        )


        membership = (
            RidePassenger.objects.create(

                ride=ride,

                ride_request=request,
            )
        )


        memberships.append(
            membership
        )


        # =================================================
        # Immutable Passenger Baseline
        # =================================================

        SharedPassengerBaseline.objects.create(

            ride_passenger=(
                membership
            ),

            # N2 -> N5
            # 3 edges × 1 minute
            direct_trip_time_minutes=3,

            baseline_expected_dropoff_at=(
                timezone.now()
                + timedelta(
                    minutes=4
                )
            ),

            baseline_route_revision=1,
        )


    # =====================================================
    # Ordered Pickup Stops
    # =====================================================

    sequence = 1


    for membership in memberships:

        RouteStop.objects.create(

            route=route,

            ride_passenger=(
                membership
            ),

            node=(
                pickup_node
            ),

            stop_type=(
                RouteStop
                .StopType
                .PICKUP
            ),

            sequence_number=(
                sequence
            ),

            estimated_arrival_minutes=1,

            status=(
                RouteStop
                .Status
                .PENDING
            ),
        )


        sequence += 1


    # =====================================================
    # Ordered Dropoff Stops
    # =====================================================

    for membership in memberships:

        RouteStop.objects.create(

            route=route,

            ride_passenger=(
                membership
            ),

            node=(
                destination_node
            ),

            stop_type=(
                RouteStop
                .StopType
                .DROPOFF
            ),

            sequence_number=(
                sequence
            ),

            estimated_arrival_minutes=4,

            status=(
                RouteStop
                .Status
                .PENDING
            ),
        )


        sequence += 1


    return (
        vehicle,
        ride,
        route,
        memberships,
    )


# =========================================================
# Failed Shared Taxi
# =========================================================

def create_failed_shared_taxi(
    *,
    current_node,
    pickup_node,
    destination_node,
):
    """
    Create one failed Shared Taxi.

    It contains exactly TWO waiting Passenger Groups.

    Both Pickup RouteStops remain PENDING.

    Therefore both groups are eligible for
    pre-pickup Recovery.
    """

    (
        vehicle,
        ride,
        route,
        memberships,
    ) = (
        create_active_shared_taxi(

            taxi_index=0,

            current_node=(
                current_node
            ),

            pickup_node=(
                pickup_node
            ),

            destination_node=(
                destination_node
            ),

            group_count=2,
        )
    )


    # =====================================================
    # Simulate Driver Reject
    #
    # Old Ride becomes historical REJECTED.
    # =====================================================

    ride.status = (
        Ride.Status.REJECTED
    )


    ride.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )


    # =====================================================
    # Failed Taxi is released
    # =====================================================

    vehicle.ride_mode = (
        Vehicle.RideMode.IDLE
    )


    vehicle.save(
        update_fields=[
            "ride_mode",
            "updated_at",
        ]
    )


    # =====================================================
    # RideRequests become PENDING for Recovery
    # =====================================================

    request_ids = [

        membership.ride_request_id

        for membership
        in memberships
    ]


    (
        RideRequest.objects
        .filter(
            id__in=request_ids
        )
        .update(

            status=(
                RideRequest
                .Status
                .PENDING
            ),

            updated_at=(
                timezone.now()
            ),
        )
    )


    return (
        vehicle,
        ride,
        route,
        memberships,
    )


# =========================================================
# Performance Test
# =========================================================

def test_recovery_under_two_seconds_with_ten_active_taxis():
    """
    Increment 5 Performance Scenario.

    Scenario:

    - 20 Road Nodes
    - 10 Taxis total
    - Maximum 2 active Passenger Groups / Taxi
    - Failed Shared Taxi contains 2 affected groups
    - 2 taxis can accept replacements
    - 7 taxis are already saturated
    - Dynamic Shared Route insertion is evaluated
    - Dijkstra routing is executed
    - Constraints are checked
    - Recovery plans are generated and ranked

    Formal performance target:

        Recovery Planning <= 2 seconds

    Full transactional Recovery is also executed afterwards
    for integration validation, but its execution time is
    reported separately.
    """

    # =====================================================
    # 1. Create 20-node Road Network
    # =====================================================

    nodes = (
        create_network()
    )


    current_node = (
        nodes[0]
    )  # N1


    pickup_node = (
        nodes[1]
    )  # N2


    destination_node = (
        nodes[4]
    )  # N5


    # =====================================================
    # 2. Failed Taxi
    #
    # Taxi #0:
    #
    # - Failed
    # - 2 affected Passenger Groups
    # =====================================================

    (
        failed_vehicle,
        failed_ride,
        _,
        _,
    ) = (
        create_failed_shared_taxi(

            current_node=(
                current_node
            ),

            pickup_node=(
                pickup_node
            ),

            destination_node=(
                destination_node
            ),
        )
    )


    # =====================================================
    # 3. Two Replacement-Capable Shared Taxis
    #
    # Each taxi already contains ONE Passenger Group.
    #
    # Therefore each taxi may receive exactly one
    # recovered Passenger Group and reach:
    #
    # 2 active groups / taxi
    # =====================================================

    replacement_taxis = []


    for taxi_index in range(
        1,
        3,
    ):

        (
            vehicle,
            _,
            _,
            _,
        ) = (
            create_active_shared_taxi(

                taxi_index=(
                    taxi_index
                ),

                current_node=(
                    current_node
                ),

                pickup_node=(
                    pickup_node
                ),

                destination_node=(
                    destination_node
                ),

                group_count=1,
            )
        )


        replacement_taxis.append(
            vehicle
        )


    # =====================================================
    # 4. Seven Saturated Shared Taxis
    #
    # Every taxi already contains TWO Passenger Groups.
    #
    # Recovery must reject them because:
    #
    # MAX_SHARED_PASSENGER_GROUPS = 2
    # =====================================================

    saturated_taxis = []


    for taxi_index in range(
        3,
        10,
    ):

        (
            vehicle,
            _,
            _,
            _,
        ) = (
            create_active_shared_taxi(

                taxi_index=(
                    taxi_index
                ),

                current_node=(
                    current_node
                ),

                pickup_node=(
                    pickup_node
                ),

                destination_node=(
                    destination_node
                ),

                group_count=2,
            )
        )


        saturated_taxis.append(
            vehicle
        )


    # =====================================================
    # 5. Scenario Sanity Checks
    #
    # 1 failed taxi
    # +
    # 2 replacement-capable taxis
    # +
    # 7 saturated taxis
    #
    # = 10 taxis
    # =====================================================

    assert (
        Vehicle.objects.count()
        == 10
    )


    assert (
        len(replacement_taxis)
        == 2
    )


    assert (
        len(saturated_taxis)
        == 7
    )


    # =====================================================
    # 6. Detect Affected Passenger Groups
    #
    # Detection occurs BEFORE the formal performance timer.
    #
    # We expect exactly two Passenger Groups because both
    # pickups on the failed taxi remain PENDING.
    # =====================================================

    affected_groups = (
        RecoveryDetectionService
        .find_affected_groups(
            failed_ride
        )
    )


    assert (
        len(affected_groups)
        == 2
    )


    # =====================================================
    # 7. PERFORMANCE MEASUREMENT START
    #
    # Measure only the Complex Recovery Planning phase:
    #
    # - Passenger priority
    # - Candidate taxi generation
    # - Existing Shared Route inspection
    # - O(k²) insertion alternatives
    # - Dijkstra routing
    # - Route simulation
    # - Capacity validation
    # - Maximum group validation
    # - Pickup wait constraint
    # - Absolute delay constraint
    # - Relative delay constraint
    # - Reject infeasible candidates
    # - Generate Recovery Plans
    # - Rank feasible plans
    #
    # Notifications and transactional DB application are
    # NOT included in this formal <= 2 sec measurement.
    # =====================================================

    planning_start = (
        time.perf_counter()
    )


    planning_result = (
        RecoveryPlanService
        .generate_recovery_plans(

            affected_groups=(
                affected_groups
            ),

            failed_vehicle_id=(
                failed_vehicle.id
            ),
        )
    )


    planning_seconds = (
        time.perf_counter()
        - planning_start
    )


    # =====================================================
    # 8. Planning Correctness
    # =====================================================

    assert (
        planning_result.best_plan
        is not None
    )


    # Both affected Passenger Groups must be recoverable.
    assert (
        planning_result
        .best_plan
        .recovered_group_count
        == 2
    )


    # Conservative Recovery consistency rule:
    #
    # two groups in the same Recovery transaction
    # must use different replacement taxis.
    assert (
        len(
            set(
                planning_result
                .best_plan
                .vehicle_ids
            )
        )
        == 2
    )


    # Failed taxi must never be selected again.
    assert (
        failed_vehicle.id
        not in (
            planning_result
            .best_plan
            .vehicle_ids
        )
    )


    # =====================================================
    # 9. FORMAL PERFORMANCE REQUIREMENT
    #
    # Recovery complex planning <= 2 seconds
    # =====================================================

    assert (
        planning_seconds
        <= 2.0
    ), (
        "\n"
        "Recovery planning exceeded performance target.\n"
        f"Elapsed: {planning_seconds:.4f} seconds\n"
        "Target: <= 2.0000 seconds\n"
        "Scenario: 20 nodes, 10 taxis, "
        "up to 2 active groups per taxi."
    )


    # =====================================================
    # 10. Full End-To-End Recovery Measurement
    #
    # Now run the real RecoveryOrchestrator.
    #
    # This executes the COMPLETE workflow:
    #
    # Detection
    # Planning
    # Final revalidation
    # DB transaction
    # Route updates
    # RouteStop updates
    # ETA updates
    # RecoveryEvent updates
    # Notifications
    #
    # This timing is useful for the final report but is
    # intentionally separate from the formal algorithmic
    # performance assertion above.
    # =====================================================

    full_start = (
        time.perf_counter()
    )


    event = (
        RecoveryOrchestrator
        .recover_ride(

            ride_id=(
                failed_ride.id
            ),

            failed_vehicle_id=(
                failed_vehicle.id
            ),

            trigger_type=(
                RecoveryEvent
                .TriggerType
                .DRIVER_REJECT
            ),
        )
    )


    full_recovery_seconds = (
        time.perf_counter()
        - full_start
    )


    # =====================================================
    # 11. Refresh Recovery Event
    # =====================================================

    event.refresh_from_db()


    # =====================================================
    # 12. End-To-End Recovery Correctness
    # =====================================================

    assert (
        event.status
        == RecoveryEvent.Status.COMPLETED
    )


    assert (
        event.affected_passenger_groups
        == 2
    )


    # =====================================================
    # 13. Find Original Failed Requests
    # =====================================================

    failed_request_ids = list(

        RidePassenger.objects
        .filter(
            ride=failed_ride
        )
        .values_list(
            "ride_request_id",
            flat=True,
        )
    )


    assert (
        len(failed_request_ids)
        == 2
    )


    # =====================================================
    # 14. Both Requests Must Be Reassigned
    # =====================================================

    recovered_requests = (
        RideRequest.objects
        .filter(
            id__in=(
                failed_request_ids
            )
        )
    )


    assert (
        recovered_requests.count()
        == 2
    )


    assert all(

        request.status
        == RideRequest.Status.ASSIGNED

        for request
        in recovered_requests
    )


    # =====================================================
    # 15. Each Request Must Now Have:
    #
    # Old historical membership
    # +
    # New replacement membership
    # =====================================================

    for request_id in (
        failed_request_ids
    ):

        assert (
            RidePassenger.objects
            .filter(
                ride_request_id=(
                    request_id
                )
            )
            .count()
            == 2
        )


    # =====================================================
    # 16. Replacement Taxis Still Shared
    #
    # They initially had one group.
    # After Recovery they now contain two groups.
    # =====================================================

    for vehicle in (
        replacement_taxis
    ):

        vehicle.refresh_from_db()


        assert (
            vehicle.ride_mode
            == Vehicle.RideMode.SHARED
        )


    # =====================================================
    # 17. Failed Vehicle Remains Free
    # =====================================================

    failed_vehicle.refresh_from_db()


    assert (
        failed_vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )


    # =====================================================
    # 18. Report-Friendly Output
    # =====================================================

    print(
        "\n"
        "=========================================\n"
        "RECOVERY PERFORMANCE RESULT\n"
        "=========================================\n"
        "Road nodes: 20\n"
        "Taxis: 10\n"
        "Affected passenger groups: 2\n"
        "Maximum groups per taxi: 2\n"
        "-----------------------------------------\n"
        f"Recovery planning time: "
        f"{planning_seconds:.4f} seconds\n"
        f"Full recovery time: "
        f"{full_recovery_seconds:.4f} seconds\n"
        f"Stored RecoveryEvent time: "
        f"{event.recovery_duration_ms} ms\n"
        "-----------------------------------------\n"
        "Formal planning requirement: "
        "<= 2.0000 seconds\n"
        "========================================="
    )