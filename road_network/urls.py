from django.urls import path

from .views import (
    RoadEdgeListView,
    PassengerNetworkAPIView,
    RoadNodeListView,
    RoutePreviewView,
    admin_move_vehicle_next,
    road_network_map,
admin_start_ride,
admin_complete_ride,
)


urlpatterns = [
    path(
        "nodes/",
        RoadNodeListView.as_view(),
        name="road-node-list",
    ),

    path(
        "edges/",
        RoadEdgeListView.as_view(),
        name="road-edge-list",
    ),


    path(
        "passenger-network/",
        PassengerNetworkAPIView.as_view(),
        name="passenger-network",
    ),

    path(
        "route/",
        RoutePreviewView.as_view(),
        name="road-route-preview",
    ),

    path(
        "map/",
        road_network_map,
        name="road-network-map",
    ),

    path(
        "map/vehicles/<int:vehicle_id>/move-next/",
        admin_move_vehicle_next,
        name="admin-map-move-next",
    ),

path(
    "map/rides/<int:ride_id>/start/",
    admin_start_ride,
    name="admin-map-start-ride",
),

path(
    "map/rides/<int:ride_id>/complete/",
    admin_complete_ride,
    name="admin-map-complete-ride",
),
]