import logging
from time import perf_counter

from django.utils import timezone

from fleet.models import Vehicle
from notifications.services import (
    NotificationService,
)
from recovery.application import (
    RecoveryApplicationService,
)
from recovery.cleanup import (
    cleanup_failed_shared_route,
)
from recovery.models import (
    RecoveryEvent,
)
from recovery.planning import (
    RecoveryPlanService,
)
from recovery.services import (
    RecoveryDetectionService,
)
from recovery.shared_application import (
    SharedRecoveryApplicationService,
)
from rides.models import (
    Ride,
    RideRequest,
)


# =========================================================
# Logger
# =========================================================

logger = logging.getLogger(__name__)


# =========================================================
# Recovery Orchestrator Error
# =========================================================

class RecoveryOrchestratorError(Exception):
    pass


# =========================================================
# Recovery Orchestrator
# =========================================================

class RecoveryOrchestrator:

    # =====================================================
    # Main Recovery Entry Point
    # =====================================================

    @classmethod
    def recover_ride(
        cls,
        *,
        ride_id,
        failed_vehicle_id,
        trigger_type,
    ):
        """
        Complete Recovery workflow.

        Steps:

        1. Load failed Ride and Vehicle
        2. Create RecoveryEvent
        3. Detect passenger groups not yet picked up
        4. Send RECOVERY_STARTED notification
        5. Generate replacement taxi plans
        6. Reject infeasible plans
        7. Select best feasible plan
        8. Apply plan transactionally
        9. Update Route / RouteStops / ETA
        10. Send success/failure notifications
        11. Measure total Recovery execution time

        Called by:

        - DRIVER_REJECT
        - DRIVER_UNAVAILABLE
        """

        started_at = perf_counter()


        # =================================================
        # 1. Load Failed Ride
        # =================================================

        try:

            ride = (
                Ride.objects
                .select_related(
                    "vehicle",
                )
                .get(
                    pk=ride_id
                )
            )

        except Ride.DoesNotExist:

            raise RecoveryOrchestratorError(
                "Ride does not exist."
            )


        # =================================================
        # 2. Load Failed Vehicle
        # =================================================

        try:

            failed_vehicle = (
                Vehicle.objects
                .get(
                    pk=failed_vehicle_id
                )
            )

        except Vehicle.DoesNotExist:

            raise RecoveryOrchestratorError(
                "Failed vehicle does not exist."
            )


        # =================================================
        # 3. Validate Ride ↔ Vehicle
        # =================================================

        if (
            ride.vehicle_id
            != failed_vehicle.id
        ):

            raise RecoveryOrchestratorError(
                (
                    "The failed vehicle does not "
                    "belong to this ride."
                )
            )


        # =================================================
        # 4. Prevent Duplicate Active Recovery
        # =================================================

        existing_event = (
            RecoveryEvent.objects
            .filter(
                ride=ride,

                failed_vehicle=(
                    failed_vehicle
                ),

                trigger_type=(
                    trigger_type
                ),

                status__in=[
                    RecoveryEvent.Status.PENDING,
                    RecoveryEvent.Status.PROCESSING,
                ],
            )
            .order_by(
                "-created_at"
            )
            .first()
        )


        if existing_event is not None:

            return existing_event


        # =================================================
        # 5. Create Recovery Event
        # =================================================

        event = (
            RecoveryEvent.objects
            .create(

                ride=ride,

                failed_vehicle=(
                    failed_vehicle
                ),

                trigger_type=(
                    trigger_type
                ),

                status=(
                    RecoveryEvent.Status.PENDING
                ),

                message=(
                    "Recovery started."
                ),
            )
        )


        try:

            # =============================================
            # 6. Detect Affected Passenger Groups
            #
            # Only passengers NOT yet picked up are
            # eligible for Increment 5 Recovery.
            # =============================================

            affected_groups = (
                RecoveryDetectionService
                .find_affected_groups(
                    ride
                )
            )


            event.affected_passenger_groups = (
                len(affected_groups)
            )

            event.save(
                update_fields=[
                    "affected_passenger_groups",
                ]
            )


            # =============================================
            # 7. Nothing To Recover
            # =============================================

            if not affected_groups:

                cls._complete_without_recovery(
                    event=event,
                    started_at=started_at,
                )

                return event


            # =============================================
            # 8. Load Affected Requests
            # =============================================

            affected_requests = {}


            for group in affected_groups:

                ride_request = (
                    RideRequest.objects
                    .select_related(
                        "passenger",
                        "passenger__user",
                    )
                    .get(
                        pk=(
                            group.ride_request_id
                        )
                    )
                )


                affected_requests[
                    ride_request.id
                ] = ride_request


                # =========================================
                # RECOVERY_STARTED Notification
                # =========================================

                NotificationService \
                    .recovery_started(

                        ride_request=(
                            ride_request
                        ),

                        recovery_event=(
                            event
                        ),
                    )


            # =============================================
            # 9. Generate Replacement Taxi Plans
            #
            # RecoveryPlanService reuses:
            #
            # - AssignmentService
            # - SharedTaxiOptionService
            #
            # Therefore existing feasibility rules
            # are reused rather than duplicated.
            # =============================================

            planning_result = (
                RecoveryPlanService
                .generate_recovery_plans(

                    affected_groups=(
                        affected_groups
                    ),

                    failed_vehicle_id=(
                        failed_vehicle.id
                    ),
                )
            )


            # =============================================
            # 10. No Feasible Replacement
            # =============================================

            if (
                planning_result.best_plan
                is None
            ):

                # -----------------------------------------
                # Important Shared-Ride Cleanup
                #
                # Do not leave:
                #
                # Route       = ACTIVE
                # RouteStops  = PENDING
                #
                # after Recovery has permanently failed.
                # -----------------------------------------

                cls._cleanup_failed_shared_state(
                    ride=ride,

                    failed_vehicle=(
                        failed_vehicle
                    ),
                )


                # -----------------------------------------
                # Mark Event FAILED + Notify Passenger
                # -----------------------------------------

                cls._mark_failed(
                    event=event,

                    affected_requests=(
                        affected_requests
                    ),

                    started_at=(
                        started_at
                    ),

                    message=(
                        "No feasible recovery plan exists."
                    ),
                )


                return event


            # =============================================
            # 11. Apply Selected Plan
            # =============================================

            if (
                ride.ride_type
                == RideRequest.RideType.PRIVATE
            ):

                application_result = (
                    RecoveryApplicationService
                    .apply_best_private_plan(

                        recovery_event=(
                            event
                        ),

                        planning_result=(
                            planning_result
                        ),
                    )
                )


            elif (
                ride.ride_type
                == RideRequest.RideType.SHARED
            ):

                application_result = (
                    SharedRecoveryApplicationService
                    .apply_best_shared_plan(

                        recovery_event=(
                            event
                        ),

                        planning_result=(
                            planning_result
                        ),
                    )
                )


            else:

                raise RecoveryOrchestratorError(
                    "Unsupported ride type."
                )


            # =============================================
            # 12. Successfully Recovered Requests
            # =============================================

            recovered_request_ids = set()


            for assignment in (
                application_result.assignments
            ):

                recovered_request_ids.add(
                    assignment.ride_request_id
                )


                ride_request = (
                    affected_requests[
                        assignment.ride_request_id
                    ]
                )


                # =========================================
                # RECOVERY_COMPLETED Notification
                # =========================================

                NotificationService \
                    .recovery_completed(

                        ride_request=(
                            ride_request
                        ),

                        recovery_event=(
                            event
                        ),

                        replacement_vehicle_id=(
                            assignment
                            .replacement_vehicle_id
                        ),
                    )


            # =============================================
            # 13. Groups Not Included In Selected Plan
            #
            # Example:
            #
            # 2 affected groups
            # but only 1 can be feasibly reassigned.
            # =============================================

            for (
                request_id,
                ride_request,
            ) in affected_requests.items():

                if (
                    request_id
                    not in recovered_request_ids
                ):

                    NotificationService \
                        .recovery_failed(

                            ride_request=(
                                ride_request
                            ),

                            recovery_event=(
                                event
                            ),
                        )


            # =============================================
            # 14. Measure Entire Recovery Workflow
            #
            # Includes:
            #
            # detection
            # priority
            # candidate generation
            # constraints
            # ranking
            # transactional application
            # =============================================

            elapsed_ms = int(
                (
                    perf_counter()
                    - started_at
                )
                * 1000
            )


            RecoveryEvent.objects.filter(
                pk=event.pk
            ).update(

                recovery_duration_ms=(
                    elapsed_ms
                ),
            )


            event.refresh_from_db()


            return event


        # =================================================
        # 15. Unexpected Recovery Failure
        # =================================================

        except Exception as error:

            # ---------------------------------------------
            # Shared Ride:
            #
            # Make sure an old ACTIVE Route does not
            # remain orphaned after Recovery failure.
            # ---------------------------------------------

            cls._cleanup_failed_shared_state(
                ride=ride,

                failed_vehicle=(
                    failed_vehicle
                ),
            )


            # ---------------------------------------------
            # Event → FAILED
            # ---------------------------------------------

            cls._mark_failed_after_exception(
                event=event,

                started_at=(
                    started_at
                ),

                error=error,
            )


            raise RecoveryOrchestratorError(
                str(error)
            ) from error


    # =====================================================
    # Cleanup Failed Shared State
    # =====================================================

    @staticmethod
    def _cleanup_failed_shared_state(
        *,
        ride,
        failed_vehicle,
    ):
        """
        Clean the failed Shared Ride state when Recovery
        cannot continue.

        PRIVATE rides have no Route/RouteStops, so nothing
        is required here.

        SHARED:
            pending RouteStops -> CANCELLED
            active Route       -> CANCELLED
            failed Vehicle     -> IDLE

        Cleanup is best-effort.

        A cleanup failure must not hide the original
        Recovery failure.
        """

        if (
            ride.ride_type
            != RideRequest.RideType.SHARED
        ):

            return


        try:

            cleanup_failed_shared_route(
                ride_id=ride.id,

                failed_vehicle_id=(
                    failed_vehicle.id
                ),
            )


        except Exception:

            logger.exception(
                (
                    "Could not clean failed SHARED "
                    "Ride %s after Recovery failure."
                ),
                ride.id,
            )


    # =====================================================
    # Recovery With Zero Affected Groups
    # =====================================================

    @staticmethod
    def _complete_without_recovery(
        *,
        event,
        started_at,
    ):

        elapsed_ms = int(
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
            elapsed_ms
        )

        event.completed_at = (
            timezone.now()
        )

        event.message = (
            (
                "No pre-pickup passenger groups "
                "required recovery."
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


    # =====================================================
    # No Feasible Plan
    # =====================================================

    @staticmethod
    def _mark_failed(
        *,
        event,
        affected_requests,
        started_at,
        message,
    ):

        elapsed_ms = int(
            (
                perf_counter()
                - started_at
            )
            * 1000
        )


        # =================================================
        # Event → FAILED
        # =================================================

        event.status = (
            RecoveryEvent.Status.FAILED
        )

        event.recovery_duration_ms = (
            elapsed_ms
        )

        event.completed_at = (
            timezone.now()
        )

        event.message = (
            message
        )


        event.save(
            update_fields=[
                "status",
                "recovery_duration_ms",
                "completed_at",
                "message",
            ]
        )


        # =================================================
        # Notify Every Affected Passenger
        # =================================================

        for ride_request in (
            affected_requests.values()
        ):

            NotificationService \
                .recovery_failed(

                    ride_request=(
                        ride_request
                    ),

                    recovery_event=(
                        event
                    ),
                )


    # =====================================================
    # Unexpected Failure
    # =====================================================

    @staticmethod
    def _mark_failed_after_exception(
        *,
        event,
        started_at,
        error,
    ):

        elapsed_ms = int(
            (
                perf_counter()
                - started_at
            )
            * 1000
        )


        RecoveryEvent.objects.filter(
            pk=event.pk
        ).update(

            status=(
                RecoveryEvent.Status.FAILED
            ),

            recovery_duration_ms=(
                elapsed_ms
            ),

            completed_at=(
                timezone.now()
            ),

            message=(
                f"Recovery failed: {error}"
            ),
        )