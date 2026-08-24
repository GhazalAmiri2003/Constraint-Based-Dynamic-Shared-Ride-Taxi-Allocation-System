import time

import pytest

from django.contrib.auth.models import User

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from assignment.shared_confirmation_services import (
    SharedTaxiConfirmationService,
)
from assignment.shared_services import (
    SharedTaxiOptionService,
)
from fleet.models import Vehicle
from rides.models import RideRequest
from road_network.models import (
    RoadEdge,
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


def connect_nodes(
    first,
    second,
):
    """
    Create a bidirectional road connection.
    """

    return RoadEdge.objects.create(
        from_node=first,
        to_node=second,
        distance_km=1.0,
        travel_time_minutes=1,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )


def create_network():
    """
    Create a simple network with 20 nodes:

    N1 -- N2 -- N3 -- ... -- N20

    This gives the routing algorithm enough nodes
    to perform multiple Dijkstra searches.
    """

    nodes = []

    for index in range(
        1,
        21,
    ):

        node = create_node(
            name=f"N{index}",
            x=index,
        )

        nodes.append(
            node
        )


    for index in range(
        len(nodes) - 1
    ):

        connect_nodes(
            nodes[index],
            nodes[index + 1],
        )


    return nodes


def create_passenger(
    username,
):
    """
    Create a Passenger user and profile.
    """

    user = User.objects.create_user(
        username=username,
        password="StrongPass123!",
    )


    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.PASSENGER,
    )


    return PassengerProfile.objects.create(
        user=user,
    )


def create_vehicle(
    username,
    current_node,
):
    """
    Create an ONLINE driver with an available taxi.
    """

    user = User.objects.create_user(
        username=username,
        password="StrongPass123!",
    )


    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.DRIVER,
    )


    driver = DriverProfile.objects.create(
        user=user,
        availability_status=(
            DriverProfile
            .AvailabilityStatus
            .ONLINE
        ),
    )


    return Vehicle.objects.create(
        driver=driver,
        capacity=4,
        is_available=True,
        ride_mode=Vehicle.RideMode.IDLE,
        current_node=current_node,
    )


# =========================================================
# Performance Test
# =========================================================

def test_shared_option_generation_under_two_seconds():

    # =====================================================
    # 1. Create realistic small road network
    # =====================================================

    nodes = create_network()


    # =====================================================
    # 2. Create 8 simulated taxis
    # =====================================================

    vehicles = []

    for index in range(
        1,
        9,
    ):

        vehicle = create_vehicle(
            username=f"performance_driver_{index}",
            current_node=nodes[0],
        )

        vehicles.append(
            vehicle
        )


    # =====================================================
    # 3. Create first shared passenger
    #
    # This passenger is assigned to Vehicle #1.
    # Therefore Vehicle #1 becomes an existing SHARED taxi.
    # =====================================================

    passenger_one = create_passenger(
        "performance_passenger_one"
    )


    first_request = (
        RideRequest.objects.create(
            passenger=passenger_one,

            ride_type=(
                RideRequest.RideType.SHARED
            ),

            passenger_count=1,

            pickup_node=nodes[2],       # N3

            destination_node=nodes[7],  # N8

            status=(
                RideRequest.Status.PENDING
            ),
        )
    )


    # =====================================================
    # 4. Hold Vehicle #1
    # =====================================================

    hold = (
        SharedTaxiConfirmationService
        .create_shared_taxi_hold(
            ride_request=first_request,
            vehicle_id=vehicles[0].id,
        )
    )


    # =====================================================
    # 5. Confirm first passenger
    #
    # Vehicle #1 now has:
    #
    # - SHARED mode
    # - Active Route
    # - Existing RouteStops
    # - Passenger Baseline
    #
    # This means the next request will require
    # real dynamic route insertion evaluation.
    # =====================================================

    SharedTaxiConfirmationService \
        .confirm_shared_taxi_hold(
            hold
        )


    vehicles[0].refresh_from_db()

    assert (
        vehicles[0].ride_mode
        == Vehicle.RideMode.SHARED
    )


    # =====================================================
    # 6. Create second shared request
    #
    # The allocation engine must now evaluate:
    #
    # - 1 existing SHARED taxi
    # - 7 IDLE taxis
    #
    # For the SHARED taxi it must generate insertion
    # alternatives and evaluate all constraints.
    # =====================================================

    passenger_two = create_passenger(
        "performance_passenger_two"
    )


    second_request = (
        RideRequest.objects.create(
            passenger=passenger_two,

            ride_type=(
                RideRequest.RideType.SHARED
            ),

            passenger_count=1,

            pickup_node=nodes[3],       # N4

            destination_node=nodes[8],  # N9

            status=(
                RideRequest.Status.PENDING
            ),
        )
    )


    # =====================================================
    # 7. Measure ONLY the allocation algorithm
    #
    # Database/network setup above is intentionally
    # excluded from the measurement.
    # =====================================================

    start_time = (
        time.perf_counter()
    )


    options = (
        SharedTaxiOptionService
        .generate_shared_taxi_options(
            second_request
        )
    )


    elapsed_time = (
        time.perf_counter()
        - start_time
    )


    # =====================================================
    # 8. Correctness checks
    # =====================================================

    assert len(options) >= 1


    # Every returned option must have a valid ranking.
    assert all(
        option.rank >= 1
        for option in options
    )


    # Rankings must be sequential.
    assert [
        option.rank
        for option in options
    ] == list(
        range(
            1,
            len(options) + 1,
        )
    )


    # =====================================================
    # 9. Performance requirement
    #
    # Proposal target:
    #
    # Shared taxi option generation < 2 seconds
    # =====================================================

    assert elapsed_time < 2.0, (
        "Shared option generation exceeded "
        "the 2-second performance target. "
        f"Elapsed time: {elapsed_time:.4f} seconds"
    )


    # Useful information when running pytest with -s
    print(
        "\n"
        "Shared allocation performance:"
        f" {elapsed_time:.4f} seconds"
        f" | taxis evaluated: {len(vehicles)}"
        f" | feasible options: {len(options)}"
    )