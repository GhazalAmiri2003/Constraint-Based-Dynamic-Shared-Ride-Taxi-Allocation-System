from django.urls import path

from .web_views import (
    passenger_confirm_hold,
    passenger_hold_taxi,
    passenger_release_hold,
    passenger_taxi_options,
)


urlpatterns = [
    path(
        "passenger/ride-requests/"
        "<int:ride_request_id>/taxi-options/",
        passenger_taxi_options,
        name="passenger-taxi-options",
    ),

    path(
        "passenger/ride-requests/"
        "<int:ride_request_id>/hold-taxi/",
        passenger_hold_taxi,
        name="passenger-hold-taxi",
    ),

    path(
        "passenger/holds/"
        "<int:hold_id>/confirm/",
        passenger_confirm_hold,
        name="passenger-confirm-hold",
    ),

    path(
        "passenger/holds/"
        "<int:hold_id>/release/",
        passenger_release_hold,
        name="passenger-release-hold",
    ),
]