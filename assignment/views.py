from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsPassenger
from rides.models import RideRequest

from .models import TaxiHold
from .serializers import (
    TaxiOptionSerializer,
    TaxiSelectionSerializer,
)
from .services import (
    AssignmentError,
    AssignmentService,
)



from .hold_services import (
    TaxiHoldError,
    TaxiHoldService,
)


# =========================================================
# Ranked Taxi Options
# =========================================================

class PrivateTaxiOptionsView(APIView):
    permission_classes = [
        IsPassenger
    ]

    def get(
        self,
        request,
        ride_request_id,
    ):
        # Passenger فقط Request خودش
        ride_request = get_object_or_404(
            RideRequest,
            pk=ride_request_id,
            passenger=(
                request.user.passenger_profile
            ),
        )


        try:
            options = (
                AssignmentService
                .generate_private_taxi_options(
                    ride_request
                )
            )

        except AssignmentError as error:
            return Response(
                {
                    "detail": str(error)
                },
                status=(
                    status.HTTP_400_BAD_REQUEST
                ),
            )


        # تمام Ranked Options
        serializer = TaxiOptionSerializer(
            options,
            many=True,
        )


        return Response(
            {
                "ride_request_id":
                    ride_request.id,

                "option_count":
                    len(options),

                "options":
                    serializer.data,
            },
            status=status.HTTP_200_OK,
        )


# =========================================================
# Legacy Direct Selection
# =========================================================

# =========================================================
# Create Temporary Hold
# =========================================================

class HoldPrivateTaxiView(APIView):
    permission_classes = [
        IsPassenger
    ]

    def post(
        self,
        request,
        ride_request_id,
    ):
        # Passenger فقط Request خودش
        ride_request = get_object_or_404(
            RideRequest,
            pk=ride_request_id,
            passenger=(
                request.user.passenger_profile
            ),
        )


        serializer = TaxiSelectionSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )


        vehicle_id = (
            serializer.validated_data[
                "vehicle_id"
            ]
        )


        try:
            hold = (
                AssignmentService
                .create_private_taxi_hold(
                    ride_request,
                    vehicle_id,
                )
            )

        except AssignmentError as error:
            return Response(
                {
                    "detail": str(error)
                },
                status=(
                    status.HTTP_400_BAD_REQUEST
                ),
            )


        return Response(
            {
                "hold_id":
                    hold.id,

                "ride_request_id":
                    hold.ride_request_id,

                "vehicle_id":
                    hold.vehicle_id,

                "status":
                    hold.status,

                "expires_at":
                    hold.expires_at,
            },
            status=status.HTTP_201_CREATED,
        )


# =========================================================
# Confirm Temporary Hold
# =========================================================

class ConfirmPrivateTaxiHoldView(APIView):
    permission_classes = [
        IsPassenger
    ]

    def post(
        self,
        request,
        hold_id,
    ):
        # Passenger فقط Hold متعلق به خودش
        hold = get_object_or_404(
            TaxiHold.objects.select_related(
                "ride_request",
                "vehicle",
            ),
            pk=hold_id,
            ride_request__passenger=(
                request.user.passenger_profile
            ),
        )


        try:
            ride, confirmed_hold = (
                AssignmentService
                .confirm_private_taxi_hold(
                    hold
                )
            )

        except AssignmentError as error:
            return Response(
                {
                    "detail": str(error)
                },
                status=(
                    status.HTTP_400_BAD_REQUEST
                ),
            )


        return Response(
            {
                "hold_id":
                    confirmed_hold.id,

                "hold_status":
                    confirmed_hold.status,

                "ride_id":
                    ride.id,

                "ride_status":
                    ride.status,

                "ride_request_id":
                    confirmed_hold.ride_request_id,

                "vehicle_id":
                    ride.vehicle_id,
            },
            status=status.HTTP_200_OK,
        )


# =========================================================
# Release Temporary Hold
# =========================================================

class ReleasePrivateTaxiHoldView(APIView):
    permission_classes = [
        IsPassenger
    ]

    def post(
        self,
        request,
        hold_id,
    ):
        # Passenger فقط Hold متعلق به خودش را آزاد می‌کند
        hold = get_object_or_404(
            TaxiHold.objects.select_related(
                "ride_request",
                "vehicle",
            ),
            pk=hold_id,
            ride_request__passenger=(
                request.user.passenger_profile
            ),
        )

        try:
            released_hold = (
                TaxiHoldService.release_hold(
                    hold
                )
            )

        except TaxiHoldError as error:
            return Response(
                {
                    "detail": str(error)
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "hold_id":
                    released_hold.id,

                "ride_request_id":
                    released_hold.ride_request_id,

                "vehicle_id":
                    released_hold.vehicle_id,

                "status":
                    released_hold.status,
            },
            status=status.HTTP_200_OK,
        )