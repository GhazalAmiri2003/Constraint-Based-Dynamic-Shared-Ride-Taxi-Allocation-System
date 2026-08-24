from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from accounts.driver_views import DriverAvailabilityView
urlpatterns = [
    # Django Admin
    path(
        "admin/",
        admin.site.urls,
    ),

    # Authentication APIs
    path(
        "api/auth/",
        include("accounts.urls"),
    ),

    # Vehicle APIs
    path(
        "api/vehicles/",
        include("fleet.urls"),
    ),

    # Ride Request APIs
    path(
        "api/ride-requests/",
        include("rides.urls"),
    ),


# Driver availability
path(
    "api/driver/availability/",
    DriverAvailabilityView.as_view(),
    name="driver-availability",
),


# Driver Ride APIs
path(
    "api/driver/rides/",
    include("rides.driver_urls"),
),


path(
    "api/road-network/",
    include("road_network.urls"),
),

path(
    "api/assignment/",
    include("assignment.urls"),
),
path(
    "",
    include("accounts.web_urls"),
),
path(
    "",
    include("rides.web_urls"),
),
path(
    "",
    include("assignment.web_urls"),
),
path(
    "",
    include("fleet.web_urls"),
),

]


# =========================================================
# Development Static Files
# =========================================================

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()