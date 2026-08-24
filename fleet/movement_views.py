from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsDriver
from road_network.serializers import RoadNodeSerializer

from .models import Vehicle
from .services import (
    VehicleMovementError,
    VehicleMovementService,
)


class DriverMoveNextView(APIView):
    # فقط Driver
    permission_classes = [IsDriver]

    def post(self, request):
        try:
            vehicle = Vehicle.objects.get(
                driver=request.user.driver_profile
            )

        except Vehicle.DoesNotExist:
            return Response(
                {"detail": "Driver has no vehicle."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            result = (
                VehicleMovementService
                .move_next_for_active_ride(vehicle)
            )

        except VehicleMovementError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        moved_vehicle = result["vehicle"]

        return Response(
            {
                "ride_id": result["ride"].id,
                "ride_status": result["ride"].status,
                "target_type": result["target_type"],

                "target_node": RoadNodeSerializer(
                    result["target_node"]
                ).data,

                "previous_node": (
                    RoadNodeSerializer(
                        result["previous_node"]
                    ).data
                    if result["previous_node"]
                    else None
                ),

                "current_node": RoadNodeSerializer(
                    moved_vehicle.current_node
                ).data,
            },
            status=status.HTTP_200_OK,
        )