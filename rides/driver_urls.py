from django.urls import path

from .driver_map_api import (
    DriverOperationalMapAPIView,
)
from .driver_views import (
    DriverRideAcceptView,
    DriverRideCompleteView,
    DriverRideDetailView,
    DriverRideListView,
    DriverRideRejectView,
    DriverRideStartView,
)


urlpatterns = [
    # =====================================================
    # Driver Operational Map
    # =====================================================

    path(
        "map/active/",
        DriverOperationalMapAPIView.as_view(),
        name="driver-operational-map",
    ),


    # =====================================================
    # Driver Ride List
    # =====================================================

    path(
        "",
        DriverRideListView.as_view(),
        name="driver-ride-list",
    ),


    # =====================================================
    # Driver Ride Detail
    # =====================================================

    path(
        "<int:ride_id>/",
        DriverRideDetailView.as_view(),
        name="driver-ride-detail",
    ),


    # =====================================================
    # Accept
    # =====================================================

    path(
        "<int:ride_id>/accept/",
        DriverRideAcceptView.as_view(),
        name="driver-ride-accept",
    ),


    # =====================================================
    # Reject
    # =====================================================

    path(
        "<int:ride_id>/reject/",
        DriverRideRejectView.as_view(),
        name="driver-ride-reject",
    ),


    # =====================================================
    # Start
    # =====================================================

    path(
        "<int:ride_id>/start/",
        DriverRideStartView.as_view(),
        name="driver-ride-start",
    ),


    # =====================================================
    # Complete
    # =====================================================

    path(
        "<int:ride_id>/complete/",
        DriverRideCompleteView.as_view(),
        name="driver-ride-complete",
    ),
]
