from datetime import timedelta

import pytest

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from assignment.hold_services import (
    TaxiHoldError,
    TaxiHoldService,
)
from assignment.models import TaxiHold
from fleet.models import Vehicle
from rides.models import RideRequest
from road_network.models import RoadNode


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

    PassengerProfile.objects.create(
        user=user,
    )

    return user


def create_driver_with_vehicle(
    username,
    current_node,
):
    user = User.objects.create_user(
        username=username,
        password="StrongPass123!",
    )

    UserProfile.objects.create(
        user=user,
        role=UserProfile.Role.DRIVER,
    )

    driver_profile = DriverProfile.objects.create(
        user=user,
        availability_status=(
            DriverProfile
            .AvailabilityStatus
            .ONLINE
        ),
    )

    return Vehicle.objects.create(
        driver=driver_profile,
        capacity=4,
        is_available=True,
        ride_mode=Vehicle.RideMode.IDLE,
        current_node=current_node,
    )


@pytest.fixture
def nodes():
    pickup = RoadNode.objects.create(
        name="HOLD_PICKUP",
        x=0,
        y=0,
    )

    destination = RoadNode.objects.create(
        name="HOLD_DESTINATION",
        x=5,
        y=5,
    )

    taxi_node = RoadNode.objects.create(
        name="HOLD_TAXI_NODE",
        x=1,
        y=0,
    )

    second_taxi_node = RoadNode.objects.create(
        name="HOLD_TAXI_NODE_2",
        x=2,
        y=0,
    )

    return {
        "pickup": pickup,
        "destination": destination,
        "taxi_node": taxi_node,
        "second_taxi_node": second_taxi_node,
    }


def create_ride_request(
    passenger,
    nodes,
):
    return RideRequest.objects.create(
        passenger=passenger.passenger_profile,
        ride_type=RideRequest.RideType.PRIVATE,
        passenger_count=1,
        pickup_node=nodes["pickup"],
        destination_node=nodes["destination"],
        status=RideRequest.Status.PENDING,
    )


# =========================================================
# 1. Successful Hold
# =========================================================

@override_settings(
    TAXI_HOLD_DURATION_SECONDS=120
)
@pytest.mark.django_db
def test_taxi_can_be_held_for_pending_request(
    nodes,
):
    passenger = create_passenger(
        "hold_passenger_1"
    )

    ride_request = create_ride_request(
        passenger,
        nodes,
    )

    vehicle = create_driver_with_vehicle(
        "hold_driver_1",
        nodes["taxi_node"],
    )

    before = timezone.now()

    hold = TaxiHoldService.create_hold(
        ride_request,
        vehicle,
    )

    after = timezone.now()

    assert hold.status == TaxiHold.Status.ACTIVE

    assert (
        hold.ride_request_id
        == ride_request.id
    )

    assert (
        hold.vehicle_id
        == vehicle.id
    )

    assert hold.expires_at > before

    assert hold.expires_at <= (
        after + timedelta(seconds=120)
    )


# =========================================================
# 2. Same request + same taxi = same Hold
# =========================================================

@pytest.mark.django_db
def test_same_request_and_taxi_returns_existing_hold(
    nodes,
):
    passenger = create_passenger(
        "hold_passenger_2"
    )

    ride_request = create_ride_request(
        passenger,
        nodes,
    )

    vehicle = create_driver_with_vehicle(
        "hold_driver_2",
        nodes["taxi_node"],
    )

    first_hold = TaxiHoldService.create_hold(
        ride_request,
        vehicle,
    )

    second_hold = TaxiHoldService.create_hold(
        ride_request,
        vehicle,
    )

    assert first_hold.id == second_hold.id

    assert (
        TaxiHold.objects.filter(
            status=TaxiHold.Status.ACTIVE
        ).count()
        == 1
    )


# =========================================================
# 3. Same request cannot hold two taxis
# =========================================================

@pytest.mark.django_db
def test_request_cannot_hold_two_taxis(
    nodes,
):
    passenger = create_passenger(
        "hold_passenger_3"
    )

    ride_request = create_ride_request(
        passenger,
        nodes,
    )

    first_vehicle = create_driver_with_vehicle(
        "hold_driver_3a",
        nodes["taxi_node"],
    )

    second_vehicle = create_driver_with_vehicle(
        "hold_driver_3b",
        nodes["second_taxi_node"],
    )

    TaxiHoldService.create_hold(
        ride_request,
        first_vehicle,
    )

    with pytest.raises(
        TaxiHoldError
    ):
        TaxiHoldService.create_hold(
            ride_request,
            second_vehicle,
        )

    assert (
        TaxiHold.objects.filter(
            status=TaxiHold.Status.ACTIVE
        ).count()
        == 1
    )


# =========================================================
# 4. Same taxi cannot be held by two requests
# =========================================================

@pytest.mark.django_db
def test_taxi_cannot_be_held_by_two_requests(
    nodes,
):
    first_passenger = create_passenger(
        "hold_passenger_4a"
    )

    second_passenger = create_passenger(
        "hold_passenger_4b"
    )

    first_request = create_ride_request(
        first_passenger,
        nodes,
    )

    second_request = create_ride_request(
        second_passenger,
        nodes,
    )

    vehicle = create_driver_with_vehicle(
        "hold_driver_4",
        nodes["taxi_node"],
    )

    TaxiHoldService.create_hold(
        first_request,
        vehicle,
    )

    with pytest.raises(
        TaxiHoldError
    ):
        TaxiHoldService.create_hold(
            second_request,
            vehicle,
        )

    assert (
        TaxiHold.objects.filter(
            vehicle=vehicle,
            status=TaxiHold.Status.ACTIVE,
        ).count()
        == 1
    )


# =========================================================
# 5. Hold can be released
# =========================================================

@pytest.mark.django_db
def test_active_hold_can_be_released(
    nodes,
):
    passenger = create_passenger(
        "hold_passenger_5"
    )

    ride_request = create_ride_request(
        passenger,
        nodes,
    )

    vehicle = create_driver_with_vehicle(
        "hold_driver_5",
        nodes["taxi_node"],
    )

    hold = TaxiHoldService.create_hold(
        ride_request,
        vehicle,
    )

    released_hold = (
        TaxiHoldService.release_hold(
            hold
        )
    )

    assert (
        released_hold.status
        == TaxiHold.Status.RELEASED
    )

    released_hold.refresh_from_db()

    assert (
        released_hold.status
        == TaxiHold.Status.RELEASED
    )


# =========================================================
# 6. Expired Hold becomes EXPIRED
# =========================================================

@pytest.mark.django_db
def test_expired_hold_is_not_returned_as_active(
    nodes,
):
    passenger = create_passenger(
        "hold_passenger_6"
    )

    ride_request = create_ride_request(
        passenger,
        nodes,
    )

    vehicle = create_driver_with_vehicle(
        "hold_driver_6",
        nodes["taxi_node"],
    )

    hold = TaxiHoldService.create_hold(
        ride_request,
        vehicle,
    )

    # زمان Hold را به گذشته می‌بریم
    TaxiHold.objects.filter(
        pk=hold.pk
    ).update(
        expires_at=(
            timezone.now()
            - timedelta(seconds=1)
        )
    )

    active_hold = (
        TaxiHoldService.get_active_hold(
            ride_request
        )
    )

    assert active_hold is None

    hold.refresh_from_db()

    assert (
        hold.status
        == TaxiHold.Status.EXPIRED
    )


# =========================================================
# 7. Expired taxi can be held again
# =========================================================

@pytest.mark.django_db
def test_expired_taxi_hold_allows_new_request(
    nodes,
):
    first_passenger = create_passenger(
        "hold_passenger_7a"
    )

    second_passenger = create_passenger(
        "hold_passenger_7b"
    )

    first_request = create_ride_request(
        first_passenger,
        nodes,
    )

    second_request = create_ride_request(
        second_passenger,
        nodes,
    )

    vehicle = create_driver_with_vehicle(
        "hold_driver_7",
        nodes["taxi_node"],
    )

    first_hold = TaxiHoldService.create_hold(
        first_request,
        vehicle,
    )

    # Hold اول منقضی می‌شود
    TaxiHold.objects.filter(
        pk=first_hold.pk
    ).update(
        expires_at=(
            timezone.now()
            - timedelta(seconds=1)
        )
    )

    second_hold = TaxiHoldService.create_hold(
        second_request,
        vehicle,
    )

    first_hold.refresh_from_db()

    assert (
        first_hold.status
        == TaxiHold.Status.EXPIRED
    )

    assert (
        second_hold.status
        == TaxiHold.Status.ACTIVE
    )

    assert (
        second_hold.vehicle_id
        == vehicle.id
    )

    assert (
        second_hold.ride_request_id
        == second_request.id
    )