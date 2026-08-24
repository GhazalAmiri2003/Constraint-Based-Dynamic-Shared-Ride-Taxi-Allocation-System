from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from fleet.models import Vehicle
from fleet.services import (
    VehicleMovementError,
    VehicleMovementService,
)
from rides.models import Ride, RideRequest

from .models import RoadEdge, RoadNode
from .serializers import (
    RoadEdgeSerializer,
    RoadNodeSerializer,
)
from .services import (
    RoadNetworkError,
    RoadNetworkService,
)

from rides.models import Ride, RideRequest
from rides.services import (
    RideLifecycleError,
    complete_ride,
    start_ride,
)




class RoadNodeListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # همه Nodeها
        nodes = RoadNode.objects.all().order_by("id")

        serializer = RoadNodeSerializer(
            nodes,
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class RoadEdgeListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # همه Edgeها
        edges = (
            RoadEdge.objects
            .select_related(
                "from_node",
                "to_node",
            )
            .all()
            .order_by("id")
        )

        serializer = RoadEdgeSerializer(
            edges,
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


# =========================================================
# Passenger Map Network API
# =========================================================

class PassengerNetworkAPIView(APIView):
    """
    Stable JSON payload for passenger-side Leaflet maps.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        nodes = list(
            RoadNode.objects
            .all()
            .order_by("id")
            .values(
                "id",
                "name",
                "x",
                "y",
            )
        )

        edges = list(
            RoadEdge.objects
            .all()
            .order_by("id")
            .values(
                "id",
                "from_node_id",
                "to_node_id",
                "distance_km",
                "travel_time_minutes",
                "road_type",
                "is_bidirectional",
            )
        )

        return Response(
            {
                "nodes": nodes,
                "edges": edges,
            },
            status=status.HTTP_200_OK,
        )


class RoutePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # ID مبدا و مقصد
        start_id = request.query_params.get("start")
        end_id = request.query_params.get("end")

        if not start_id or not end_id:
            return Response(
                {
                    "detail":
                        "start and end parameters are required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            start_node = RoadNode.objects.get(
                pk=start_id
            )

            end_node = RoadNode.objects.get(
                pk=end_id
            )

        except (RoadNode.DoesNotExist, ValueError):
            return Response(
                {
                    "detail":
                        "Invalid start or destination node."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # سریع‌ترین مسیر
            path = RoadNetworkService.shortest_path(
                start_node,
                end_node,
            )

            total_time = RoadNetworkService.route_time(
                path
            )

            total_distance = (
                RoadNetworkService.route_distance(path)
            )

        except RoadNetworkError as error:
            return Response(
                {
                    "detail": str(error)
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "start_node": start_node.id,
                "destination_node": end_node.id,

                "path": RoadNodeSerializer(
                    path,
                    many=True,
                ).data,

                "total_distance_km":
                    total_distance,

                "total_time_minutes":
                    total_time,
            },
            status=status.HTTP_200_OK,
        )


@staff_member_required
@ensure_csrf_cookie
def road_network_map(request):
    # Nodeهای شبکه
    nodes = list(
        RoadNode.objects
        .all()
        .order_by("id")
        .values(
            "id",
            "name",
            "x",
            "y",
        )
    )

    # Edgeهای شبکه
    edges = list(
        RoadEdge.objects
        .all()
        .order_by("id")
        .values(
            "id",
            "from_node_id",
            "to_node_id",
            "distance_km",
            "travel_time_minutes",
            "road_type",
            "is_bidirectional",
        )
    )

    # Taxiهایی که موقعیت دارند
    vehicles = list(
        Vehicle.objects
        .filter(
            current_node__isnull=False
        )
        .select_related(
            "driver__user",
            "current_node",
        )
        .order_by("id")
        .values(
            "id",
            "driver__user__username",
            "capacity",
            "is_available",
            "ride_mode",
            "current_node_id",
        )
    )

    # Routeهای Ride فعال
    ride_routes = []

    active_rides = (
        Ride.objects
        .filter(
            status__in=[
                Ride.Status.ASSIGNED,
                Ride.Status.ACCEPTED,
                Ride.Status.IN_PROGRESS,
            ],
            vehicle__current_node__isnull=False,
            ride_type=RideRequest.RideType.PRIVATE,
        )
        .select_related(
            "vehicle",
            "vehicle__current_node",
        )
        .order_by("id")
    )

    for ride in active_rides:
        # Private Ride باید یک Passenger Group داشته باشد
        passenger_group = (
            ride.passenger_groups
            .select_related(
                "ride_request__pickup_node",
                "ride_request__destination_node",
            )
            .first()
        )

        if not passenger_group:
            continue

        ride_request = passenger_group.ride_request

        # قبل از Pickup
        if ride.status in [
            Ride.Status.ASSIGNED,
            Ride.Status.ACCEPTED,
        ]:
            target_node = ride_request.pickup_node
            target_type = "PICKUP"

        # بعد از Pickup
        else:
            target_node = ride_request.destination_node
            target_type = "DROPOFF"

        try:
            path = RoadNetworkService.shortest_path(
                ride.vehicle.current_node,
                target_node,
            )

        except RoadNetworkError:
            # Route نامعتبر روی Map نمایش داده نمی‌شود
            continue

        ride_routes.append(
            {
                "ride_id":
                    ride.id,

                "vehicle_id":
                    ride.vehicle_id,

                "ride_status":
                    ride.status,

                "pickup_node_id":
                    ride_request.pickup_node_id,

                "destination_node_id":
                    ride_request.destination_node_id,

                "target_node_id":
                    target_node.id,

                "target_type":
                    target_type,

                "path_node_ids": [
                    node.id
                    for node in path
                ],
            }
        )

    return render(
        request,
        "road_network/map.html",
        {
            "nodes": nodes,
            "edges": edges,
            "vehicles": vehicles,
            "ride_routes": ride_routes,
        },
    )


@require_POST
@staff_member_required
def admin_move_vehicle_next(
    request,
    vehicle_id,
):
    # Taxi موردنظر
    vehicle = get_object_or_404(
        Vehicle,
        pk=vehicle_id,
    )

    try:
        result = (
            VehicleMovementService
            .move_next_for_active_ride(
                vehicle
            )
        )

    except VehicleMovementError as error:
        return JsonResponse(
            {
                "detail": str(error)
            },
            status=400,
        )

    moved_vehicle = result["vehicle"]

    return JsonResponse(
        {
            "vehicle_id":
                moved_vehicle.id,

            "current_node_id":
                moved_vehicle.current_node_id,

            "current_node_name":
                moved_vehicle.current_node.name,

            "target_type":
                result["target_type"],

            "target_node_name":
                result["target_node"].name,
        }
    )

@require_POST
@staff_member_required
def admin_start_ride(request, ride_id):
    # Ride موردنظر
    ride = get_object_or_404(
        Ride.objects.select_related(
            "vehicle__driver"
        ),
        pk=ride_id,
    )

    try:
        # Simulation Admin از همان Service اصلی استفاده می‌کند
        ride = start_ride(
            ride,
            ride.vehicle.driver,
        )

    except RideLifecycleError as error:
        return JsonResponse(
            {
                "detail": str(error)
            },
            status=400,
        )

    return JsonResponse(
        {
            "ride_id": ride.id,
            "ride_status": ride.status,
        }
    )

@require_POST
@staff_member_required
def admin_complete_ride(request, ride_id):
    # Ride موردنظر
    ride = get_object_or_404(
        Ride.objects.select_related(
            "vehicle__driver"
        ),
        pk=ride_id,
    )

    try:
        # همان Service اصلی Lifecycle
        ride = complete_ride(
            ride,
            ride.vehicle.driver,
        )

    except RideLifecycleError as error:
        return JsonResponse(
            {
                "detail": str(error)
            },
            status=400,
        )

    return JsonResponse(
        {
            "ride_id": ride.id,
            "ride_status": ride.status,
        }
    )