from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from fleet.models import Vehicle
from rides.models import (
    Ride,
    RideRequest,
)
from road_network.models import RoadNode
from road_network.services import (
    RoadNetworkError,
    RoadNetworkService,
)
from shared_ride.models import (
    Route,
    RouteStop,
)


# =========================================================
# Error
# =========================================================

class SharedMovementError(Exception):
    pass


# =========================================================
# Movement Actions
# =========================================================

class SharedMovementAction:

    MOVED = "MOVED"

    STOP_COMPLETED = "STOP_COMPLETED"

    RIDE_COMPLETED = "RIDE_COMPLETED"


# =========================================================
# Movement Result
# =========================================================

@dataclass(frozen=True)
class SharedMovementResult:

    action: str

    vehicle_id: int

    ride_id: int

    route_id: int

    current_node_id: int

    completed_stop_id: int | None = None

    next_stop_id: int | None = None


# =========================================================
# Shared Route Movement Service
# =========================================================

class SharedRouteMovementService:

    # =====================================================
    # Lock Current Shared State
    # =====================================================

    @staticmethod
    def _lock_shared_state(
        vehicle_id,
    ):
        """
        Vehicle + Ride + Route را برای یک
        movement transaction قفل می‌کنیم.

        عمداً current_node را داخل
        select_related روی select_for_update
        نمی‌آوریم تا مشکل nullable outer join
        در PostgreSQL ایجاد نشود.
        """

        try:
            vehicle = (
                Vehicle.objects
                .select_for_update()
                .get(
                    pk=vehicle_id
                )
            )

        except Vehicle.DoesNotExist:
            raise SharedMovementError(
                "Vehicle does not exist."
            )


        if (
            vehicle.ride_mode
            != Vehicle.RideMode.SHARED
        ):
            raise SharedMovementError(
                (
                    "Vehicle is not currently "
                    "serving a shared ride."
                )
            )


        if vehicle.current_node_id is None:
            raise SharedMovementError(
                "Vehicle has no current node."
            )


        # =============================================
        # Find current active Shared Ride
        # =============================================

        rides = list(
            Ride.objects
            .select_for_update()
            .filter(
                vehicle=vehicle,

                ride_type=(
                    RideRequest.RideType.SHARED
                ),

                status__in=[
                    Ride.Status.ASSIGNED,
                    Ride.Status.ACCEPTED,
                    Ride.Status.IN_PROGRESS,
                ],
            )
            .order_by("-id")[:2]
        )


        if len(rides) != 1:
            raise SharedMovementError(
                (
                    "Vehicle must have exactly one "
                    "active shared ride."
                )
            )


        ride = rides[0]


        # Driver must accept first.
        if (
            ride.status
            == Ride.Status.ASSIGNED
        ):
            raise SharedMovementError(
                (
                    "Shared ride must be accepted "
                    "before movement can start."
                )
            )


        try:
            route = (
                Route.objects
                .select_for_update()
                .get(
                    ride=ride,
                    status=Route.Status.ACTIVE,
                )
            )

        except Route.DoesNotExist:
            raise SharedMovementError(
                "Active shared route was not found."
            )


        return (
            vehicle,
            ride,
            route,
        )


    # =====================================================
    # Get Next Pending Stop
    # =====================================================

    @staticmethod
    def _get_next_pending_stop(
        route,
    ):
        """
        همیشه کمترین sequence_number
        باید Stop بعدی باشد.
        """

        return (
            RouteStop.objects
            .select_for_update()
            .filter(
                route=route,

                status=(
                    RouteStop.Status.PENDING
                ),
            )
            .order_by(
                "sequence_number",
                "id",
            )
            .first()
        )


    # =====================================================
    # Finish Entire Shared Ride
    # =====================================================

    @staticmethod
    def _finish_shared_ride(
        *,
        vehicle,
        ride,
        route,
    ):
        """
        وقتی هیچ PENDING RouteStop باقی نماند:

        Route → COMPLETED
        Ride → COMPLETED
        Vehicle → IDLE
        """

        route.status = (
            Route.Status.COMPLETED
        )

        route.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )


        ride.status = (
            Ride.Status.COMPLETED
        )

        ride.save(
            update_fields=[
                "status",
            ]
        )


        vehicle.ride_mode = (
            Vehicle.RideMode.IDLE
        )

        vehicle.save(
            update_fields=[
                "ride_mode",
                "updated_at",
            ]
        )


    # =====================================================
    # Complete Current RouteStop
    # =====================================================

    @staticmethod
    def _complete_stop(
        *,
        vehicle,
        ride,
        route,
        stop,
    ):
        """
        Taxi باید دقیقاً روی Node مربوط به Stop باشد.
        """

        if (
            vehicle.current_node_id
            != stop.node_id
        ):
            raise SharedMovementError(
                (
                    "Vehicle has not reached "
                    "the route stop yet."
                )
            )


        now = timezone.now()


        # =================================================
        # PICKUP
        # =================================================

        if (
            stop.stop_type
            == RouteStop.StopType.PICKUP
        ):

            stop.status = (
                RouteStop.Status.COMPLETED
            )

            stop.actual_arrival_time = now

            stop.save(
                update_fields=[
                    "status",
                    "actual_arrival_time",
                    "updated_at",
                ]
            )


            # First real passenger pickup starts ride.
            if (
                ride.status
                == Ride.Status.ACCEPTED
            ):

                ride.status = (
                    Ride.Status.IN_PROGRESS
                )

                ride.save(
                    update_fields=[
                        "status",
                    ]
                )


        # =================================================
        # DROPOFF
        # =================================================

        elif (
            stop.stop_type
            == RouteStop.StopType.DROPOFF
        ):

            stop.status = (
                RouteStop.Status.COMPLETED
            )

            stop.actual_arrival_time = now

            stop.save(
                update_fields=[
                    "status",
                    "actual_arrival_time",
                    "updated_at",
                ]
            )


            # =============================================
            # Passenger Request → COMPLETED
            # =============================================

            ride_request_id = (
                stop
                .ride_passenger
                .ride_request_id
            )


            ride_request = (
                RideRequest.objects
                .select_for_update()
                .get(
                    pk=ride_request_id
                )
            )


            ride_request.status = (
                RideRequest.Status.COMPLETED
            )

            ride_request.save(
                update_fields=[
                    "status",
                ]
            )


        else:
            raise SharedMovementError(
                "Unknown route stop type."
            )


    # =====================================================
    # Main Node-By-Node Movement
    # =====================================================

    @staticmethod
    @transaction.atomic
    def advance_shared_ride(
        vehicle_id,
    ):
        """
        یک Step از Shared Ride را اجرا می‌کند.

        هر call:

        - یا Taxi را فقط ONE EDGE حرکت می‌دهد
        - یا Stop فعلی را complete می‌کند
        - یا با رسیدن به Stop آن را complete می‌کند
        - یا کل Ride را تمام می‌کند
        """

        (
            vehicle,
            ride,
            route,
        ) = (
            SharedRouteMovementService
            ._lock_shared_state(
                vehicle_id
            )
        )


        # =================================================
        # 1. Next Stop
        # =================================================

        next_stop = (
            SharedRouteMovementService
            ._get_next_pending_stop(
                route
            )
        )


        # Defensive:
        # Active route without pending stops.
        if next_stop is None:

            (
                SharedRouteMovementService
                ._finish_shared_ride(
                    vehicle=vehicle,
                    ride=ride,
                    route=route,
                )
            )


            return SharedMovementResult(
                action=(
                    SharedMovementAction
                    .RIDE_COMPLETED
                ),

                vehicle_id=vehicle.id,

                ride_id=ride.id,

                route_id=route.id,

                current_node_id=(
                    vehicle.current_node_id
                ),
            )


        # =================================================
        # 2. Already At Stop
        # =================================================

        if (
            vehicle.current_node_id
            == next_stop.node_id
        ):

            (
                SharedRouteMovementService
                ._complete_stop(
                    vehicle=vehicle,
                    ride=ride,
                    route=route,
                    stop=next_stop,
                )
            )


            following_stop = (
                SharedRouteMovementService
                ._get_next_pending_stop(
                    route
                )
            )


            # =============================================
            # Final Stop Completed
            # =============================================

            if following_stop is None:

                (
                    SharedRouteMovementService
                    ._finish_shared_ride(
                        vehicle=vehicle,
                        ride=ride,
                        route=route,
                    )
                )


                return SharedMovementResult(
                    action=(
                        SharedMovementAction
                        .RIDE_COMPLETED
                    ),

                    vehicle_id=vehicle.id,

                    ride_id=ride.id,

                    route_id=route.id,

                    current_node_id=(
                        vehicle.current_node_id
                    ),

                    completed_stop_id=(
                        next_stop.id
                    ),
                )


            return SharedMovementResult(
                action=(
                    SharedMovementAction
                    .STOP_COMPLETED
                ),

                vehicle_id=vehicle.id,

                ride_id=ride.id,

                route_id=route.id,

                current_node_id=(
                    vehicle.current_node_id
                ),

                completed_stop_id=(
                    next_stop.id
                ),

                next_stop_id=(
                    following_stop.id
                ),
            )


        # =================================================
        # 3. Current Node
        # =================================================

        current_node = (
            RoadNode.objects.get(
                pk=vehicle.current_node_id
            )
        )


        target_node = (
            RoadNode.objects.get(
                pk=next_stop.node_id
            )
        )


        # =================================================
        # 4. Shortest Path To Next Stop
        # =================================================

        try:
            path = (
                RoadNetworkService
                .shortest_path(
                    current_node,
                    target_node,
                )
            )

        except RoadNetworkError as error:

            raise SharedMovementError(
                (
                    "Next shared route stop "
                    "is unreachable."
                )
            ) from error


        if len(path) < 2:

            raise SharedMovementError(
                (
                    "Could not determine the "
                    "next movement node."
                )
            )


        # =================================================
        # 5. Move Exactly ONE Edge
        # =================================================

        next_node = path[1]


        vehicle.current_node_id = (
            next_node.id
        )

        vehicle.save(
            update_fields=[
                "current_node",
                "updated_at",
            ]
        )


        # =================================================
        # 6. Reached RouteStop?
        # =================================================

        if (
            next_node.id
            == next_stop.node_id
        ):

            (
                SharedRouteMovementService
                ._complete_stop(
                    vehicle=vehicle,
                    ride=ride,
                    route=route,
                    stop=next_stop,
                )
            )


            following_stop = (
                SharedRouteMovementService
                ._get_next_pending_stop(
                    route
                )
            )


            # =============================================
            # Final Dropoff / Final Stop
            # =============================================

            if following_stop is None:

                (
                    SharedRouteMovementService
                    ._finish_shared_ride(
                        vehicle=vehicle,
                        ride=ride,
                        route=route,
                    )
                )


                return SharedMovementResult(
                    action=(
                        SharedMovementAction
                        .RIDE_COMPLETED
                    ),

                    vehicle_id=vehicle.id,

                    ride_id=ride.id,

                    route_id=route.id,

                    current_node_id=(
                        next_node.id
                    ),

                    completed_stop_id=(
                        next_stop.id
                    ),
                )


            return SharedMovementResult(
                action=(
                    SharedMovementAction
                    .STOP_COMPLETED
                ),

                vehicle_id=vehicle.id,

                ride_id=ride.id,

                route_id=route.id,

                current_node_id=(
                    next_node.id
                ),

                completed_stop_id=(
                    next_stop.id
                ),

                next_stop_id=(
                    following_stop.id
                ),
            )


        # =================================================
        # 7. Normal Intermediate Movement
        # =================================================

        return SharedMovementResult(
            action=(
                SharedMovementAction.MOVED
            ),

            vehicle_id=vehicle.id,

            ride_id=ride.id,

            route_id=route.id,

            current_node_id=(
                next_node.id
            ),

            next_stop_id=(
                next_stop.id
            ),
        )