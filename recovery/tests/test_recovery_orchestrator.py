from types import SimpleNamespace

import pytest

from django.contrib.auth.models import User

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)
from fleet.models import Vehicle
from notifications.models import Notification
from recovery.models import RecoveryEvent
from recovery.orchestrator import (
    RecoveryOrchestrator,
)
from recovery.planning import (
    RecoveryPlanService,
)
from recovery.application import (
    RecoveryApplicationService,
)
from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)
from road_network.models import (
    RoadNode,
)


pytestmark = pytest.mark.django_db


def create_scenario():

    node = RoadNode.objects.create(
        name="ORCHESTRATOR_N1",
        x=1,
        y=0,
    )


    passenger_user = User.objects.create_user(
        username="orchestrator_passenger",
        password="StrongPass123!",
    )


    UserProfile.objects.create(
        user=passenger_user,
        role=UserProfile.Role.PASSENGER,
    )


    passenger = PassengerProfile.objects.create(
        user=passenger_user
    )


    driver_user = User.objects.create_user(
        username="orchestrator_driver",
        password="StrongPass123!",
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


    ride_request = RideRequest.objects.create(

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


    ride = Ride.objects.create(

        vehicle=vehicle,

        ride_type=(
            RideRequest.RideType.PRIVATE
        ),

        status=(
            Ride.Status.REJECTED
        ),
    )


    RidePassenger.objects.create(

        ride=ride,

        ride_request=ride_request,
    )


    return (
        ride,
        ride_request,
        vehicle,
    )


def test_recovery_orchestrator_creates_notifications(
    monkeypatch,
):

    (
        ride,
        ride_request,
        vehicle,
    ) = create_scenario()


    fake_candidate = (
        SimpleNamespace(

            ride_request_id=(
                ride_request.id
            ),

            replacement_vehicle_id=999,
        )
    )


    fake_application_result = (
        SimpleNamespace(
            assignments=(
                fake_candidate,
            )
        )
    )


    fake_plan = (
        SimpleNamespace(
            best_plan=object(),
        )
    )


    monkeypatch.setattr(

        RecoveryPlanService,

        "generate_recovery_plans",

        classmethod(
            lambda cls, **kwargs:
                fake_plan
        ),
    )


    monkeypatch.setattr(

        RecoveryApplicationService,

        "apply_best_private_plan",

        classmethod(
            lambda cls, **kwargs:
                fake_application_result
        ),
    )


    event = (
        RecoveryOrchestrator
        .recover_ride(

            ride_id=ride.id,

            failed_vehicle_id=(
                vehicle.id
            ),

            trigger_type=(
                RecoveryEvent
                .TriggerType
                .DRIVER_REJECT
            ),
        )
    )


    assert event is not None


    assert (
        Notification.objects
        .filter(
            recipient=(
                ride_request
                .passenger
                .user
            ),

            notification_type=(
                Notification
                .Type
                .RECOVERY_STARTED
            ),
        )
        .exists()
    )


    assert (
        Notification.objects
        .filter(
            recipient=(
                ride_request
                .passenger
                .user
            ),

            notification_type=(
                Notification
                .Type
                .RECOVERY_COMPLETED
            ),
        )
        .exists()
    )