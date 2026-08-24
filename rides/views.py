from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsPassenger

from .models import RideRequest
from .serializers import RideRequestSerializer

from .services import (
    RideLifecycleError,
    cancel_ride_request,
)
class RideRequestListCreateView(APIView):
    # فقط Passenger اجازه دسترسی دارد
    permission_classes = [IsPassenger]

    def get(self, request):
        # فقط درخواست‌های Passenger فعلی
        ride_requests = RideRequest.objects.filter(
            passenger=request.user.passenger_profile
        ).order_by("-created_at")

        serializer = RideRequestSerializer(
            ride_requests,
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        # بررسی داده‌های Request جدید
        serializer = RideRequestSerializer(
            data=request.data
        )

        if serializer.is_valid():
            # Passenger از User لاگین‌شده گرفته می‌شود
            ride_request = serializer.save(
                passenger=request.user.passenger_profile
            )

            return Response(
                RideRequestSerializer(ride_request).data,
                status=status.HTTP_201_CREATED,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


class RideRequestDetailView(APIView):
    # فقط Passenger
    permission_classes = [IsPassenger]

    def get(self, request, request_id):
        # Passenger فقط Request خودش را می‌بیند
        ride_request = get_object_or_404(
            RideRequest,
            id=request_id,
            passenger=request.user.passenger_profile,
        )

        return Response(
            RideRequestSerializer(ride_request).data,
            status=status.HTTP_200_OK,
        )


class RideRequestCancelView(APIView):
    # فقط Passenger
    permission_classes = [IsPassenger]

    def post(self, request, request_id):
        # فقط Request متعلق به Passenger
        ride_request = get_object_or_404(
            RideRequest,
            id=request_id,
            passenger=request.user.passenger_profile,
        )

        try:
            # Cancellation از Service عبور می‌کند
            ride_request = cancel_ride_request(
                ride_request,
                request.user.passenger_profile,
            )

        except RideLifecycleError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            RideRequestSerializer(ride_request).data,
            status=status.HTTP_200_OK,
        )