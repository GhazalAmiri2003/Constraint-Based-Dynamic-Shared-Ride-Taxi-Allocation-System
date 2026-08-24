from django.urls import path

from .tracking_api import (
    PassengerRideTrackingAPIView,
)

from .views import (
    RideRequestCancelView,
    RideRequestDetailView,
    RideRequestListCreateView,
)


urlpatterns = [
    # لیست درخواست‌ها + ساخت درخواست جدید
    path(
        "",
        RideRequestListCreateView.as_view(),
        name="ride-request-list-create",
    ),

    # Passenger simulated live tracking
    path(
        "<int:request_id>/tracking/",
        PassengerRideTrackingAPIView.as_view(),
        name="passenger-ride-tracking",
    ),

    # مشاهده یک درخواست مشخص
    path(
        "<int:request_id>/",
        RideRequestDetailView.as_view(),
        name="ride-request-detail",
    ),

    # لغو درخواست
    path(
        "<int:request_id>/cancel/",
        RideRequestCancelView.as_view(),
        name="ride-request-cancel",
    ),
]