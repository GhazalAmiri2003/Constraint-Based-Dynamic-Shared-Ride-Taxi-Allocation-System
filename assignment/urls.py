from django.urls import path

from .views import (
    ConfirmPrivateTaxiHoldView,
    HoldPrivateTaxiView,
    PrivateTaxiOptionsView,
    ReleasePrivateTaxiHoldView,
)
from assignment.shared_api import (
    DriverActiveSharedRideAPIView,
    DriverSharedMoveNextAPIView,
    SharedTaxiConfirmAPIView,
    SharedTaxiHoldAPIView,
    SharedTaxiOptionsAPIView,
    SharedTaxiReleaseAPIView,
)
urlpatterns = [
    # Ranked Taxi Options
    path(
        "ride-requests/<int:ride_request_id>/taxi-options/",
        PrivateTaxiOptionsView.as_view(),
        name="private-taxi-options",
    ),

    # Create Temporary Hold
    path(
        "ride-requests/<int:ride_request_id>/hold-taxi/",
        HoldPrivateTaxiView.as_view(),
        name="hold-private-taxi",
    ),

    # Confirm Temporary Hold
    path(
        "holds/<int:hold_id>/confirm/",
        ConfirmPrivateTaxiHoldView.as_view(),
        name="confirm-private-taxi-hold",
    ),


path(
    "holds/<int:hold_id>/release/",
    ReleasePrivateTaxiHoldView.as_view(),
    name="release-private-taxi-hold",
),

    # =====================================================
    # Shared Ride - Passenger
    # =====================================================

    path(
        "ride-requests/<int:ride_request_id>/shared-options/",
        SharedTaxiOptionsAPIView.as_view(),
        name="shared-taxi-options",
    ),

    path(
        "ride-requests/<int:ride_request_id>/shared-hold/",
        SharedTaxiHoldAPIView.as_view(),
        name="shared-taxi-hold",
    ),

    path(
        "shared-holds/<int:hold_id>/confirm/",
        SharedTaxiConfirmAPIView.as_view(),
        name="shared-taxi-confirm",
    ),

    path(
        "shared-holds/<int:hold_id>/release/",
        SharedTaxiReleaseAPIView.as_view(),
        name="shared-taxi-release",
    ),

    # =====================================================
    # Shared Ride - Driver
    # =====================================================

    path(
        "driver/shared-ride/active/",
        DriverActiveSharedRideAPIView.as_view(),
        name="driver-active-shared-ride",
    ),

    path(
        "driver/shared-ride/move-next/",
        DriverSharedMoveNextAPIView.as_view(),
        name="driver-shared-move-next",
    ),
]