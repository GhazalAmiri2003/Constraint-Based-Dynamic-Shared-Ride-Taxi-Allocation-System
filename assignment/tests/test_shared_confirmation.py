from datetime import timedelta

import pytest

from django.contrib.auth.models import User
from django.utils import timezone

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from assignment.models import TaxiHold
from assignment.shared_confirmation_services import (
    SharedConfirmationError,
    SharedTaxiConfirmationService,
)
from fleet.models import Vehicle
from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)
from road_network.models import (
    RoadEdge,
    RoadNode,
)
from shared_ride.baseline_services import (
    SharedBaselineError,
    SharedPassengerBaselineService,
)
from shared_ride.models import (
    Route,
    RouteStop,
    SharedPassengerBaseline,
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


def connect(
    first,
    second,
    *,
    time_minutes=2,
    distance_km=1.0,
):
    return RoadEdge.objects.create(
        from_node=first,
        to_node=second,
        distance_km=distance_km,
        travel_time_minutes=time_minutes,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )


def create_network():
    """
    N1 --2-- N2 --2-- N3 --2-- N4 --2-- N5
    """

    nodes = [
        create_node(
            f"N{i}",
            i,
        )
        for i in range(1, 6)
    ]

    for index in range(4):
        connect(
            nodes[index],
            nodes[index + 1],
        )

    return nodes


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
        user=user,
    )


def create_vehicle(
    *,
    username,
    current_node,
    mode=Vehicle.RideMode.IDLE,
    online=True,
    available=True,
    capacity=4,
):
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
            DriverProfile.AvailabilityStatus.ONLINE
            if online
            else DriverProfile.AvailabilityStatus.OFFLINE
        ),
    )

    return Vehicle.objects.create(
        driver=driver,
        capacity=capacity,
        is_available=available,
        ride_mode=mode,
        current_node=current_node,
    )


def create_shared_request(
    *,
    username,
    pickup,
    destination,
    passenger_count=1,
):
    passenger = create_passenger(
        username
    )

    return RideRequest.objects.create(
        passenger=passenger,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        passenger_count=(
            passenger_count
        ),

        pickup_node=pickup,

        destination_node=destination,

        status=(
            RideRequest.Status.PENDING
        ),
    )


def create_existing_shared_ride(
    *,
    vehicle,
    reference_time,
    pickup,
    destination,
):
    """
    Existing Passenger A:

    Pickup = completed
    Passenger is onboard
    Dropoff = pending
    """

    passenger = create_passenger(
        "existing_passenger"
    )

    request = RideRequest.objects.create(
        passenger=passenger,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        passenger_count=1,

        pickup_node=pickup,

        destination_node=destination,

        status=(
            RideRequest.Status.ASSIGNED
        ),
    )

    ride = Ride.objects.create(
        vehicle=vehicle,

        ride_type=(
            RideRequest.RideType.SHARED
        ),

        status=(
            Ride.Status.IN_PROGRESS
        ),
    )

    ride_passenger = (
        RidePassenger.objects.create(
            ride=ride,
            ride_request=request,
        )
    )

    route = Route.objects.create(
        ride=ride,

        status=(
            Route.Status.ACTIVE
        ),

        revision=1,

        total_estimated_time_minutes=6,

        total_estimated_distance_km=3.0,
    )

    # -----------------------------------------------------
    # Passenger A Pickup - already completed
    # -----------------------------------------------------

    RouteStop.objects.create(
        route=route,

        ride_passenger=(
            ride_passenger
        ),

        node=pickup,

        stop_type=(
            RouteStop.StopType.PICKUP
        ),

        sequence_number=1,

        status=(
            RouteStop.Status.COMPLETED
        ),

        estimated_arrival_minutes=0,

        estimated_arrival_time=(
            reference_time
        ),

        actual_arrival_time=(
            reference_time
        ),
    )

    # -----------------------------------------------------
    # Passenger A Dropoff - still pending
    # -----------------------------------------------------

    RouteStop.objects.create(
        route=route,

        ride_passenger=(
            ride_passenger
        ),

        node=destination,

        stop_type=(
            RouteStop.StopType.DROPOFF
        ),

        sequence_number=2,

        status=(
            RouteStop.Status.PENDING
        ),

        estimated_arrival_minutes=6,

        estimated_arrival_time=(
            reference_time
            + timedelta(
                minutes=6
            )
        ),
    )

    # -----------------------------------------------------
    # Original Passenger Baseline
    # -----------------------------------------------------

    SharedPassengerBaseline.objects.create(
        ride_passenger=(
            ride_passenger
        ),

        # N1 → N5:
        # 4 edges × 2 minutes = 8
        direct_trip_time_minutes=8,

        # Taxi is currently at N2.
        # N2 → N5 = 6 minutes.
        baseline_expected_dropoff_at=(
            reference_time
            + timedelta(
                minutes=6
            )
        ),

        baseline_route_revision=1,
    )

    return (
        ride,
        route,
        ride_passenger,
    )


# =========================================================
# 1. Hold Does NOT Assign Immediately
# =========================================================

def test_shared_hold_does_not_assign_immediately():

    n1, n2, _, n4, _ = (
        create_network()
    )

    vehicle = create_vehicle(
        username="driver_hold_only",
        current_node=n1,
    )

    request = create_shared_request(
        username="passenger_hold_only",
        pickup=n2,
        destination=n4,
    )

    hold = (
        SharedTaxiConfirmationService
        .create_shared_taxi_hold(
            ride_request=request,
            vehicle_id=vehicle.id,
        )
    )

    request.refresh_from_db()
    vehicle.refresh_from_db()
    hold.refresh_from_db()

    # Hold ساخته شده است.
    assert (
        hold.status
        == TaxiHold.Status.ACTIVE
    )

    # ولی هنوز assignment انجام نشده.
    assert (
        request.status
        == RideRequest.Status.PENDING
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )

    assert Ride.objects.count() == 0

    assert (
        RidePassenger.objects.count()
        == 0
    )

    assert Route.objects.count() == 0

    assert (
        RouteStop.objects.count()
        == 0
    )


# =========================================================
# 2. Confirm IDLE Taxi Creates Complete Shared Ride
# =========================================================

def test_confirm_idle_taxi_creates_shared_ride():

    n1, n2, _, n4, _ = (
        create_network()
    )

    vehicle = create_vehicle(
        username="driver_idle_confirm",
        current_node=n1,
    )

    request = create_shared_request(
        username="passenger_idle_confirm",
        pickup=n2,
        destination=n4,
    )

    hold = (
        SharedTaxiConfirmationService
        .create_shared_taxi_hold(
            ride_request=request,
            vehicle_id=vehicle.id,
        )
    )

    result = (
        SharedTaxiConfirmationService
        .confirm_shared_taxi_hold(
            hold
        )
    )

    request.refresh_from_db()
    vehicle.refresh_from_db()
    hold.refresh_from_db()

    route = result.route

    route.refresh_from_db()

    # -----------------------------------------------------
    # Hold
    # -----------------------------------------------------

    assert (
        hold.status
        == TaxiHold.Status.CONFIRMED
    )

    # -----------------------------------------------------
    # Request
    # -----------------------------------------------------

    assert (
        request.status
        == RideRequest.Status.ASSIGNED
    )

    # -----------------------------------------------------
    # Vehicle
    # -----------------------------------------------------

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.SHARED
    )

    # -----------------------------------------------------
    # Ride
    # -----------------------------------------------------

    assert (
        result.ride.vehicle_id
        == vehicle.id
    )

    assert (
        result.ride.ride_type
        == RideRequest.RideType.SHARED
    )

    assert (
        result.ride.status
        == Ride.Status.ASSIGNED
    )

    # -----------------------------------------------------
    # RidePassenger
    # -----------------------------------------------------

    assert (
        result
        .ride_passenger
        .ride_request_id
        == request.id
    )

    assert (
        result
        .ride_passenger
        .ride_id
        == result.ride.id
    )

    # -----------------------------------------------------
    # Route
    # -----------------------------------------------------

    assert route.revision == 1

    assert (
        route.status
        == Route.Status.ACTIVE
    )

    # -----------------------------------------------------
    # Route Stops
    # -----------------------------------------------------

    stops = list(
        RouteStop.objects
        .filter(
            route=route
        )
        .order_by(
            "sequence_number"
        )
    )

    assert len(stops) == 2

    assert (
        stops[0].stop_type
        == RouteStop.StopType.PICKUP
    )

    assert (
        stops[0].node_id
        == n2.id
    )

    assert (
        stops[1].stop_type
        == RouteStop.StopType.DROPOFF
    )

    assert (
        stops[1].node_id
        == n4.id
    )

    assert (
        stops[0].sequence_number
        == 1
    )

    assert (
        stops[1].sequence_number
        == 2
    )

    # -----------------------------------------------------
    # Baseline
    # -----------------------------------------------------

    baseline = (
        SharedPassengerBaseline.objects.get(
            ride_passenger=(
                result.ride_passenger
            )
        )
    )

    assert (
        baseline.baseline_route_revision
        == 1
    )

    assert (
        baseline.direct_trip_time_minutes
        == 4
    )


# =========================================================
# 3. Existing Shared Taxi Reuses Ride + Revises Route
# =========================================================

def test_confirm_existing_shared_taxi_inserts_passenger():

    (
        n1,
        n2,
        n3,
        n4,
        n5,
    ) = create_network()

    now = timezone.now()

    vehicle = create_vehicle(
        username="driver_existing_shared",
        current_node=n2,
        mode=Vehicle.RideMode.SHARED,
    )

    (
        existing_ride,
        existing_route,
        existing_ride_passenger,
    ) = (
        create_existing_shared_ride(
            vehicle=vehicle,
            reference_time=now,
            pickup=n1,
            destination=n5,
        )
    )

    request = create_shared_request(
        username="new_shared_passenger",
        pickup=n3,
        destination=n4,
    )

    hold = (
        SharedTaxiConfirmationService
        .create_shared_taxi_hold(
            ride_request=request,
            vehicle_id=vehicle.id,
        )
    )

    result = (
        SharedTaxiConfirmationService
        .confirm_shared_taxi_hold(
            hold
        )
    )

    hold.refresh_from_db()
    request.refresh_from_db()
    existing_route.refresh_from_db()

    # -----------------------------------------------------
    # Same Ride must be reused
    # -----------------------------------------------------

    assert (
        result.ride.id
        == existing_ride.id
    )

    assert (
        Ride.objects.filter(
            vehicle=vehicle
        ).count()
        == 1
    )

    # -----------------------------------------------------
    # New Passenger added
    # -----------------------------------------------------

    assert (
        RidePassenger.objects
        .filter(
            ride=existing_ride
        )
        .count()
        == 2
    )

    assert (
        result
        .ride_passenger
        .ride_request_id
        == request.id
    )

    # -----------------------------------------------------
    # Route reused
    # -----------------------------------------------------

    assert (
        result.route.id
        == existing_route.id
    )

    # Revision:
    # 1 → 2
    assert (
        existing_route.revision
        == 2
    )

    # -----------------------------------------------------
    # Request assigned
    # -----------------------------------------------------

    assert (
        request.status
        == RideRequest.Status.ASSIGNED
    )

    # -----------------------------------------------------
    # Hold confirmed
    # -----------------------------------------------------

    assert (
        hold.status
        == TaxiHold.Status.CONFIRMED
    )

    # -----------------------------------------------------
    # Existing completed pickup must remain
    # -----------------------------------------------------

    completed_pickup = (
        RouteStop.objects.get(
            route=existing_route,

            ride_passenger=(
                existing_ride_passenger
            ),

            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        )
    )

    assert (
        completed_pickup.status
        == RouteStop.Status.COMPLETED
    )

    assert (
        completed_pickup.sequence_number
        == 1
    )

    # -----------------------------------------------------
    # New Passenger must have exactly 2 stops
    # -----------------------------------------------------

    new_stops = list(
        RouteStop.objects
        .filter(
            route=existing_route,

            ride_passenger=(
                result.ride_passenger
            ),
        )
        .order_by(
            "sequence_number"
        )
    )

    assert len(new_stops) == 2

    assert (
        new_stops[0].stop_type
        == RouteStop.StopType.PICKUP
    )

    assert (
        new_stops[0].node_id
        == n3.id
    )

    assert (
        new_stops[1].stop_type
        == RouteStop.StopType.DROPOFF
    )

    assert (
        new_stops[1].node_id
        == n4.id
    )

    # -----------------------------------------------------
    # Existing A dropoff must still exist
    # -----------------------------------------------------

    existing_dropoff = (
        RouteStop.objects.get(
            route=existing_route,

            ride_passenger=(
                existing_ride_passenger
            ),

            stop_type=(
                RouteStop.StopType.DROPOFF
            ),
        )
    )

    assert (
        existing_dropoff.node_id
        == n5.id
    )

    assert (
        existing_dropoff.status
        == RouteStop.Status.PENDING
    )

    # Expected best order:
    #
    # seq 1 = completed pickup A
    # seq 2 = pickup B
    # seq 3 = dropoff B
    # seq 4 = dropoff A

    assert (
        new_stops[0].sequence_number
        == 2
    )

    assert (
        new_stops[1].sequence_number
        == 3
    )

    assert (
        existing_dropoff.sequence_number
        == 4
    )

    # -----------------------------------------------------
    # Baseline must exist for both passenger groups
    # -----------------------------------------------------

    assert (
        SharedPassengerBaseline.objects
        .filter(
            ride_passenger__ride=(
                existing_ride
            )
        )
        .count()
        == 2
    )

    new_baseline = (
        SharedPassengerBaseline.objects.get(
            ride_passenger=(
                result.ride_passenger
            )
        )
    )

    assert (
        new_baseline.baseline_route_revision
        == 2
    )


# =========================================================
# 4. Expired Hold Cannot Be Confirmed
# =========================================================

def test_expired_shared_hold_is_rejected():

    n1, n2, _, n4, _ = (
        create_network()
    )

    vehicle = create_vehicle(
        username="driver_expired_hold",
        current_node=n1,
    )

    request = create_shared_request(
        username="passenger_expired_hold",
        pickup=n2,
        destination=n4,
    )

    hold = (
        SharedTaxiConfirmationService
        .create_shared_taxi_hold(
            ride_request=request,
            vehicle_id=vehicle.id,
        )
    )

    # Force expiration
    TaxiHold.objects.filter(
        pk=hold.pk
    ).update(
        expires_at=(
            timezone.now()
            - timedelta(
                seconds=1
            )
        )
    )

    with pytest.raises(
        SharedConfirmationError
    ):
        (
            SharedTaxiConfirmationService
            .confirm_shared_taxi_hold(
                hold
            )
        )

    hold.refresh_from_db()
    request.refresh_from_db()
    vehicle.refresh_from_db()

    assert (
        hold.status
        == TaxiHold.Status.EXPIRED
    )

    assert (
        request.status
        == RideRequest.Status.PENDING
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )

    assert Ride.objects.count() == 0

    assert (
        RidePassenger.objects.count()
        == 0
    )


# =========================================================
# 5. Vehicle State Changed After Hold
# =========================================================

def test_confirmation_revalidates_vehicle_state():

    n1, n2, _, n4, _ = (
        create_network()
    )

    vehicle = create_vehicle(
        username="driver_state_change",
        current_node=n1,
    )

    request = create_shared_request(
        username="passenger_state_change",
        pickup=n2,
        destination=n4,
    )

    hold = (
        SharedTaxiConfirmationService
        .create_shared_taxi_hold(
            ride_request=request,
            vehicle_id=vehicle.id,
        )
    )

    # -----------------------------------------------------
    # Taxi state changes AFTER hold
    # -----------------------------------------------------

    vehicle.is_available = False

    vehicle.save(
        update_fields=[
            "is_available",
            "updated_at",
        ]
    )

    # Confirmation must re-check state.
    with pytest.raises(
        SharedConfirmationError
    ):
        (
            SharedTaxiConfirmationService
            .confirm_shared_taxi_hold(
                hold
            )
        )

    hold.refresh_from_db()
    request.refresh_from_db()
    vehicle.refresh_from_db()

    # Hold is released rather than confirmed.
    assert (
        hold.status
        == TaxiHold.Status.RELEASED
    )

    assert (
        request.status
        == RideRequest.Status.PENDING
    )

    assert Ride.objects.count() == 0

    assert (
        RidePassenger.objects.count()
        == 0
    )


# =========================================================
# 6. Double Confirmation Rejected
# =========================================================

def test_same_shared_hold_cannot_be_confirmed_twice():

    n1, n2, _, n4, _ = (
        create_network()
    )

    vehicle = create_vehicle(
        username="driver_double_confirm",
        current_node=n1,
    )

    request = create_shared_request(
        username="passenger_double_confirm",
        pickup=n2,
        destination=n4,
    )

    hold = (
        SharedTaxiConfirmationService
        .create_shared_taxi_hold(
            ride_request=request,
            vehicle_id=vehicle.id,
        )
    )

    first_result = (
        SharedTaxiConfirmationService
        .confirm_shared_taxi_hold(
            hold
        )
    )

    assert (
        first_result.hold.status
        == TaxiHold.Status.CONFIRMED
    )

    # Second confirmation must fail.
    with pytest.raises(
        SharedConfirmationError
    ):
        (
            SharedTaxiConfirmationService
            .confirm_shared_taxi_hold(
                hold
            )
        )

    hold.refresh_from_db()

    assert (
        hold.status
        == TaxiHold.Status.CONFIRMED
    )

    # No duplicate ride
    assert Ride.objects.count() == 1

    # No duplicate passenger
    assert (
        RidePassenger.objects.count()
        == 1
    )

    # No duplicate route
    assert Route.objects.count() == 1

    # Still exactly:
    # Pickup + Dropoff
    assert (
        RouteStop.objects.count()
        == 2
    )


# =========================================================
# 7. Transaction Rollback On Baseline Failure
# =========================================================

def test_confirmation_rolls_back_if_baseline_creation_fails(
    monkeypatch,
):

    n1, n2, _, n4, _ = (
        create_network()
    )

    vehicle = create_vehicle(
        username="driver_rollback",
        current_node=n1,
    )

    request = create_shared_request(
        username="passenger_rollback",
        pickup=n2,
        destination=n4,
    )

    hold = (
        SharedTaxiConfirmationService
        .create_shared_taxi_hold(
            ride_request=request,
            vehicle_id=vehicle.id,
        )
    )

    # -----------------------------------------------------
    # Artificial failure during final transaction
    # -----------------------------------------------------

    def fail_baseline_creation(
        *args,
        **kwargs,
    ):
        raise SharedBaselineError(
            "Forced baseline failure."
        )

    monkeypatch.setattr(
        SharedPassengerBaselineService,
        "create_baseline",
        fail_baseline_creation,
    )

    # -----------------------------------------------------
    # Confirmation should fail
    # -----------------------------------------------------

    with pytest.raises(
        SharedConfirmationError
    ):
        (
            SharedTaxiConfirmationService
            .confirm_shared_taxi_hold(
                hold
            )
        )

    # -----------------------------------------------------
    # Refresh original records
    # -----------------------------------------------------

    hold.refresh_from_db()
    request.refresh_from_db()
    vehicle.refresh_from_db()

    # -----------------------------------------------------
    # Everything inside transaction must rollback
    # -----------------------------------------------------

    assert Ride.objects.count() == 0

    assert (
        RidePassenger.objects.count()
        == 0
    )

    assert Route.objects.count() == 0

    assert (
        RouteStop.objects.count()
        == 0
    )

    assert (
        SharedPassengerBaseline.objects.count()
        == 0
    )

    # Request must remain unchanged.
    assert (
        request.status
        == RideRequest.Status.PENDING
    )

    # Vehicle must remain IDLE.
    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )

    # Because the entire transaction rolled back,
    # the original active hold also remains active.
    assert (
        hold.status
        == TaxiHold.Status.ACTIVE
    )