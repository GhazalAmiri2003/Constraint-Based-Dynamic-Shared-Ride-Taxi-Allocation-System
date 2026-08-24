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
from rides.models import (
    Ride,
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
from shared_ride.movement_services import (
    SharedMovementAction,
    SharedRouteMovementService,
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
):
    return RoadEdge.objects.create(
        from_node=first,
        to_node=second,
        distance_km=1.0,
        travel_time_minutes=2,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )


def create_network():
    """
    N1 -- N2 -- N3 -- N4
    """

    n1 = create_node("N1", 1)
    n2 = create_node("N2", 2)
    n3 = create_node("N3", 3)
    n4 = create_node("N4", 4)

    connect(n1, n2)
    connect(n2, n3)
    connect(n3, n4)

    return n1, n2, n3, n4


def create_passenger():
    user = User.objects.create_user(
        username="shared_e2e_passenger",
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.PASSENGER,
    )

    return PassengerProfile.objects.create(
        user=user
    )


def create_vehicle(
    current_node,
):
    user = User.objects.create_user(
        username="shared_e2e_driver",
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
# Complete Shared Ride End-To-End
# =========================================================

def test_complete_shared_ride_end_to_end():

    (
        n1,
        n2,
        _,
        n4,
    ) = create_network()

    passenger = create_passenger()

    vehicle = create_vehicle(
        current_node=n1
    )

    # =====================================================
    # 1. Passenger Creates SHARED Request
    # =====================================================

    ride_request = (
        RideRequest.objects.create(
            passenger=passenger,

            ride_type=(
                RideRequest.RideType.SHARED
            ),

            passenger_count=1,

            pickup_node=n2,

            destination_node=n4,

            status=(
                RideRequest.Status.PENDING
            ),
        )
    )

    # =====================================================
    # 2. Shared Taxi Options
    # =====================================================

    options = (
        SharedTaxiOptionService
        .generate_shared_taxi_options(
            ride_request
        )
    )

    assert len(options) == 1

    assert (
        options[0].vehicle_id
        == vehicle.id
    )

    assert (
        options[0].rank
        == 1
    )

    # =====================================================
    # 3. Hold
    # =====================================================

    hold = (
        SharedTaxiConfirmationService
        .create_shared_taxi_hold(
            ride_request=ride_request,
            vehicle_id=vehicle.id,
        )
    )

    # Hold must not assign immediately.
    ride_request.refresh_from_db()

    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )

    # =====================================================
    # 4. Confirm
    # =====================================================

    confirmation = (
        SharedTaxiConfirmationService
        .confirm_shared_taxi_hold(
            hold
        )
    )

    ride = confirmation.ride
    route = confirmation.route

    ride_request.refresh_from_db()
    vehicle.refresh_from_db()

    assert (
        ride_request.status
        == RideRequest.Status.ASSIGNED
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.SHARED
    )

    assert (
        route.status
        == Route.Status.ACTIVE
    )

    # Pickup + Dropoff
    assert (
        RouteStop.objects
        .filter(
            route=route
        )
        .count()
        == 2
    )

    assert (
        SharedPassengerBaseline.objects
        .filter(
            ride_passenger=(
                confirmation.ride_passenger
            )
        )
        .exists()
    )

    # =====================================================
    # 5. Driver Accepts Ride
    # =====================================================

    ride.status = Ride.Status.ACCEPTED

    ride.save(
        update_fields=[
            "status",
        ]
    )

    # =====================================================
    # 6. Move N1 → N2
    # Pickup completed
    # =====================================================

    result = (
        SharedRouteMovementService
        .advance_shared_ride(
            vehicle.id
        )
    )

    ride.refresh_from_db()
    vehicle.refresh_from_db()

    assert (
        vehicle.current_node_id
        == n2.id
    )

    assert (
        ride.status
        == Ride.Status.IN_PROGRESS
    )

    assert (
        result.action
        == SharedMovementAction.STOP_COMPLETED
    )

    # =====================================================
    # 7. Move N2 → N3
    # =====================================================

    result = (
        SharedRouteMovementService
        .advance_shared_ride(
            vehicle.id
        )
    )

    vehicle.refresh_from_db()

    assert (
        vehicle.current_node.name
        == "N3"
    )

    assert (
        result.action
        == SharedMovementAction.MOVED
    )

    # =====================================================
    # 8. Move N3 → N4
    # Final Dropoff
    # =====================================================

    result = (
        SharedRouteMovementService
        .advance_shared_ride(
            vehicle.id
        )
    )

    ride.refresh_from_db()
    route.refresh_from_db()
    vehicle.refresh_from_db()
    ride_request.refresh_from_db()

    assert (
        result.action
        == SharedMovementAction.RIDE_COMPLETED
    )

    assert (
        ride_request.status
        == RideRequest.Status.COMPLETED
    )

    assert (
        ride.status
        == Ride.Status.COMPLETED
    )

    assert (
        route.status
        == Route.Status.COMPLETED
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )

    assert (
        vehicle.current_node_id
        == n4.id
    )

    # All stops completed.
    assert not (
        RouteStop.objects
        .filter(
            route=route,
            status=RouteStop.Status.PENDING,
        )
        .exists()
    )