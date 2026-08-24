from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsDriver
from .serializers import DriverAvailabilitySerializer
from .services import (
    DriverAvailabilityError,
    set_driver_availability,
)


class DriverAvailabilityView(APIView):
    # فقط Driver
    permission_classes = [IsDriver]

    def get(self, request):
        # وضعیت فعلی Driver
        return Response(
            {
                "availability_status":
                    request.user.driver_profile.availability_status
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        # Validate ONLINE/OFFLINE
        serializer = DriverAvailabilitySerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        try:
            driver_profile = set_driver_availability(
                request.user.driver_profile,
                serializer.validated_data[
                    "availability_status"
                ],
            )

        except DriverAvailabilityError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "availability_status":
                    driver_profile.availability_status
            },
            status=status.HTTP_200_OK,
        )