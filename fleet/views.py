from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsDriver

from .models import Vehicle
from .serializers import VehicleSerializer


class MyVehicleView(APIView):
    # فقط Driver اجازه دارد
    permission_classes = [IsDriver]

    def get(self, request):
        # Driver مربوط به User فعلی
        driver_profile = request.user.driver_profile

        try:
            # Vehicle متعلق به همین Driver
            vehicle = driver_profile.vehicle

        except Vehicle.DoesNotExist:
            return Response(
                {
                    "detail": "No vehicle registered."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # نمایش Vehicle
        return Response(
            VehicleSerializer(vehicle).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        # Driver فعلی
        driver_profile = request.user.driver_profile

        # هر Driver فعلاً فقط یک Vehicle
        if hasattr(driver_profile, "vehicle"):
            return Response(
                {
                    "detail": "This driver already has a vehicle."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validation داده‌های ورودی
        serializer = VehicleSerializer(
            data=request.data
        )

        if serializer.is_valid():
            # Driver را Backend تعیین می‌کند
            vehicle = serializer.save(
                driver=driver_profile
            )

            return Response(
                VehicleSerializer(vehicle).data,
                status=status.HTTP_201_CREATED,
            )

        # Validation error
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


class VehicleAvailabilityView(APIView):
    # فقط Driver
    permission_classes = [IsDriver]

    def patch(self, request):
        driver_profile = request.user.driver_profile

        try:
            vehicle = driver_profile.vehicle

        except Vehicle.DoesNotExist:
            return Response(
                {
                    "detail": "No vehicle registered."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # فیلد الزامی است
        if "is_available" not in request.data:
            return Response(
                {
                    "detail": "is_available is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        value = request.data["is_available"]

        # فقط Boolean قبول می‌کنیم
        if not isinstance(value, bool):
            return Response(
                {
                    "detail": "is_available must be a boolean."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update وضعیت ماشین
        vehicle.is_available = value

        vehicle.save(
            update_fields=[
                "is_available",
                "updated_at",
            ]
        )

        return Response(
            VehicleSerializer(vehicle).data,
            status=status.HTTP_200_OK,
        )