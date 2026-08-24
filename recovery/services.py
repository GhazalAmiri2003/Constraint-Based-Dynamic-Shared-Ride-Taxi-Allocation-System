from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)
from shared_ride.models import RouteStop


# =========================================================
# Recovery Error
# =========================================================

class RecoveryError(Exception):
    pass


# =========================================================
# Affected Passenger Group
# =========================================================

@dataclass(frozen=True)
class AffectedPassengerGroup:

    ride_passenger_id: int
    ride_request_id: int

    ride_type: str

    passenger_count: int

    pickup_node_id: int
    destination_node_id: int

    original_request_time: datetime

    # هرچه کمتر باشد Passenger urgent‌تر است.
    #
    # مثال:
    #
    # 8 min remaining -> urgency پایین‌تر
    # 2 min remaining -> urgency بالاتر
    # -3 min          -> passenger already overdue
    pickup_slack_minutes: float


    @property
    def priority_key(self):
        """
        Recovery priority:

        1. Lowest remaining pickup slack
           -> more urgent first

        2. Older original request
           -> older passenger first

        3. Request ID
           -> deterministic tie-break
        """

        return (
            self.pickup_slack_minutes,
            self.original_request_time,
            self.ride_request_id,
        )


# =========================================================
# Recovery Priority Service
# =========================================================

class RecoveryPriorityService:

    # =====================================================
    # Maximum Pickup Wait
    # =====================================================

    @staticmethod
    def get_max_pickup_wait(
        ride_request,
    ):

        if (
            ride_request.ride_type
            == RideRequest.RideType.SHARED
        ):

            return getattr(
                settings,
                "MAX_SHARED_PICKUP_WAIT_MINUTES",
                10,
            )


        return getattr(
            settings,
            "MAX_PRIVATE_PICKUP_WAIT_MINUTES",
            10,
        )


    # =====================================================
    # Pickup Urgency
    # =====================================================

    @classmethod
    def calculate_pickup_slack(
        cls,
        ride_request,
        reference_time=None,
    ):
        """
        Pickup urgency is represented by the amount
        of pickup-wait budget still remaining.

        Lower value = more urgent.

        Example:

        max wait = 10 min

        request age = 3 min
        slack = 7 min

        request age = 9 min
        slack = 1 min

        request age = 12 min
        slack = -2 min
        """

        if reference_time is None:
            reference_time = timezone.now()


        request_time = getattr(
            ride_request,
            "created_at",
            None,
        )


        if request_time is None:

            raise RecoveryError(
                "RideRequest.created_at is required "
                "for recovery priority calculation."
            )


        elapsed_minutes = (
            (
                reference_time
                - request_time
            )
            .total_seconds()
            / 60.0
        )


        max_wait = (
            cls.get_max_pickup_wait(
                ride_request
            )
        )


        return (
            float(max_wait)
            - elapsed_minutes
        )


    # =====================================================
    # Rank Groups
    # =====================================================

    @staticmethod
    def rank_groups(
        groups,
    ):
        """
        Most urgent passenger group comes first.
        """

        return sorted(
            groups,
            key=lambda group:
                group.priority_key,
        )


# =========================================================
# Recovery Detection Service
# =========================================================

class RecoveryDetectionService:

    # =====================================================
    # Private Ride Pickup State
    # =====================================================

    @staticmethod
    def _private_group_not_picked_up(
        ride,
    ):
        """
        PRIVATE:

        ASSIGNED / ACCEPTED
            -> Passenger has not been picked up yet.

        IN_PROGRESS
            -> Passenger is already onboard.
        """

        return (
                ride.status
                in [
                    Ride.Status.ASSIGNED,
                    Ride.Status.ACCEPTED,

                    # Driver Reject before Pickup
                    Ride.Status.REJECTED,

                    # Driver Unavailable recovery
                    # later may use CANCELLED.
                    Ride.Status.CANCELLED,
                ]
        )

    # =====================================================
    # Shared Ride Pickup Stop
    # =====================================================

    @staticmethod
    def _get_shared_pickup_stop(
        ride_passenger,
    ):

        return (
            RouteStop.objects
            .filter(
                ride_passenger=ride_passenger,

                stop_type=(
                    RouteStop
                    .StopType
                    .PICKUP
                ),
            )
            .order_by(
                "sequence_number",
                "id",
            )
            .first()
        )


    # =====================================================
    # Build Affected Group
    # =====================================================

    @classmethod
    def _build_group(
        cls,
        ride_passenger,
        reference_time,
    ):

        ride_request = (
            ride_passenger.ride_request
        )


        request_time = getattr(
            ride_request,
            "created_at",
            None,
        )


        if request_time is None:

            raise RecoveryError(
                "RideRequest.created_at is required "
                "for recovery."
            )


        pickup_slack = (
            RecoveryPriorityService
            .calculate_pickup_slack(
                ride_request,
                reference_time=(
                    reference_time
                ),
            )
        )


        return AffectedPassengerGroup(

            ride_passenger_id=(
                ride_passenger.id
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
                request_time
            ),

            pickup_slack_minutes=(
                pickup_slack
            ),
        )


    # =====================================================
    # Find Not-Yet-Picked-Up Groups
    # =====================================================

    @classmethod
    def find_affected_groups(
        cls,
        ride,
        reference_time=None,
    ):
        """
        Return only Passenger Groups affected by the
        disruption that have NOT yet been picked up.

        PRIVATE:
            Ride must still be ASSIGNED/ACCEPTED.

        SHARED:
            The group's PICKUP RouteStop must still
            be PENDING.

        Passenger groups already onboard are intentionally
        excluded from Recovery.
        """

        if reference_time is None:
            reference_time = timezone.now()

        # COMPLETED Ride cannot enter Recovery.
        #
        # REJECTED / CANCELLED may still represent
        # a pre-pickup disruption. In that case the
        # RideRequest remains PENDING and must be recovered.
        if (
                ride.status
                == Ride.Status.COMPLETED
        ):
            return []

        ride_passengers = (
            RidePassenger.objects
            .filter(
                ride=ride
            )
            .select_related(
                "ride_request",
                "ride_request__pickup_node",
                "ride_request__destination_node",
            )
            .order_by(
                "ride_request__id"
            )
        )


        affected_groups = []


        for ride_passenger in ride_passengers:

            ride_request = (
                ride_passenger.ride_request
            )


            # ---------------------------------------------
            # Ignore already finished passenger requests.
            # ---------------------------------------------

            if (
                ride_request.status
                in [
                    RideRequest.Status.COMPLETED,
                    RideRequest.Status.CANCELLED,
                ]
            ):

                continue


            # =============================================
            # PRIVATE
            # =============================================

            if (
                ride_request.ride_type
                == RideRequest.RideType.PRIVATE
            ):

                if not (
                    cls
                    ._private_group_not_picked_up(
                        ride
                    )
                ):

                    # Ride is already IN_PROGRESS,
                    # therefore Passenger is onboard.
                    continue


            # =============================================
            # SHARED
            # =============================================

            elif (
                ride_request.ride_type
                == RideRequest.RideType.SHARED
            ):

                pickup_stop = (
                    cls
                    ._get_shared_pickup_stop(
                        ride_passenger
                    )
                )


                if pickup_stop is None:

                    # This indicates an invalid Shared Route
                    # state and should not be silently ignored.
                    raise RecoveryError(
                        (
                            "Shared passenger group "
                            f"{ride_passenger.id} "
                            "has no pickup RouteStop."
                        )
                    )


                # Pickup completed means Passenger
                # is already onboard.
                if (
                    pickup_stop.status
                    == RouteStop.Status.COMPLETED
                ):

                    continue


                # Cancelled passenger is not recoverable.
                if (
                    pickup_stop.status
                    == RouteStop.Status.CANCELLED
                ):

                    continue


                # Only a pending pickup is recoverable.
                if (
                    pickup_stop.status
                    != RouteStop.Status.PENDING
                ):

                    continue


            # =============================================
            # Unknown Ride Type
            # =============================================

            else:

                continue


            affected_groups.append(
                cls._build_group(
                    ride_passenger,
                    reference_time,
                )
            )


        # Proposal requirement:
        #
        # Recovery scope is intentionally limited
        # to at most two affected passenger groups.
        if len(affected_groups) > 2:

            raise RecoveryError(
                (
                    "Recovery supports at most "
                    "two affected passenger groups."
                )
            )


        # Final priority:
        #
        # urgency first,
        # then original request time.
        return (
            RecoveryPriorityService
            .rank_groups(
                affected_groups
            )
        )