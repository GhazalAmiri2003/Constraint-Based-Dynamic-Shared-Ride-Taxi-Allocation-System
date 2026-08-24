from django.urls import path

from .web_views import (
    passenger_dashboard,
)


urlpatterns = [
    path(
        "passenger/dashboard/",
        passenger_dashboard,
        name="passenger-dashboard",
    ),
]