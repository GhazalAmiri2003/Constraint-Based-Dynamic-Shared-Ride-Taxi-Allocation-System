from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import (
    IsAuthenticated,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import (
    PassengerProfile,
)
from accounts.permissions import (
    IsDriver,
    IsPassenger,
)
from assignment.models import TaxiHold
from assignment.shared_confirmation_services import (
    SharedConfirmationError,
    SharedTaxiConfirmationService,
)
from assignment.shared_services import (
    SharedTaxiOptionError,
    SharedTaxiOptionService,
)
from fleet.models import Vehicle
from rides.models import (
    Ride,
    RideRequest,
)
from shared_ride.models import (
    Route,
    RouteStop,
)
from shared_ride.movement_services import (
    SharedMovementError,
    SharedRouteMovementService,
)


# =========================================================
# Helpers
# =========================================================

def get_passenger_profile(user):
    """
    عمداً از user.passenger_profile استفاده نمی‌کنیم.

    پروژه قبلاً هم بر اساس query مستقیم
    PassengerProfile کار می‌کند.
    """

    return (
        PassengerProfile.objects
        .filter(
            user=user
        )
        .first()
    )


def serialize_proposed_route(
    proposed_route,
):
    return [
        {
            "sequence_number": (
                stop.sequence_number
            ),

            "group_key": (
                stop.group_key
            ),

            "passenger_count": (
                stop.passenger_count
            ),

            "node_id": (
                stop.node_id
            ),

            "node_name": (
                stop.node_name
            ),

            "stop_type": (
                stop.stop_type
            ),

            "estimated_arrival_minutes": (
                stop
                .estimated_arrival_minutes
            ),
        }

        for stop
        in proposed_route
    ]


def serialize_shared_option(
    option,
):
    return {
        "rank": option.rank,

        "vehicle_id": (
            option.vehicle_id
        ),

        "driver_username": (
            option.driver_username
        ),

        "vehicle_mode": (
            option.vehicle_mode
        ),

        "current_node": {
            "id": (
                option.current_node_id
            ),

            "name": (
                option.current_node_name
            ),
        },

        "capacity": (
            option.capacity
        ),

        "pickup_eta_minutes": (
            option.pickup_eta_minutes
        ),

        "estimated_destination_arrival_minutes": (
            option
            .estimated_destination_arrival_minutes
        ),

        "estimated_trip_duration_minutes": (
            option
            .estimated_trip_duration_minutes
        ),

        "expected_shared_delay_minutes": (
            option
            .expected_shared_delay_minutes
        ),

        "total_passenger_delay_minutes": (
            option
            .total_passenger_delay_minutes
        ),

        "available_seats_at_pickup": (
            option
            .available_seats_at_pickup
        ),

        "additional_route_time_minutes": (
            option
            .additional_route_time_minutes
        ),

        "route_extension_km": (
            option.route_extension_km
        ),

        "route_total_time_minutes": (
            option
            .route_total_time_minutes
        ),

        "route_total_distance_km": (
            option
            .route_total_distance_km
        ),

        "estimated_price": (
            option.estimated_price
        ),

        "source_route_id": (
            option.source_route_id
        ),

        "source_route_revision": (
            option
            .source_route_revision
        ),

        "proposed_route": (
            serialize_proposed_route(
                option.proposed_route
            )
        ),
    }


# =========================================================
# Passenger: Shared Taxi Options
# =========================================================

class SharedTaxiOptionsAPIView(
    APIView
):

    permission_classes = [
        IsAuthenticated,
        IsPassenger,
    ]


    def get(
        self,
        request,
        ride_request_id,
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
                status=(
                    status
                    .HTTP_403_FORBIDDEN
                ),
            )


        ride_request = (
            get_object_or_404(
                RideRequest,

                pk=ride_request_id,

                passenger=passenger,
            )
        )


        try:

            options = (
                SharedTaxiOptionService
                .generate_shared_taxi_options(
                    ride_request
                )
            )

        except SharedTaxiOptionError as error:

            return Response(
                {
                    "detail": str(error)
                },
                status=(
                    status
                    .HTTP_400_BAD_REQUEST
                ),
            )


        return Response(
            {
                "ride_request_id": (
                    ride_request.id
                ),

                "count": len(
                    options
                ),

                "options": [
                    serialize_shared_option(
                        option
                    )

                    for option
                    in options
                ],
            }
        )


# =========================================================
# Passenger: Create Shared Hold
# =========================================================

class SharedTaxiHoldAPIView(
    APIView
):

    permission_classes = [
        IsAuthenticated,
        IsPassenger,
    ]


    def post(
        self,
        request,
        ride_request_id,
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
                status=(
                    status
                    .HTTP_403_FORBIDDEN
                ),
            )


        ride_request = (
            get_object_or_404(
                RideRequest,

                pk=ride_request_id,

                passenger=passenger,
            )
        )


        vehicle_id = (
            request.data.get(
                "vehicle_id"
            )
        )


        if vehicle_id is None:

            return Response(
                {
                    "detail": (
                        "vehicle_id is required."
                    )
                },
                status=(
                    status
                    .HTTP_400_BAD_REQUEST
                ),
            )


        try:

            hold = (
                SharedTaxiConfirmationService
                .create_shared_taxi_hold(
                    ride_request=(
                        ride_request
                    ),

                    vehicle_id=(
                        vehicle_id
                    ),
                )
            )

        except SharedConfirmationError as error:

            return Response(
                {
                    "detail": str(error)
                },
                status=(
                    status
                    .HTTP_409_CONFLICT
                ),
            )


        return Response(
            {
                "hold_id": hold.id,

                "ride_request_id": (
                    hold.ride_request_id
                ),

                "vehicle_id": (
                    hold.vehicle_id
                ),

                "status": (
                    hold.status
                ),

                "expires_at": (
                    hold.expires_at
                ),
            },
            status=(
                status.HTTP_201_CREATED
            ),
        )


# =========================================================
# Passenger: Confirm Shared Hold
# =========================================================

class SharedTaxiConfirmAPIView(
    APIView
):

    permission_classes = [
        IsAuthenticated,
        IsPassenger,
    ]


    def post(
        self,
        request,
        hold_id,
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
                status=(
                    status
                    .HTTP_403_FORBIDDEN
                ),
            )


        hold = (
            get_object_or_404(
                TaxiHold.objects
                .select_related(
                    "ride_request"
                ),

                pk=hold_id,

                ride_request__passenger=(
                    passenger
                ),
            )
        )


        try:

            result = (
                SharedTaxiConfirmationService
                .confirm_shared_taxi_hold(
                    hold
                )
            )

        except SharedConfirmationError as error:

            return Response(
                {
                    "detail": str(error)
                },
                status=(
                    status
                    .HTTP_409_CONFLICT
                ),
            )


        return Response(
            {
                "hold_id": (
                    result.hold.id
                ),

                "hold_status": (
                    result.hold.status
                ),

                "ride_id": (
                    result.ride.id
                ),

                "ride_passenger_id": (
                    result
                    .ride_passenger
                    .id
                ),

                "route_id": (
                    result.route.id
                ),

                "route_revision": (
                    result.route.revision
                ),
            }
        )


# =========================================================
# Passenger: Release Shared Hold
# =========================================================

class SharedTaxiReleaseAPIView(
    APIView
):

    permission_classes = [
        IsAuthenticated,
        IsPassenger,
    ]


    def post(
        self,
        request,
        hold_id,
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
                status=(
                    status
                    .HTTP_403_FORBIDDEN
                ),
            )


        hold = (
            get_object_or_404(
                TaxiHold.objects
                .select_related(
                    "ride_request"
                ),

                pk=hold_id,

                ride_request__passenger=(
                    passenger
                ),
            )
        )


        try:

            released_hold = (
                SharedTaxiConfirmationService
                .release_shared_taxi_hold(
                    hold
                )
            )

        except SharedConfirmationError as error:

            return Response(
                {
                    "detail": str(error)
                },
                status=(
                    status
                    .HTTP_409_CONFLICT
                ),
            )


        return Response(
            {
                "hold_id": (
                    released_hold.id
                ),

                "status": (
                    released_hold.status
                ),
            }
        )


# =========================================================
# Driver: Active Shared Ride
# =========================================================

class DriverActiveSharedRideAPIView(
    APIView
):

    permission_classes = [
        IsAuthenticated,
        IsDriver,
    ]


    def get(
        self,
        request,
    ):
        vehicle = (
            Vehicle.objects
            .filter(
                driver__user=(
                    request.user
                )
            )
            .first()
        )


        if vehicle is None:

            return Response(
                {
                    "detail": (
                        "Driver has no vehicle."
                    )
                },
                status=(
                    status
                    .HTTP_404_NOT_FOUND
                ),
            )


        ride = (
            Ride.objects
            .filter(
                vehicle=vehicle,

                ride_type=(
                    RideRequest
                    .RideType
                    .SHARED
                ),

                status__in=[
                    Ride.Status.ASSIGNED,
                    Ride.Status.ACCEPTED,
                    Ride.Status.IN_PROGRESS,
                ],
            )
            .order_by("-id")
            .first()
        )


        if ride is None:

            return Response(
                {
                    "active_shared_ride": None
                }
            )


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
                        "Active shared route "
                        "was not found."
                    )
                },
                status=(
                    status
                    .HTTP_409_CONFLICT
                ),
            )


        stops = (
            RouteStop.objects
            .filter(
                route=route
            )
            .select_related(
                "node",
                "ride_passenger",
                "ride_passenger__ride_request",
            )
            .order_by(
                "sequence_number"
            )
        )


        return Response(
            {
                "active_shared_ride": {
                    "ride_id": ride.id,

                    "ride_status": (
                        ride.status
                    ),

                    "vehicle_id": (
                        vehicle.id
                    ),

                    "current_node": (
                        {
                            "id": (
                                vehicle
                                .current_node_id
                            ),

                            "name": (
                                vehicle
                                .current_node
                                .name
                            ),
                        }

                        if (
                            vehicle
                            .current_node_id
                        )

                        else None
                    ),

                    "route": {
                        "id": route.id,

                        "revision": (
                            route.revision
                        ),

                        "status": (
                            route.status
                        ),

                        "total_estimated_time_minutes": (
                            route
                            .total_estimated_time_minutes
                        ),

                        "total_estimated_distance_km": (
                            route
                            .total_estimated_distance_km
                        ),
                    },

                    "stops": [
                        {
                            "id": stop.id,

                            "sequence_number": (
                                stop
                                .sequence_number
                            ),

                            "stop_type": (
                                stop.stop_type
                            ),

                            "status": (
                                stop.status
                            ),

                            "node": {
                                "id": (
                                    stop.node_id
                                ),

                                "name": (
                                    stop.node.name
                                ),
                            },

                            "passenger_count": (
                                stop
                                .ride_passenger
                                .ride_request
                                .passenger_count
                            ),

                            "ride_request_id": (
                                stop
                                .ride_passenger
                                .ride_request_id
                            ),

                            "estimated_arrival_minutes": (
                                stop
                                .estimated_arrival_minutes
                            ),

                            "actual_arrival_time": (
                                stop
                                .actual_arrival_time
                            ),
                        }

                        for stop
                        in stops
                    ],
                }
            }
        )


# =========================================================
# Driver: Move Shared Taxi One Step
# =========================================================

class DriverSharedMoveNextAPIView(
    APIView
):

    permission_classes = [
        IsAuthenticated,
        IsDriver,
    ]


    def post(
        self,
        request,
    ):
        vehicle = (
            Vehicle.objects
            .filter(
                driver__user=(
                    request.user
                )
            )
            .first()
        )


        if vehicle is None:

            return Response(
                {
                    "detail": (
                        "Driver has no vehicle."
                    )
                },
                status=(
                    status
                    .HTTP_404_NOT_FOUND
                ),
            )


        try:

            result = (
                SharedRouteMovementService
                .advance_shared_ride(
                    vehicle.id
                )
            )

        except SharedMovementError as error:

            return Response(
                {
                    "detail": str(error)
                },
                status=(
                    status
                    .HTTP_409_CONFLICT
                ),
            )


        return Response(
            {
                "action": (
                    result.action
                ),

                "vehicle_id": (
                    result.vehicle_id
                ),

                "ride_id": (
                    result.ride_id
                ),

                "route_id": (
                    result.route_id
                ),

                "current_node_id": (
                    result.current_node_id
                ),

                "completed_stop_id": (
                    result.completed_stop_id
                ),

                "next_stop_id": (
                    result.next_stop_id
                ),
            }
        )