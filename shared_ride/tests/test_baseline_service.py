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
    SharedPassengerBaseline,
)


pytestmark = pytest.mark.django_db


# =========================================================
# Helpers
# =========================================================

def create_passenger(
    username="passenger",
):
    user = User.objects.create_user(
        username=username,
        password="test12345",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.PASSENGER,
    )

    passenger = PassengerProfile.objects.create(
        user=user,
    )

    return passenger


def create_driver_and_vehicle(
    current_node,
):
    user = User.objects.create_user(
        username="driver",
        password="test12345",
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

    vehicle = Vehicle.objects.create(
        driver=driver,
        capacity=4,
        is_available=True,
        ride_mode=Vehicle.RideMode.SHARED,
        current_node=current_node,
    )

    return vehicle


def create_simple_network():
    """
    N1 --5min--> N2 --5min--> N3

    Total direct trip:
    N1 → N3 = 10 minutes
    """

    n1 = RoadNode.objects.create(
        name="N1",
        x=0,
        y=0,
    )

    n2 = RoadNode.objects.create(
        name="N2",
        x=1,
        y=0,
    )

    n3 = RoadNode.objects.create(
        name="N3",
        x=2,
        y=0,
    )

    RoadEdge.objects.create(
        from_node=n1,
        to_node=n2,
        distance_km=1.0,
        travel_time_minutes=5,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    RoadEdge.objects.create(
        from_node=n2,
        to_node=n3,
        distance_km=1.0,
        travel_time_minutes=5,
        road_type=RoadEdge.RoadType.LOCAL,
        is_bidirectional=True,
    )

    return n1, n2, n3


def create_shared_ride_passenger(
    pickup_node,
    destination_node,
):
    passenger = create_passenger()

    vehicle = create_driver_and_vehicle(
        current_node=pickup_node,
    )

    ride_request = RideRequest.objects.create(
        passenger=passenger,
        ride_type=RideRequest.RideType.SHARED,
        passenger_count=1,
        pickup_node=pickup_node,
        destination_node=destination_node,
        status=RideRequest.Status.ASSIGNED,
    )

    ride = Ride.objects.create(
        vehicle=vehicle,

        # Ride خودش RideType ندارد،
        # پس از enum مربوط به RideRequest استفاده می‌کنیم.
        ride_type=RideRequest.RideType.SHARED,

        status=Ride.Status.ASSIGNED,
    )

    ride_passenger = (
        RidePassenger.objects.create(
            ride=ride,
            ride_request=ride_request,
        )
    )

    route = Route.objects.create(
        ride=ride,
        revision=1,
    )

    return (
        ride_passenger,
        route,
    )


# =========================================================
# 1. Shared Baseline Created
# =========================================================

def test_shared_passenger_baseline_created():
    n1, _, n3 = (
        create_simple_network()
    )

    ride_passenger, route = (
        create_shared_ride_passenger(
            pickup_node=n1,
            destination_node=n3,
        )
    )

    reference_time = timezone.now()

    baseline = (
        SharedPassengerBaselineService
        .create_baseline(
            ride_passenger=ride_passenger,
            expected_dropoff_minutes=12,
            route_revision=route.revision,
            reference_time=reference_time,
        )
    )

    # N1 → N2 → N3
    # 5 + 5 = 10 minutes
    assert (
        baseline.direct_trip_time_minutes
        == 10
    )

    assert (
        baseline.baseline_route_revision
        == 1
    )

    expected_dropoff = (
        reference_time
        + timedelta(
            minutes=12
        )
    )

    assert (
        baseline.baseline_expected_dropoff_at
        == expected_dropoff
    )

    assert (
        SharedPassengerBaseline.objects.count()
        == 1
    )


# =========================================================
# 2. Private Ride Rejected
# =========================================================

def test_private_passenger_baseline_rejected():
    n1, _, n3 = (
        create_simple_network()
    )

    passenger = create_passenger()

    vehicle = create_driver_and_vehicle(
        current_node=n1
    )

    ride_request = RideRequest.objects.create(
        passenger=passenger,
        ride_type=RideRequest.RideType.PRIVATE,
        passenger_count=1,
        pickup_node=n1,
        destination_node=n3,
        status=RideRequest.Status.ASSIGNED,
    )

    ride = Ride.objects.create(
        vehicle=vehicle,

        # Ride.RideType نداریم
        ride_type=RideRequest.RideType.PRIVATE,

        status=Ride.Status.ASSIGNED,
    )

    ride_passenger = (
        RidePassenger.objects.create(
            ride=ride,
            ride_request=ride_request,
        )
    )

    with pytest.raises(
        SharedBaselineError
    ):
        (
            SharedPassengerBaselineService
            .create_baseline(
                ride_passenger=ride_passenger,
                expected_dropoff_minutes=10,
                route_revision=1,
            )
        )


# =========================================================
# 3. Unreachable Direct Route Rejected
# =========================================================

def test_unreachable_direct_route_rejected():
    n1 = RoadNode.objects.create(
        name="N1",
        x=0,
        y=0,
    )

    n2 = RoadNode.objects.create(
        name="N2",
        x=10,
        y=10,
    )

    ride_passenger, route = (
        create_shared_ride_passenger(
            pickup_node=n1,
            destination_node=n2,
        )
    )

    # هیچ Edge بین N1 و N2 وجود ندارد.

    with pytest.raises(
        SharedBaselineError
    ):
        (
            SharedPassengerBaselineService
            .create_baseline(
                ride_passenger=ride_passenger,
                expected_dropoff_minutes=15,
                route_revision=route.revision,
            )
        )


# =========================================================
# 4. Existing Baseline Must Not Be Overwritten
# =========================================================

def test_existing_baseline_is_not_overwritten():
    n1, _, n3 = (
        create_simple_network()
    )

    ride_passenger, route = (
        create_shared_ride_passenger(
            pickup_node=n1,
            destination_node=n3,
        )
    )

    first_time = timezone.now()

    first_baseline = (
        SharedPassengerBaselineService
        .create_baseline(
            ride_passenger=ride_passenger,
            expected_dropoff_minutes=12,
            route_revision=1,
            reference_time=first_time,
        )
    )

    original_dropoff = (
        first_baseline
        .baseline_expected_dropoff_at
    )

    original_direct_time = (
        first_baseline
        .direct_trip_time_minutes
    )

    # تلاش دوم با ETA و revision متفاوت
    second_baseline = (
        SharedPassengerBaselineService
        .create_baseline(
            ride_passenger=ride_passenger,
            expected_dropoff_minutes=30,
            route_revision=5,
            reference_time=first_time,
        )
    )

    second_baseline.refresh_from_db()

    # باید همان Baseline قبلی باشد
    assert (
        first_baseline.id
        == second_baseline.id
    )

    # Expected Dropoff نباید تغییر کند
    assert (
        second_baseline
        .baseline_expected_dropoff_at
        == original_dropoff
    )

    # Route revision اولیه باید ثابت بماند
    assert (
        second_baseline
        .baseline_route_revision
        == 1
    )

    # Direct time هم نباید تغییر کند
    assert (
        second_baseline
        .direct_trip_time_minutes
        == original_direct_time
    )

    # فقط یک Baseline باید وجود داشته باشد
    assert (
        SharedPassengerBaseline.objects.count()
        == 1
    )