from dataclasses import dataclass
from time import perf_counter

from django.db import transaction
from django.utils import timezone

from assignment.services import (
    AssignmentError,
    AssignmentService,
)
from recovery.models import RecoveryEvent
from recovery.planning import (
    RecoveryPlanningResult,
)
from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)


# =========================================================
# Recovery Application Error
# =========================================================

class RecoveryApplicationError(Exception):
    pass


# =========================================================
# Applied Assignment
# =========================================================

@dataclass(frozen=True)
class AppliedRecoveryAssignment:

    ride_request_id: int

    old_ride_id: int

    new_ride_id: int

    replacement_vehicle_id: int


# =========================================================
# Final Result
# =========================================================

@dataclass(frozen=True)
class RecoveryApplicationResult:

    recovery_event_id: int

    recovered_group_count: int

    assignments: tuple[
        AppliedRecoveryAssignment,
        ...
    ]


# =========================================================
# Recovery Application Service
# =========================================================

class RecoveryApplicationService:

    # =====================================================
    # Apply Best PRIVATE Recovery Plan
    # =====================================================

    @classmethod
    def apply_best_private_plan(
        cls,
        *,
        recovery_event,
        planning_result,
    ):
        """
        Apply the best PRIVATE Recovery Plan.

        Important:

        Planning already selected a feasible candidate.

        However we do NOT trust the old candidate state.

        During application we reuse:

        AssignmentService.create_private_taxi_hold()
        AssignmentService.confirm_private_taxi_hold()

        Therefore the replacement taxi is revalidated
        again while database rows are locked.

        Everything is wrapped inside one outer
        transaction so partial reassignment cannot remain
        in the database.
        """

        started_at = perf_counter()


        try:

            with transaction.atomic():

                result = (
                    cls._apply_best_private_plan_locked(
                        recovery_event=(
                            recovery_event
                        ),
                        planning_result=(
                            planning_result
                        ),
                        started_at=(
                            started_at
                        ),
                    )
                )


        except Exception as error:

            # =================================================
            # The main transaction above has rolled back.
            #
            # Save FAILED state separately so the audit event
            # itself is not lost.
            # =================================================

            duration_ms = int(
                (
                    perf_counter()
                    - started_at
                )
                * 1000
            )


            RecoveryEvent.objects.filter(
                pk=recovery_event.pk
            ).update(

                status=(
                    RecoveryEvent
                    .Status
                    .FAILED
                ),

                recovery_duration_ms=(
                    duration_ms
                ),

                completed_at=(
                    timezone.now()
                ),

                message=(
                    f"Recovery failed: {error}"
                ),
            )


            if isinstance(
                error,
                RecoveryApplicationError,
            ):

                raise


            raise RecoveryApplicationError(
                str(error)
            ) from error


        return result


    # =====================================================
    # Locked Implementation
    # =====================================================

    @classmethod
    def _apply_best_private_plan_locked(
        cls,
        *,
        recovery_event,
        planning_result,
        started_at,
    ):

        # =================================================
        # 1. Lock Recovery Event
        # =================================================

        try:

            event = (
                RecoveryEvent.objects
                .select_for_update()
                .select_related(
                    "ride",
                    "failed_vehicle",
                )
                .get(
                    pk=recovery_event.pk
                )
            )

        except RecoveryEvent.DoesNotExist:

            raise RecoveryApplicationError(
                "Recovery event does not exist."
            )


        if (
            event.status
            != RecoveryEvent.Status.PENDING
        ):

            raise RecoveryApplicationError(
                "Only pending recovery events can be applied."
            )


        # =================================================
        # 2. Best Plan
        # =================================================

        if not isinstance(
            planning_result,
            RecoveryPlanningResult,
        ):

            raise RecoveryApplicationError(
                "Invalid recovery planning result."
            )


        best_plan = (
            planning_result.best_plan
        )


        if best_plan is None:

            raise RecoveryApplicationError(
                "No feasible recovery plan exists."
            )


        # =================================================
        # 3. Increment 5.9A currently handles PRIVATE
        # =================================================

        for candidate in best_plan.assignments:

            if (
                candidate.ride_type
                != RideRequest.RideType.PRIVATE
            ):

                raise RecoveryApplicationError(
                    (
                        "Private recovery application "
                        "cannot apply a shared candidate."
                    )
                )


        # =================================================
        # 4. Lock Failed Ride
        # =================================================

        try:

            failed_ride = (
                Ride.objects
                .select_for_update()
                .get(
                    pk=event.ride_id
                )
            )

        except Ride.DoesNotExist:

            raise RecoveryApplicationError(
                "Failed ride no longer exists."
            )


        # Driver Reject recovery should already have
        # transitioned the old Ride to REJECTED.
        if (
            event.trigger_type
            == RecoveryEvent.TriggerType.DRIVER_REJECT
        ):

            if (
                failed_ride.status
                != Ride.Status.REJECTED
            ):

                raise RecoveryApplicationError(
                    (
                        "Driver-reject recovery requires "
                        "the failed ride to be REJECTED."
                    )
                )


        # =================================================
        # 5. Event → PROCESSING
        # =================================================

        event.status = (
            RecoveryEvent.Status.PROCESSING
        )

        event.affected_passenger_groups = (
            planning_result
            .affected_group_count
        )

        event.message = (
            "Applying private recovery plan."
        )

        event.save(
            update_fields=[
                "status",
                "affected_passenger_groups",
                "message",
            ]
        )


        applied_assignments = []


        # =================================================
        # 6. Apply Every Assignment
        # =================================================

        for candidate in best_plan.assignments:

            # ---------------------------------------------
            # Failed taxi cannot be selected again
            # ---------------------------------------------

            if (
                candidate.vehicle_id
                == event.failed_vehicle_id
            ):

                raise RecoveryApplicationError(
                    "Failed taxi cannot be used as replacement."
                )


            # ---------------------------------------------
            # Passenger must belong to old failed Ride
            # ---------------------------------------------

            old_membership = (
                RidePassenger.objects
                .select_for_update()
                .filter(
                    ride_id=failed_ride.id,

                    ride_request_id=(
                        candidate
                        .ride_request_id
                    ),
                )
                .first()
            )


            if old_membership is None:

                raise RecoveryApplicationError(
                    (
                        "Passenger group does not belong "
                        "to the failed ride."
                    )
                )


            # ---------------------------------------------
            # Lock Request
            # ---------------------------------------------

            try:

                ride_request = (
                    RideRequest.objects
                    .select_for_update()
                    .select_related(
                        "pickup_node",
                        "destination_node",
                    )
                    .get(
                        pk=(
                            candidate
                            .ride_request_id
                        )
                    )
                )

            except RideRequest.DoesNotExist:

                raise RecoveryApplicationError(
                    "Affected ride request no longer exists."
                )


            # Reject lifecycle should already return
            # the Request to PENDING.
            if (
                ride_request.status
                != RideRequest.Status.PENDING
            ):

                raise RecoveryApplicationError(
                    (
                        "Affected ride request "
                        "is no longer pending."
                    )
                )


            if (
                ride_request.ride_type
                != RideRequest.RideType.PRIVATE
            ):

                raise RecoveryApplicationError(
                    "Expected a private ride request."
                )


            # =================================================
            # 7. Revalidate Replacement Taxi
            #
            # Existing Assignment Engine already performs:
            #
            # - row locks
            # - driver online check
            # - vehicle availability
            # - IDLE state
            # - capacity
            # - reachability
            # - pickup ETA
            # =================================================

            try:

                hold = (
                    AssignmentService
                    .create_private_taxi_hold(
                        ride_request=(
                            ride_request
                        ),

                        vehicle_id=(
                            candidate
                            .vehicle_id
                        ),
                    )
                )


                (
                    new_ride,
                    confirmed_hold,
                ) = (
                    AssignmentService
                    .confirm_private_taxi_hold(
                        hold
                    )
                )


            except AssignmentError as error:

                raise RecoveryApplicationError(
                    (
                        "Replacement taxi failed "
                        f"final revalidation: {error}"
                    )
                ) from error


            # confirmed_hold is intentionally kept by
            # AssignmentEngine for audit/history.
            assert confirmed_hold is not None


            applied_assignments.append(

                AppliedRecoveryAssignment(

                    ride_request_id=(
                        ride_request.id
                    ),

                    old_ride_id=(
                        failed_ride.id
                    ),

                    new_ride_id=(
                        new_ride.id
                    ),

                    replacement_vehicle_id=(
                        candidate
                        .vehicle_id
                    ),
                )
            )


        # =================================================
        # 8. Recovery COMPLETED
        # =================================================

        duration_ms = int(
            (
                perf_counter()
                - started_at
            )
            * 1000
        )


        event.status = (
            RecoveryEvent.Status.COMPLETED
        )

        event.recovery_duration_ms = (
            duration_ms
        )

        event.completed_at = (
            timezone.now()
        )

        event.message = (
            (
                "Recovery completed: "
                f"{len(applied_assignments)}/"
                f"{planning_result.affected_group_count} "
                "passenger groups reassigned."
            )
        )


        event.save(
            update_fields=[
                "status",
                "recovery_duration_ms",
                "completed_at",
                "message",
            ]
        )


        return RecoveryApplicationResult(

            recovery_event_id=(
                event.id
            ),

            recovered_group_count=(
                len(applied_assignments)
            ),

            assignments=tuple(
                applied_assignments
            ),
        )