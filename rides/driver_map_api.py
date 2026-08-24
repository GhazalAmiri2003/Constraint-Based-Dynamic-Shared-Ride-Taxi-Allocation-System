from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import DriverProfile
from accounts.permissions import IsDriver
from fleet.models import Vehicle
from rides.models import (
    Ride,
    RideRequest,
)
from road_network.services import (
    RoadNetworkError,
    RoadNetworkService,
)
from shared_ride.models import (
    Route,
    RouteStop,
)


# =========================================================
# Helpers
# =========================================================

def serialize_node(node):
    if node is None:
        return None

    return {
        "id": node.id,
        "name": node.name,
        "x": node.x,
        "y": node.y,
    }


def merge_paths(*paths):
    merged = []

    for path in paths:
        for node_id in path or []:
            node_id = int(node_id)

            if (
                not merged
                or merged[-1] != node_id
            ):
                merged.append(node_id)

    return merged


def shortest_path_ids(
    start_node,
    end_node,
):
    if (
        start_node is None
        or end_node is None
    ):
        return []

    try:
        return [
            node.id
            for node
            in RoadNetworkService.shortest_path(
                start_node,
                end_node,
            )
        ]

    except RoadNetworkError:
        return []


def serialize_group(
    ride_passenger,
):
    request = (
        ride_passenger.ride_request
    )

    return {
        "ride_passenger_id": (
            ride_passenger.id
        ),

        "ride_request_id": (
            request.id
        ),

        "passenger_username": (
            request.passenger.user.username
        ),

        "passenger_count": (
            request.passenger_count
        ),

        "request_status": (
            request.status
        ),

        "pickup_node": (
            serialize_node(
                request.pickup_node
            )
        ),

        "destination_node": (
            serialize_node(
                request.destination_node
            )
        ),
    }


# =========================================================
# Driver Operational Map API
# =========================================================

class DriverOperationalMapAPIView(
    APIView
):
    """
    Unified driver-side operational map payload.

    PRIVATE:
        Taxi current position
        Passenger pickup
        Passenger destination
        Current leg
        Full remaining route

    SHARED:
        Taxi current position
        All passenger groups
        Ordered RouteStops
        Next pending stop
        Current leg
        Full remaining ordered route
    """

    permission_classes = [
        IsDriver,
    ]


    def get(
        self,
        request,
    ):
        # =================================================
        # 1. Driver
        # =================================================

        driver = (
            DriverProfile.objects
            .filter(
                user=request.user
            )
            .first()
        )


        if driver is None:

            return Response(
                {
                    "detail": (
                        "Driver profile was not found."
                    )
                },
                status=(
                    status
                    .HTTP_403_FORBIDDEN
                ),
            )


        # =================================================
        # 2. Vehicle
        # =================================================

        vehicle = (
            Vehicle.objects
            .select_related(
                "current_node",
                "driver__user",
            )
            .filter(
                driver=driver
            )
            .first()
        )


        if vehicle is None:

            return Response(
                {
                    "detail": (
                        "Driver has no registered vehicle."
                    )
                },
                status=(
                    status
                    .HTTP_404_NOT_FOUND
                ),
            )


        vehicle_payload = {
            "id": vehicle.id,

            "ride_mode": (
                vehicle.ride_mode
            ),

            "is_available": (
                vehicle.is_available
            ),

            "capacity": (
                vehicle.capacity
            ),

            "current_node": (
                serialize_node(
                    vehicle.current_node
                )
            ),
        }


        # =================================================
        # 3. Active Ride
        # =================================================

        active_rides = list(

            Ride.objects
            .filter(
                vehicle=vehicle,

                status__in=[
                    Ride.Status.ASSIGNED,
                    Ride.Status.ACCEPTED,
                    Ride.Status.IN_PROGRESS,
                ],
            )
            .order_by(
                "-assigned_at"
            )[:2]
        )


        if not active_rides:

            return Response(
                {
                    "vehicle": (
                        vehicle_payload
                    ),

                    "active_ride": None,
                },
                status=(
                    status.HTTP_200_OK
                ),
            )


        if len(active_rides) > 1:

            return Response(
                {
                    "detail": (
                        "Vehicle has conflicting active rides."
                    )
                },
                status=(
                    status
                    .HTTP_409_CONFLICT
                ),
            )


        ride = active_rides[0]


        # =================================================
        # 4. Passenger Groups
        # =================================================

        groups = list(

            ride.passenger_groups
            .select_related(
                "ride_request",
                "ride_request__passenger__user",
                "ride_request__pickup_node",
                "ride_request__destination_node",
            )
            .order_by(
                "id"
            )
        )


        group_payload = [
            serialize_group(group)
            for group
            in groups
        ]


        # =================================================
        # 5. PRIVATE Ride
        # =================================================

        if (
            ride.ride_type
            == RideRequest.RideType.PRIVATE
        ):

            if len(groups) != 1:

                return Response(
                    {
                        "detail": (
                            "Private ride must have "
                            "exactly one passenger group."
                        )
                    },
                    status=(
                        status
                        .HTTP_409_CONFLICT
                    ),
                )


            ride_request = (
                groups[0].ride_request
            )


            pickup_completed = (
                ride.status
                == Ride.Status.IN_PROGRESS
            )


            if pickup_completed:

                next_target = (
                    ride_request
                    .destination_node
                )

                next_target_type = (
                    "DROPOFF"
                )

                current_leg_path = (
                    shortest_path_ids(
                        vehicle.current_node,
                        ride_request
                        .destination_node,
                    )
                )

                full_remaining_path = (
                    current_leg_path
                )

            else:

                next_target = (
                    ride_request
                    .pickup_node
                )

                next_target_type = (
                    "PICKUP"
                )

                to_pickup = (
                    shortest_path_ids(
                        vehicle.current_node,
                        ride_request
                        .pickup_node,
                    )
                )

                pickup_to_destination = (
                    shortest_path_ids(
                        ride_request
                        .pickup_node,

                        ride_request
                        .destination_node,
                    )
                )

                current_leg_path = (
                    to_pickup
                )

                full_remaining_path = (
                    merge_paths(
                        to_pickup,
                        pickup_to_destination,
                    )
                )


            ordered_stops = [
                {
                    "sequence_number": 1,

                    "stop_type": (
                        "PICKUP"
                    ),

                    "status": (
                        "COMPLETED"
                        if pickup_completed
                        else "PENDING"
                    ),

                    "is_next": (
                        not pickup_completed
                    ),

                    "node": (
                        serialize_node(
                            ride_request
                            .pickup_node
                        )
                    ),

                    "ride_request_id": (
                        ride_request.id
                    ),

                    "passenger_username": (
                        ride_request
                        .passenger
                        .user
                        .username
                    ),

                    "passenger_count": (
                        ride_request
                        .passenger_count
                    ),

                    "estimated_arrival_minutes": (
                        None
                    ),
                },

                {
                    "sequence_number": 2,

                    "stop_type": (
                        "DROPOFF"
                    ),

                    "status": (
                        "PENDING"
                    ),

                    "is_next": (
                        pickup_completed
                    ),

                    "node": (
                        serialize_node(
                            ride_request
                            .destination_node
                        )
                    ),

                    "ride_request_id": (
                        ride_request.id
                    ),

                    "passenger_username": (
                        ride_request
                        .passenger
                        .user
                        .username
                    ),

                    "passenger_count": (
                        ride_request
                        .passenger_count
                    ),

                    "estimated_arrival_minutes": (
                        None
                    ),
                },
            ]


            return Response(
                {
                    "vehicle": (
                        vehicle_payload
                    ),

                    "active_ride": {
                        "ride_id": ride.id,

                        "ride_type": (
                            ride.ride_type
                        ),

                        "ride_status": (
                            ride.status
                        ),

                        "route_revision": (
                            None
                        ),

                        "passenger_groups": (
                            group_payload
                        ),

                        "ordered_stops": (
                            ordered_stops
                        ),

                        "next_target": {
                            "type": (
                                next_target_type
                            ),

                            "node": (
                                serialize_node(
                                    next_target
                                )
                            ),
                        },

                        "current_leg_path_node_ids": (
                            current_leg_path
                        ),

                        "full_remaining_path_node_ids": (
                            full_remaining_path
                        ),
                    },
                },
                status=(
                    status.HTTP_200_OK
                ),
            )


        # =================================================
        # 6. SHARED Ride
        # =================================================

        if (
            ride.ride_type
            == RideRequest.RideType.SHARED
        ):

            route = (
                Route.objects
                .filter(
                    ride=ride,
                    status=Route.Status.ACTIVE,
                )
                .first()
            )


            if route is None:

                return Response(
                    {
                        "detail": (
                            "Active shared route was not found."
                        )
                    },
                    status=(
                        status
                        .HTTP_409_CONFLICT
                    ),
                )


            stops = list(

                RouteStop.objects
                .filter(
                    route=route
                )
                .select_related(
                    "node",
                    "ride_passenger",
                    "ride_passenger__ride_request",
                    "ride_passenger__ride_request__passenger__user",
                )
                .order_by(
                    "sequence_number",
                    "id",
                )
            )


            pending_stops = [
                stop
                for stop
                in stops

                if (
                    stop.status
                    == RouteStop.Status.PENDING
                )
            ]


            next_stop = (
                pending_stops[0]
                if pending_stops
                else None
            )


            # ---------------------------------------------
            # Current leg: Taxi -> next pending stop
            # ---------------------------------------------

            current_leg_path = []

            if next_stop is not None:

                current_leg_path = (
                    shortest_path_ids(
                        vehicle.current_node,
                        next_stop.node,
                    )
                )


            # ---------------------------------------------
            # Full remaining route:
            #
            # current taxi node
            # -> pending stop 1
            # -> pending stop 2
            # -> ...
            # ---------------------------------------------

            full_remaining_path = []

            cursor = (
                vehicle.current_node
            )


            for stop in pending_stops:

                segment = (
                    shortest_path_ids(
                        cursor,
                        stop.node,
                    )
                )

                full_remaining_path = (
                    merge_paths(
                        full_remaining_path,
                        segment,
                    )
                )

                cursor = (
                    stop.node
                )


            ordered_stops = []


            for stop in stops:

                request = (
                    stop
                    .ride_passenger
                    .ride_request
                )


                ordered_stops.append(
                    {
                        "id": stop.id,

                        "sequence_number": (
                            stop.sequence_number
                        ),

                        "stop_type": (
                            stop.stop_type
                        ),

                        "status": (
                            stop.status
                        ),

                        "is_next": (
                            next_stop is not None
                            and
                            stop.id == next_stop.id
                        ),

                        "node": (
                            serialize_node(
                                stop.node
                            )
                        ),

                        "ride_request_id": (
                            request.id
                        ),

                        "passenger_username": (
                            request
                            .passenger
                            .user
                            .username
                        ),

                        "passenger_count": (
                            request
                            .passenger_count
                        ),

                        "estimated_arrival_minutes": (
                            stop
                            .estimated_arrival_minutes
                        ),
                    }
                )


            next_target = None

            if next_stop is not None:

                next_target = {
                    "type": (
                        next_stop.stop_type
                    ),

                    "node": (
                        serialize_node(
                            next_stop.node
                        )
                    ),
                }


            return Response(
                {
                    "vehicle": (
                        vehicle_payload
                    ),

                    "active_ride": {
                        "ride_id": ride.id,

                        "ride_type": (
                            ride.ride_type
                        ),

                        "ride_status": (
                            ride.status
                        ),

                        "route_id": (
                            route.id
                        ),

                        "route_revision": (
                            route.revision
                        ),

                        "route_total_time_minutes": (
                            route
                            .total_estimated_time_minutes
                        ),

                        "route_total_distance_km": (
                            route
                            .total_estimated_distance_km
                        ),

                        "passenger_groups": (
                            group_payload
                        ),

                        "ordered_stops": (
                            ordered_stops
                        ),

                        "next_target": (
                            next_target
                        ),

                        "current_leg_path_node_ids": (
                            current_leg_path
                        ),

                        "full_remaining_path_node_ids": (
                            full_remaining_path
                        ),
                    },
                },
                status=(
                    status.HTTP_200_OK
                ),
            )


        # =================================================
        # 7. Unsupported Type
        # =================================================

        return Response(
            {
                "detail": (
                    "Unsupported active ride type."
                )
            },
            status=(
                status.HTTP_409_CONFLICT
            ),
        )
