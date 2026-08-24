from django.urls import path
from .movement_views import DriverMoveNextView
from .views import (
    MyVehicleView,
    VehicleAvailabilityView,
)


urlpatterns = [
    # گرفتن یا ساخت Vehicle خود Driver
    path(
        "me/",
        MyVehicleView.as_view(),
        name="my-vehicle",
    ),

    # تغییر availability ماشین
    path(
        "me/availability/",
        VehicleAvailabilityView.as_view(),
        name="vehicle-availability",
    ),

path(
    "me/move-next/",
    DriverMoveNextView.as_view(),
    name="driver-move-next",
),

]