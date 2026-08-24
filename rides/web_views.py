from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    redirect,
    render,
)

from accounts.models import (
    PassengerProfile,
    UserProfile,
)
from rides.models import (
    Ride,
    RidePassenger,
    RideRequest,
)
from shared_ride.models import RouteStop

from .web_forms import RideRequestForm


# =========================================================
# Passenger Cancellation Visibility
# =========================================================

def can_cancel_ride_request(
    ride_request,
):
    """
    UI فقط وقتی Cancel button را نشان می‌دهد که
    Passenger هنوز pickup نشده باشد.

    Backend دوباره همین rule را enforce می‌کند؛
    این helper فقط برای UI visibility است.
    """

    if (
        ride_request.status
        == RideRequest.Status.PENDING
    ):
        return True

    if (
        ride_request.status
        != RideRequest.Status.ASSIGNED
    ):
        return False

    active_ride = (
        Ride.objects
        .filter(
            passenger_groups__ride_request=(
                ride_request
            ),

            status__in=[
                Ride.Status.ASSIGNED,
                Ride.Status.ACCEPTED,
                Ride.Status.IN_PROGRESS,
            ],
        )
        .order_by(
            "-assigned_at"
        )
        .first()
    )

    if active_ride is None:
        return False

    if (
        active_ride.ride_type
        == RideRequest.RideType.PRIVATE
    ):
        return (
            active_ride.status
            in {
                Ride.Status.ASSIGNED,
                Ride.Status.ACCEPTED,
            }
        )

    if (
        active_ride.ride_type
        != RideRequest.RideType.SHARED
    ):
        return False

    ride_passenger = (
        RidePassenger.objects
        .filter(
            ride=active_ride,
            ride_request=ride_request,
        )
        .first()
    )

    if ride_passenger is None:
        return False

    pickup_status = (
        RouteStop.objects
        .filter(
            route__ride=active_ride,

            ride_passenger=(
                ride_passenger
            ),

            stop_type=(
                RouteStop.StopType.PICKUP
            ),
        )
        .values_list(
            "status",
            flat=True,
        )
        .first()
    )

    return (
        pickup_status
        == RouteStop.Status.PENDING
    )


# =========================================================
# Passenger Dashboard
# =========================================================

@login_required(login_url="/login/")
def passenger_dashboard(request):

    # =====================================================
    # 1. Admin / Staff
    # =====================================================

    if request.user.is_staff:
        return redirect("/admin/")


    # =====================================================
    # 2. Check User Role
    # =====================================================

    profile = (
        UserProfile.objects
        .filter(
            user=request.user
        )
        .first()
    )


    if profile is None:
        return redirect("/login/")


    if (
        profile.role
        != UserProfile.Role.PASSENGER
    ):
        # Driver نباید وارد Passenger Dashboard شود
        if (
            profile.role
            == UserProfile.Role.DRIVER
        ):
            return redirect(
                "/driver/dashboard/"
            )

        return redirect("/")


    # =====================================================
    # 3. Passenger Profile
    # =====================================================

    passenger = (
        PassengerProfile.objects
        .filter(
            user=request.user
        )
        .first()
    )


    if passenger is None:
        messages.error(
            request,
            "Passenger profile was not found.",
        )

        return redirect("/logout/")


    # =====================================================
    # 4. Create Ride Request
    # =====================================================

    if request.method == "POST":

        form = RideRequestForm(
            request.POST
        )


        if form.is_valid():

            ride_request = form.save(
                commit=False
            )

            # Passenger را Backend تعیین می‌کند
            ride_request.passenger = (
                passenger
            )

            ride_request.status = (
                RideRequest.Status.PENDING
            )

            ride_request.save()


            messages.success(
                request,
                "Ride request created successfully.",
            )


            # Prevent duplicate POST
            return redirect(
                "/passenger/dashboard/"
            )


    else:
        form = RideRequestForm()


    # =====================================================
    # 5. Passenger Ride History
    # =====================================================

    ride_requests = (
        RideRequest.objects
        .filter(
            passenger=passenger
        )
        .select_related(
            "pickup_node",
            "destination_node",
        )
        .order_by(
            "-id"
        )
    )


    # UI-only flag.
    # Security/business validation دوباره در Backend انجام می‌شود.
    for ride_request in ride_requests:

        ride_request.can_cancel = (
            can_cancel_ride_request(
                ride_request
            )
        )


    # =====================================================
    # 6. Render Dashboard
    # =====================================================

    return render(
        request,
        "rides/passenger_dashboard.html",
        {
            "form": form,
            "ride_requests": ride_requests,
        },
    )