from django.urls import path

from .web_views import (
    driver_dashboard,
)


urlpatterns = [
    path(
        "driver/dashboard/",
        driver_dashboard,
        name="driver-dashboard",
    ),
]