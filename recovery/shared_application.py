from dataclasses import dataclass
from datetime import timedelta
from time import perf_counter

from django.db import transaction
from django.utils import timezone

from assignment.shared_confirmation_services import (
    SharedConfirmationError,
    SharedTaxiConfirmationService,
)
from fleet.models import Vehicle
from recovery.models import RecoveryEvent
from recovery.planning import RecoveryPlanningResult
from recovery.services import RecoveryDetectionService
from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)
from shared_ride.models import (
    Route,
    RouteStop,
)
from shared_ride.simulation import (
    SharedRouteSimulationService,
    SimulatedStop,
)


# =========================================================
# Error
# =========================================================

class SharedRecoveryApplicationError(Exception):
    pass


# =========================================================
# Result Objects
# =========================================================

@dataclass(frozen=True)
class AppliedSharedRecoveryAssignment:

    ride_request_id: int
    old_ride_id: int
    new_ride_id: int

    replacement_vehicle_id: int

    new_route_id: int
    new_ride_passenger_id: int


@dataclass(frozen=True)
class SharedRecoveryApplicationResult:

    recovery_event_id: int

    recovered_group_count: int

    assignments: tuple[
        AppliedSharedRecoveryAssignment,
        ...
    ]


# =========================================================
# Shared Recovery Application
# =========================================================

class SharedRecoveryApplicationService:

    # =====================================================
    # Public Entry Point
    # =====================================================

    @classmethod
    def apply_best_shared_plan(
        cls,
        *,
        recovery_event,
        planning_result,
    ):

        started_at = perf_counter()

        try:

            with transaction.atomic():

                result = (
                    cls._apply_locked(
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

            # Main transaction has rolled back.
            #
            # Store FAILED audit information separately.

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
                    f"Shared recovery failed: {error}"
                ),
            )

            if isinstance(
                error,
                SharedRecoveryApplicationError,
            ):

                raise

            raise SharedRecoveryApplicationError(
                str(error)
            ) from error

        return result


    # =====================================================
    # Locked Recovery
    # =====================================================

    @classmethod
    def _apply_locked(
        cls,
        *,
        recovery_event,
        planning_result,
        started_at,
    ):

        # =================================================
        # 1. Lock Event
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

            raise SharedRecoveryApplicationError(
                "Recovery event does not exist."
            )


        if (
            event.status
            != RecoveryEvent.Status.PENDING
        ):

            raise SharedRecoveryApplicationError(
                "Recovery event is not pending."
            )


        # =================================================
        # 2. Validate Planning Result
        # =================================================

        if not isinstance(
            planning_result,
            RecoveryPlanningResult,
        ):

            raise SharedRecoveryApplicationError(
                "Invalid recovery planning result."
            )


        best_plan = (
            planning_result.best_plan
        )


        if best_plan is None:

            raise SharedRecoveryApplicationError(
                "No feasible shared recovery plan exists."
            )


        for candidate in best_plan.assignments:

            if (
                candidate.ride_type
                != RideRequest.RideType.SHARED
            ):

                raise SharedRecoveryApplicationError(
                    (
                        "Shared recovery cannot apply "
                        "a PRIVATE candidate."
                    )
                )


        # =================================================
        # 3. Lock Failed Ride
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

            raise SharedRecoveryApplicationError(
                "Failed shared ride does not exist."
            )


        if (
            failed_ride.ride_type
            != RideRequest.RideType.SHARED
        ):

            raise SharedRecoveryApplicationError(
                "Failed ride is not SHARED."
            )


        # =================================================
        # 4. Lock Failed Vehicle
        # =================================================

        try:

            failed_vehicle = (
                Vehicle.objects
                .select_for_update()
                .get(
                    pk=event.failed_vehicle_id
                )
            )

        except Vehicle.DoesNotExist:

            raise SharedRecoveryApplicationError(
                "Failed vehicle does not exist."
            )


        # =================================================
        # 5. Lock Old Route
        # =================================================

        try:

            old_route = (
                Route.objects
                .select_for_update()
                .get(
                    ride=failed_ride,
                    status=Route.Status.ACTIVE,
                )
            )

        except Route.DoesNotExist:

            raise SharedRecoveryApplicationError(
                "Failed shared ride has no active route."
            )


        # =================================================
        # 6. Re-detect Affected Groups
        #
        # We do not trust the list calculated during
        # planning because state may have changed.
        # =================================================

        affected_groups = (
            RecoveryDetectionService
            .find_affected_groups(
                failed_ride
            )
        )


        if (
            len(affected_groups)
            != planning_result.affected_group_count
        ):

            raise SharedRecoveryApplicationError(
                (
                    "Affected passenger state changed "
                    "after recovery planning."
                )
            )


        affected_request_ids = {
            group.ride_request_id
            for group
            in affected_groups
        }


        planned_request_ids = {
            candidate.ride_request_id
            for candidate
            in best_plan.assignments
        }


        if not planned_request_ids.issubset(
            affected_request_ids
        ):

            raise SharedRecoveryApplicationError(
                (
                    "Recovery plan contains a passenger "
                    "that is no longer affected."
                )
            )


        # =================================================
        # 7. Event → PROCESSING
        # =================================================

        event.status = (
            RecoveryEvent.Status.PROCESSING
        )

        event.affected_passenger_groups = (
            len(affected_groups)
        )

        event.message = (
            "Applying shared recovery plan."
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
        # 8. Detach affected groups from failed Route
        # =================================================

        memberships_by_request = {}


        for group in affected_groups:

            try:

                membership = (
                    RidePassenger.objects
                    .select_for_update()
                    .get(
                        ride=failed_ride,

                        ride_request_id=(
                            group.ride_request_id
                        ),
                    )
                )

            except RidePassenger.DoesNotExist:

                raise SharedRecoveryApplicationError(
                    (
                        "Affected passenger membership "
                        "no longer exists."
                    )
                )


            memberships_by_request[
                group.ride_request_id
            ] = membership


            # ---------------------------------------------
            # Lock this group's RouteStops
            # ---------------------------------------------

            stops = list(

                RouteStop.objects
                .select_for_update()
                .filter(
                    route=old_route,
                    ride_passenger=membership,
                )
                .order_by(
                    "sequence_number",
                    "id",
                )
            )


            pickup_stop = next(
                (
                    stop
                    for stop in stops

                    if (
                        stop.stop_type
                        == RouteStop.StopType.PICKUP
                    )
                ),
                None,
            )


            if pickup_stop is None:

                raise SharedRecoveryApplicationError(
                    "Affected group has no pickup stop."
                )


            # Pre-pickup recovery ONLY.
            if (
                pickup_stop.status
                != RouteStop.Status.PENDING
            ):

                raise SharedRecoveryApplicationError(
                    (
                        "Passenger was already picked up; "
                        "pre-pickup recovery is no longer allowed."
                    )
                )


            # ---------------------------------------------
            # Cancel old pending stops.
            #
            # We do NOT delete them because they form
            # part of the recovery/history audit trail.
            # ---------------------------------------------

            for stop in stops:

                if (
                    stop.status
                    == RouteStop.Status.PENDING
                ):

                    stop.status = (
                        RouteStop.Status.CANCELLED
                    )

                    stop.save(
                        update_fields=[
                            "status",
                        ]
                    )


            # ---------------------------------------------
            # Request becomes available for replacement
            # assignment.
            # ---------------------------------------------

            ride_request = (
                RideRequest.objects
                .select_for_update()
                .get(
                    pk=group.ride_request_id
                )
            )


            if (
                ride_request.status
                in [
                    RideRequest.Status.COMPLETED,
                    RideRequest.Status.CANCELLED,
                ]
            ):

                raise SharedRecoveryApplicationError(
                    (
                        "Affected request can no longer "
                        "be recovered."
                    )
                )


            ride_request.status = (
                RideRequest.Status.PENDING
            )

            ride_request.save(
                update_fields=[
                    "status",
                ]
            )


        # =================================================
        # 9. Apply selected replacement assignments
        # =================================================

        for candidate in best_plan.assignments:

            if (
                candidate.vehicle_id
                == failed_vehicle.id
            ):

                raise SharedRecoveryApplicationError(
                    (
                        "Failed vehicle cannot be "
                        "its own replacement."
                    )
                )


            ride_request = (
                RideRequest.objects
                .select_for_update()
                .get(
                    pk=(
                        candidate
                        .ride_request_id
                    )
                )
            )


            if (
                ride_request.status
                != RideRequest.Status.PENDING
            ):

                raise SharedRecoveryApplicationError(
                    (
                        "Affected request is no longer "
                        "pending during recovery."
                    )
                )


            # =================================================
            # FINAL REVALIDATION
            #
            # SharedTaxiConfirmationService again validates:
            #
            # - Driver ONLINE
            # - Vehicle availability
            # - Capacity
            # - Route state
            # - Dynamic insertion
            # - pickup wait
            # - absolute delay
            # - relative delay
            # - group limit
            #
            # Therefore an old/stale Recovery Plan cannot
            # blindly modify the DB.
            # =================================================

            try:

                hold = (
                    SharedTaxiConfirmationService
                    .create_shared_taxi_hold(
                        ride_request=(
                            ride_request
                        ),

                        vehicle_id=(
                            candidate
                            .vehicle_id
                        ),
                    )
                )


                confirmation = (
                    SharedTaxiConfirmationService
                    .confirm_shared_taxi_hold(
                        hold
                    )
                )


            except SharedConfirmationError as error:

                raise SharedRecoveryApplicationError(
                    (
                        "Replacement shared taxi failed "
                        f"final revalidation: {error}"
                    )
                ) from error


            applied_assignments.append(

                AppliedSharedRecoveryAssignment(

                    ride_request_id=(
                        ride_request.id
                    ),

                    old_ride_id=(
                        failed_ride.id
                    ),

                    new_ride_id=(
                        confirmation.ride.id
                    ),

                    replacement_vehicle_id=(
                        candidate.vehicle_id
                    ),

                    new_route_id=(
                        confirmation.route.id
                    ),

                    new_ride_passenger_id=(
                        confirmation
                        .ride_passenger
                        .id
                    ),
                )
            )


        # =================================================
        # 10. Rebuild Remaining Failed Route
        # =================================================

        cls._rebuild_failed_route(
            route=old_route,
            vehicle=failed_vehicle,
        )


        # =================================================
        # 11. Event COMPLETED
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
                "Shared recovery completed: "
                f"{len(applied_assignments)}/"
                f"{len(affected_groups)} "
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


        return SharedRecoveryApplicationResult(

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


    # =====================================================
    # Rebuild Failed Route
    # =====================================================

    @classmethod
    def _rebuild_failed_route(
        cls,
        *,
        route,
        vehicle,
    ):
        """
        After affected passenger groups are removed:

        - keep historical CANCELLED stops
        - keep remaining passenger groups
        - recompute ETA / route time / distance
        - increment route revision

        If no active stops remain:
            Route -> CANCELLED
            Vehicle -> IDLE
        """

        active_stops = list(

            RouteStop.objects
            .select_for_update()
            .filter(
                route=route
            )
            .exclude(
                status=(
                    RouteStop.Status.CANCELLED
                )
            )
            .select_related(
                "ride_passenger",
                "ride_passenger__ride_request",
                "node",
            )
            .order_by(
                "sequence_number",
                "id",
            )
        )


        # =================================================
        # No active passenger groups remain
        # =================================================

        if not active_stops:

            route.status = (
                Route.Status.CANCELLED
            )

            route.total_estimated_time_minutes = 0

            route.total_estimated_distance_km = 0

            route.revision += 1


            route.save(
                update_fields=[
                    "status",
                    "total_estimated_time_minutes",
                    "total_estimated_distance_km",
                    "revision",
                ]
            )


            vehicle.ride_mode = (
                Vehicle.RideMode.IDLE
            )

            vehicle.save(
                update_fields=[
                    "ride_mode",
                ]
            )

            return


        # =================================================
        # Determine remaining pending stops
        # =================================================

        pending_stops = [

            stop
            for stop in active_stops

            if (
                stop.status
                == RouteStop.Status.PENDING
            )
        ]


        if not pending_stops:

            # Nothing remains to execute.

            route.status = (
                Route.Status.COMPLETED
            )

            route.revision += 1


            route.save(
                update_fields=[
                    "status",
                    "revision",
                ]
            )


            vehicle.ride_mode = (
                Vehicle.RideMode.IDLE
            )

            vehicle.save(
                update_fields=[
                    "ride_mode",
                ]
            )

            return


        if vehicle.current_node_id is None:

            raise SharedRecoveryApplicationError(
                (
                    "Failed vehicle has no current node; "
                    "remaining shared route cannot be rebuilt."
                )
            )


        # =================================================
        # Determine onboard groups
        # =================================================

        completed_pickup_ids = {

            stop.ride_passenger_id

            for stop in active_stops

            if (
                stop.stop_type
                == RouteStop.StopType.PICKUP

                and

                stop.status
                == RouteStop.Status.COMPLETED
            )
        }


        pending_dropoff_ids = {

            stop.ride_passenger_id

            for stop in pending_stops

            if (
                stop.stop_type
                == RouteStop.StopType.DROPOFF
            )
        }


        onboard_ids = (
            completed_pickup_ids
            & pending_dropoff_ids
        )


        initial_onboard = {}


        for stop in active_stops:

            if (
                stop.ride_passenger_id
                in onboard_ids
            ):

                initial_onboard[
                    f"rp:{stop.ride_passenger_id}"
                ] = (
                    stop
                    .ride_passenger
                    .ride_request
                    .passenger_count
                )


        # =================================================
        # Convert DB RouteStops → simulation stops
        # =================================================

        simulated_stops = []


        for stop in pending_stops:

            simulated_stops.append(

                SimulatedStop(

                    group_key=(
                        f"rp:{stop.ride_passenger_id}"
                    ),

                    passenger_count=(
                        stop
                        .ride_passenger
                        .ride_request
                        .passenger_count
                    ),

                    node=stop.node,

                    stop_type=stop.stop_type,
                )
            )


        simulation = (
            SharedRouteSimulationService
            .simulate(
                current_node=(
                    vehicle.current_node
                ),

                vehicle_capacity=(
                    vehicle.capacity
                ),

                stops=(
                    simulated_stops
                ),

                initial_onboard=(
                    initial_onboard
                ),
            )
        )


        if not simulation.is_valid:

            raise SharedRecoveryApplicationError(
                (
                    "Remaining shared route became invalid "
                    f"after recovery: {simulation.violations}"
                )
            )


        # =================================================
        # Update remaining ETAs
        # =================================================

        reference_time = (
            timezone.now()
        )


        for (
            route_stop,
            simulated_result,
        ) in zip(
            pending_stops,
            simulation.stop_results,
        ):

            route_stop.estimated_arrival_minutes = (
                simulated_result
                .arrival_minutes
            )

            route_stop.estimated_arrival_time = (
                reference_time
                + timedelta(
                    minutes=(
                        simulated_result
                        .arrival_minutes
                    )
                )
            )

            route_stop.save(
                update_fields=[
                    "estimated_arrival_minutes",
                    "estimated_arrival_time",
                ]
            )


        # =================================================
        # Update Route
        # =================================================

        route.total_estimated_time_minutes = (
            simulation.total_time_minutes
        )

        route.total_estimated_distance_km = (
            simulation.total_distance_km
        )

        route.revision += 1


        route.save(
            update_fields=[
                "total_estimated_time_minutes",
                "total_estimated_distance_km",
                "revision",
            ]
        )