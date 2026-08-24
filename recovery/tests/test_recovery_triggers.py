import pytest

from django.contrib.auth.models import User

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from accounts.services import (
    DriverAvailabilityError,
    set_driver_availability,
)
from fleet.models import Vehicle
from recovery.models import RecoveryEvent
from rides.models import (
    Ride,
    RideRequest,
)
from rides.services import (
    assign_private_ride,
    reject_ride,
)
from road_network.models import RoadNode


pytestmark = pytest.mark.django_db


# =========================================================
# Helpers
# =========================================================

def create_scenario():

    node = RoadNode.objects.create(
        name="RECOVERY_TRIGGER_NODE",
        x=1,
        y=0,
    )


    # =====================================================
    # Passenger
    # =====================================================

    passenger_user = (
        User.objects.create_user(
            username="trigger_passenger",
            password="StrongPass123!",
        )
    )


    UserProfile.objects.create(
        user=passenger_user,
        role=UserProfile.Role.PASSENGER,
    )


    passenger = (
        PassengerProfile.objects.create(
            user=passenger_user
        )
    )


    # =====================================================
    # Driver
    # =====================================================

    driver_user = (
        User.objects.create_user(
            username="trigger_driver",
            password="StrongPass123!",
        )
    )


    UserProfile.objects.create(
        user=driver_user,
        role=UserProfile.Role.DRIVER,
    )


    driver = DriverProfile.objects.create(

        user=driver_user,

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

        ride_mode=(
            Vehicle.RideMode.IDLE
        ),

        current_node=node,
    )


    # =====================================================
    # Request + Ride
    # =====================================================

    ride_request = (
        RideRequest.objects.create(

            passenger=passenger,

            ride_type=(
                RideRequest.RideType.PRIVATE
            ),

            passenger_count=1,

            pickup_node=node,

            destination_node=node,

            status=(
                RideRequest.Status.PENDING
            ),
        )
    )


    ride = assign_private_ride(
        ride_request,
        vehicle,
    )


    return (
        driver,
        vehicle,
        ride_request,
        ride,
    )


# =========================================================
# 1. Driver Reject schedules Recovery
# =========================================================

def test_driver_reject_schedules_recovery(
    monkeypatch,
    django_capture_on_commit_callbacks,
):

    (
        driver,
        vehicle,
        ride_request,
        ride,
    ) = create_scenario()


    calls = []


    def fake_recovery(
        *,
        ride_id,
        failed_vehicle_id,
        trigger_type,
    ):

        calls.append(
            (
                ride_id,
                failed_vehicle_id,
                trigger_type,
            )
        )


    monkeypatch.setattr(
        "recovery.triggers.run_recovery_safely",
        fake_recovery,
    )


    with django_capture_on_commit_callbacks(
        execute=True
    ):

        reject_ride(
            ride,
            driver,
        )


    ride.refresh_from_db()
    ride_request.refresh_from_db()
    vehicle.refresh_from_db()


    assert (
        ride.status
        == Ride.Status.REJECTED
    )

    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )


    assert len(calls) == 1


    assert (
        calls[0][0]
        == ride.id
    )

    assert (
        calls[0][1]
        == vehicle.id
    )

    assert (
        calls[0][2]
        == RecoveryEvent
        .TriggerType
        .DRIVER_REJECT
    )


# =========================================================
# 2. Driver OFFLINE before pickup schedules Recovery
# =========================================================

def test_driver_offline_before_pickup_schedules_recovery(
    monkeypatch,
    django_capture_on_commit_callbacks,
):

    (
        driver,
        vehicle,
        ride_request,
        ride,
    ) = create_scenario()


    calls = []


    def fake_recovery(
        *,
        ride_id,
        failed_vehicle_id,
        trigger_type,
    ):

        calls.append(
            (
                ride_id,
                failed_vehicle_id,
                trigger_type,
            )
        )


    monkeypatch.setattr(
        "recovery.triggers.run_recovery_safely",
        fake_recovery,
    )


    with django_capture_on_commit_callbacks(
        execute=True
    ):

        set_driver_availability(
            driver,

            DriverProfile
            .AvailabilityStatus
            .OFFLINE,
        )


    driver.refresh_from_db()
    vehicle.refresh_from_db()
    ride.refresh_from_db()
    ride_request.refresh_from_db()


    assert (
        driver.availability_status
        == DriverProfile
        .AvailabilityStatus
        .OFFLINE
    )

    assert (
        ride.status
        == Ride.Status.CANCELLED
    )

    assert (
        ride_request.status
        == RideRequest.Status.PENDING
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.IDLE
    )


    assert len(calls) == 1


    assert (
        calls[0][2]
        == RecoveryEvent
        .TriggerType
        .DRIVER_UNAVAILABLE
    )


# =========================================================
# 3. Driver cannot go OFFLINE after pickup
# =========================================================

def test_driver_cannot_go_offline_after_pickup(
    monkeypatch,
    django_capture_on_commit_callbacks,
):

    (
        driver,
        vehicle,
        ride_request,
        ride,
    ) = create_scenario()


    ride.status = (
        Ride.Status.IN_PROGRESS
    )

    ride.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )


    calls = []


    def fake_recovery(**kwargs):

        calls.append(kwargs)


    monkeypatch.setattr(
        "recovery.triggers.run_recovery_safely",
        fake_recovery,
    )


    with pytest.raises(
        DriverAvailabilityError
    ):

        with django_capture_on_commit_callbacks(
            execute=True
        ):

            set_driver_availability(

                driver,

                DriverProfile
                .AvailabilityStatus
                .OFFLINE,
            )


    driver.refresh_from_db()
    ride.refresh_from_db()
    vehicle.refresh_from_db()


    assert (
        driver.availability_status
        == DriverProfile
        .AvailabilityStatus
        .ONLINE
    )

    assert (
        ride.status
        == Ride.Status.IN_PROGRESS
    )

    assert (
        vehicle.ride_mode
        == Vehicle.RideMode.PRIVATE
    )

    assert calls == []