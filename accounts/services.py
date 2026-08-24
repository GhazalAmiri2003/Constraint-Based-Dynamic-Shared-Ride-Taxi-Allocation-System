from django.db import transaction
from django.utils import timezone

from fleet.models import Vehicle

from .models import DriverProfile


# =========================================================
# Driver Availability Error
# =========================================================

class DriverAvailabilityError(Exception):
    pass


# =========================================================
# Driver Availability Service
# =========================================================

@transaction.atomic
def set_driver_availability(
    driver_profile,
    new_status,
):
    """
    Update Driver availability.

    Going OFFLINE:

    IDLE taxi
        -> normal OFFLINE

    ASSIGNED / ACCEPTED ride
        -> pre-pickup disruption
        -> cancel old assignment
        -> requests become PENDING
        -> vehicle becomes IDLE
        -> Recovery is triggered after COMMIT

    IN_PROGRESS ride
        -> OFFLINE is rejected because a passenger
           has already been picked up and Increment 5
           Recovery is intentionally pre-pickup only.
    """

    # =====================================================
    # 1. Lock Driver
    # =====================================================

    driver_profile = (
        DriverProfile.objects
        .select_for_update()
        .get(
            pk=driver_profile.pk
        )
    )


    # =====================================================
    # 2. Same Status
    # =====================================================

    if (
        driver_profile.availability_status
        == new_status
    ):

        return driver_profile


    # =====================================================
    # 3. Going OFFLINE
    # =====================================================

    recovery_target = None


    if (
        new_status
        == DriverProfile
        .AvailabilityStatus
        .OFFLINE
    ):

        # ---------------------------------------------
        # Lock Vehicle
        # ---------------------------------------------

        try:

            vehicle = (
                Vehicle.objects
                .select_for_update()
                .get(
                    driver=driver_profile
                )
            )

        except Vehicle.DoesNotExist:

            vehicle = None


        # =============================================
        # Taxi currently has an active assignment
        # =============================================

        if (
            vehicle
            and
            vehicle.ride_mode
            != Vehicle.RideMode.IDLE
        ):

            # Local import keeps accounts independent
            # from rides at module-import time.
            from rides.models import (
                Ride,
                RideRequest,
            )


            active_rides = list(

                Ride.objects
                .select_for_update()
                .filter(
                    vehicle=vehicle,

                    status__in=[
                        Ride.Status.ASSIGNED,
                        Ride.Status.ACCEPTED,
                        Ride.Status.IN_PROGRESS,
                    ],
                )
                .order_by(
                    "id"
                )
            )


            # -----------------------------------------
            # Vehicle says it is busy but no active
            # Ride exists -> inconsistent DB state.
            # -----------------------------------------

            if not active_rides:

                raise DriverAvailabilityError(
                    (
                        "Vehicle has an active ride mode "
                        "but no active ride exists."
                    )
                )


            # System architecture expects one active Ride
            # per Vehicle.
            if (
                len(active_rides)
                != 1
            ):

                raise DriverAvailabilityError(
                    (
                        "Vehicle has multiple active rides; "
                        "driver availability cannot be changed."
                    )
                )


            active_ride = (
                active_rides[0]
            )


            # =========================================
            # Passenger already picked up
            # =========================================

            if (
                active_ride.status
                == Ride.Status.IN_PROGRESS
            ):

                raise DriverAvailabilityError(
                    (
                        "Driver cannot go offline after "
                        "passenger pickup."
                    )
                )


            # =========================================
            # Pre-Pickup Driver Unavailability
            #
            # ASSIGNED / ACCEPTED
            # =========================================

            active_ride.status = (
                Ride.Status.CANCELLED
            )

            active_ride.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )


            # -----------------------------------------
            # Affected Requests become recoverable.
            # -----------------------------------------

            (
                RideRequest.objects
                .filter(
                    ride_links__ride=(
                        active_ride
                    )
                )
                .exclude(
                    status__in=[
                        RideRequest.Status.COMPLETED,
                        RideRequest.Status.CANCELLED,
                    ]
                )
                .update(
                    status=(
                        RideRequest.Status.PENDING
                    ),
                    updated_at=(
                        timezone.now()
                    ),
                )
            )


            # -----------------------------------------
            # Failed Taxi no longer owns the Ride.
            # Driver OFFLINE prevents it from appearing
            # as a replacement candidate.
            # -----------------------------------------

            vehicle.ride_mode = (
                Vehicle.RideMode.IDLE
            )

            vehicle.save(
                update_fields=[
                    "ride_mode",
                    "updated_at",
                ]
            )


            recovery_target = (
                active_ride.id,
                vehicle.id,
            )


    # =====================================================
    # 4. Update Driver Status
    # =====================================================

    driver_profile.availability_status = (
        new_status
    )

    driver_profile.save(
        update_fields=[
            "availability_status",
        ]
    )


    # =====================================================
    # 5. Trigger Recovery AFTER COMMIT
    # =====================================================

    if recovery_target is not None:

        from recovery.triggers import (
            schedule_driver_unavailable_recovery,
        )


        (
            ride_id,
            vehicle_id,
        ) = recovery_target


        schedule_driver_unavailable_recovery(
            ride_id=ride_id,

            failed_vehicle_id=(
                vehicle_id
            ),
        )


    return driver_profile