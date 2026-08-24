from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import PassengerProfile
from accounts.permissions import IsPassenger
from rides.models import Ride, RideRequest
from road_network.services import (
    RoadNetworkError,
    RoadNetworkService,
)
from shared_ride.models import Route, RouteStop


def get_passenger_profile(user):
    return (
        PassengerProfile.objects
        .filter(user=user)
        .first()
    )


def serialize_node(node):
    if node is None:
        return None

    return {
        "id": node.id,
        "name": node.name,
        "x": node.x,
        "y": node.y,
    }


def append_segment(full_path, segment):
    for node in segment:
        if (
            not full_path
            or full_path[-1] != node.id
        ):
            full_path.append(node.id)


def build_private_remaining_path(
    ride,
    ride_request,
):
    vehicle = ride.vehicle

    if vehicle.current_node_id is None:
        return [], None

    if ride.status in [
        Ride.Status.ASSIGNED,
        Ride.Status.ACCEPTED,
    ]:
        targets = [
            ride_request.pickup_node,
            ride_request.destination_node,
        ]
        target_type = "PICKUP"

    elif (
        ride.status
        == Ride.Status.IN_PROGRESS
    ):
        targets = [
            ride_request.destination_node
        ]
        target_type = "DROPOFF"

    else:
        return [], None

    current = vehicle.current_node
    full_path = []

    for target in targets:
        try:
            segment = (
                RoadNetworkService
                .shortest_path(
                    current,
                    target,
                )
            )
        except RoadNetworkError:
            break

        append_segment(
            full_path,
            segment,
        )
        current = target

    return (
        full_path,
        target_type,
    )


def get_shared_passenger_phase(
    ride,
    ride_request,
):
    membership = (
        ride.passenger_groups
        .filter(
            ride_request=ride_request
        )
        .order_by("-id")
        .first()
    )

    if membership is None:
        return "UNKNOWN"

    pickup_stop = (
        RouteStop.objects
        .filter(
            ride_passenger=membership,
            stop_type=RouteStop.StopType.PICKUP,
        )
        .order_by("-id")
        .first()
    )

    dropoff_stop = (
        RouteStop.objects
        .filter(
            ride_passenger=membership,
            stop_type=RouteStop.StopType.DROPOFF,
        )
        .order_by("-id")
        .first()
    )

    if (
        dropoff_stop
        and dropoff_stop.status
        == RouteStop.Status.COMPLETED
    ):
        return "COMPLETED"

    if (
        pickup_stop
        and pickup_stop.status
        == RouteStop.Status.COMPLETED
    ):
        return "ONBOARD"

    if (
        pickup_stop
        and pickup_stop.status
        == RouteStop.Status.PENDING
    ):
        return "WAITING_PICKUP"

    return "UNKNOWN"


def build_shared_remaining_path(ride):
    vehicle = ride.vehicle

    if vehicle.current_node_id is None:
        return [], None, None

    route = (
        Route.objects
        .filter(
            ride=ride,
            status=Route.Status.ACTIVE,
        )
        .first()
    )

    if route is None:
        return [], None, None

    pending_stops = list(
        RouteStop.objects
        .filter(
            route=route,
            status=RouteStop.Status.PENDING,
        )
        .select_related("node")
        .order_by(
            "sequence_number",
            "id",
        )
    )

    if not pending_stops:
        return [], route.revision, None

    full_path = []
    current = vehicle.current_node

    for stop in pending_stops:
        try:
            segment = (
                RoadNetworkService
                .shortest_path(
                    current,
                    stop.node,
                )
            )
        except RoadNetworkError:
            break

        append_segment(
            full_path,
            segment,
        )
        current = stop.node

    return (
        full_path,
        route.revision,
        "NEXT_ROUTE_STOP",
    )


class PassengerRideTrackingAPIView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsPassenger,
    ]

    def get(
        self,
        request,
        request_id,
    ):
        passenger = (
            get_passenger_profile(
                request.user
            )
        )

        if passenger is None:
            return Response(
                {
                    "detail": (
                        "Passenger profile "
                        "was not found."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        ride_request = get_object_or_404(
            RideRequest.objects
            .select_related(
                "pickup_node",
                "destination_node",
            ),
            pk=request_id,
            passenger=passenger,
        )

        # A request can have historical RidePassenger links
        # after rejection/recovery. Highest Ride id is the
        # latest assignment.
        ride = (
            Ride.objects
            .filter(
                passenger_groups__ride_request=(
                    ride_request
                )
            )
            .select_related(
                "vehicle",
                "vehicle__current_node",
            )
            .order_by("-id")
            .first()
        )

        if ride is None:
            return Response(
                {
                    "ride_request_id":
                        ride_request.id,

                    "request_status":
                        ride_request.status,

                    "tracking_available":
                        False,

                    "detail": (
                        "No operational ride "
                        "has been assigned yet."
                    ),
                },
                status=status.HTTP_200_OK,
            )

        if (
            ride.ride_type
            == RideRequest.RideType.PRIVATE
        ):
            (
                remaining_path,
                target_type,
            ) = build_private_remaining_path(
                ride,
                ride_request,
            )

            route_revision = None

            if (
                ride.status
                == Ride.Status.IN_PROGRESS
            ):
                passenger_phase = "ONBOARD"

            elif ride.status in [
                Ride.Status.ASSIGNED,
                Ride.Status.ACCEPTED,
            ]:
                passenger_phase = (
                    "WAITING_PICKUP"
                )

            elif (
                ride.status
                == Ride.Status.COMPLETED
            ):
                passenger_phase = "COMPLETED"

            else:
                passenger_phase = "INACTIVE"

        else:
            (
                remaining_path,
                route_revision,
                target_type,
            ) = build_shared_remaining_path(
                ride
            )

            passenger_phase = (
                get_shared_passenger_phase(
                    ride,
                    ride_request,
                )
            )

        tracking_available = (
            ride.status
            in [
                Ride.Status.ASSIGNED,
                Ride.Status.ACCEPTED,
                Ride.Status.IN_PROGRESS,
            ]
        )

        return Response(
            {
                "ride_request_id":
                    ride_request.id,

                "ride_type":
                    ride.ride_type,

                "request_status":
                    ride_request.status,

                "tracking_available":
                    tracking_available,

                "ride": {
                    "id": ride.id,
                    "status": ride.status,
                },

                "vehicle": {
                    "id": ride.vehicle_id,
                    "current_node":
                        serialize_node(
                            ride.vehicle.current_node
                        ),
                },

                "pickup_node":
                    serialize_node(
                        ride_request.pickup_node
                    ),

                "destination_node":
                    serialize_node(
                        ride_request.destination_node
                    ),

                "passenger_phase":
                    passenger_phase,

                "target_type":
                    target_type,

                "remaining_path_node_ids":
                    remaining_path,

                "route_revision":
                    route_revision,

                "server_time":
                    timezone.now(),
            },
            status=status.HTTP_200_OK,
        )
