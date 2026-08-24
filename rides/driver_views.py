from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsDriver

from .models import Ride
from .serializers import RideSerializer
from .services import (
    RideLifecycleError,
    accept_ride,
    complete_ride,
    reject_ride,
    start_ride,
)


def get_driver_ride(request, ride_id):
    # Driver فقط Ride مربوط به Vehicle خودش را می‌گیرد
    return get_object_or_404(
        Ride,
        id=ride_id,
        vehicle__driver=request.user.driver_profile,
    )


class DriverRideListView(APIView):
    # فقط Driver
    permission_classes = [IsDriver]

    def get(self, request):
        # فقط Rideهای Taxi همین Driver
        rides = (
            Ride.objects
            .filter(
                vehicle__driver=request.user.driver_profile
            )
            .select_related(
                "vehicle__driver__user"
            )
            .prefetch_related(
                "passenger_groups__ride_request__passenger__user",
                "passenger_groups__ride_request__pickup_node",
                "passenger_groups__ride_request__destination_node",
            )
            .order_by("-assigned_at")
        )

        return Response(
            RideSerializer(
                rides,
                many=True,
            ).data,
            status=status.HTTP_200_OK,
        )


class DriverRideDetailView(APIView):
    # فقط Driver
    permission_classes = [IsDriver]

    def get(self, request, ride_id):
        ride = get_driver_ride(
            request,
            ride_id,
        )

        return Response(
            RideSerializer(ride).data,
            status=status.HTTP_200_OK,
        )


class DriverRideAcceptView(APIView):
    permission_classes = [IsDriver]

    def post(self, request, ride_id):
        ride = get_driver_ride(
            request,
            ride_id,
        )

        try:
            ride = accept_ride(
                ride,
                request.user.driver_profile,
            )

        except RideLifecycleError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            RideSerializer(ride).data,
            status=status.HTTP_200_OK,
        )


class DriverRideRejectView(APIView):
    permission_classes = [IsDriver]

    def post(self, request, ride_id):
        ride = get_driver_ride(
            request,
            ride_id,
        )

        try:
            ride = reject_ride(
                ride,
                request.user.driver_profile,
            )

        except RideLifecycleError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            RideSerializer(ride).data,
            status=status.HTTP_200_OK,
        )


class DriverRideStartView(APIView):
    permission_classes = [IsDriver]

    def post(self, request, ride_id):
        ride = get_driver_ride(
            request,
            ride_id,
        )

        try:
            ride = start_ride(
                ride,
                request.user.driver_profile,
            )

        except RideLifecycleError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            RideSerializer(ride).data,
            status=status.HTTP_200_OK,
        )


class DriverRideCompleteView(APIView):
    permission_classes = [IsDriver]

    def post(self, request, ride_id):
        ride = get_driver_ride(
            request,
            ride_id,
        )

        try:
            ride = complete_ride(
                ride,
                request.user.driver_profile,
            )

        except RideLifecycleError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            RideSerializer(ride).data,
            status=status.HTTP_200_OK,
        )