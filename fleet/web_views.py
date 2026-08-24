from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    redirect,
    render,
)

from accounts.models import (
    DriverProfile,
    UserProfile,
)
from fleet.models import Vehicle
from rides.models import (
    Ride,
    RidePassenger,
)

from .web_forms import VehicleRegistrationForm


# =========================================================
# Driver Dashboard
# =========================================================

@login_required(login_url="/login/")
def driver_dashboard(request):

    # =====================================================
    # 1. Admin
    # =====================================================

    if request.user.is_staff:
        return redirect("/admin/")


    # =====================================================
    # 2. Check Driver Role
    # =====================================================

    user_profile = (
        UserProfile.objects
        .filter(
            user=request.user
        )
        .first()
    )


    if user_profile is None:
        return redirect("/login/")


    if (
        user_profile.role
        != UserProfile.Role.DRIVER
    ):
        if (
            user_profile.role
            == UserProfile.Role.PASSENGER
        ):
            return redirect(
                "/passenger/dashboard/"
            )

        return redirect("/")


    # =====================================================
    # 3. Driver Profile
    # =====================================================

    driver_profile = (
        DriverProfile.objects
        .filter(
            user=request.user
        )
        .first()
    )


    if driver_profile is None:
        messages.error(
            request,
            "Driver profile was not found.",
        )

        return redirect("/logout/")


    # =====================================================
    # 4. Driver Vehicle
    # =====================================================

    vehicle = (
        Vehicle.objects
        .select_related(
            "current_node"
        )
        .filter(
            driver=driver_profile
        )
        .first()
    )


    # =====================================================
    # 5. Register Vehicle
    # =====================================================

    if vehicle is None:

        if request.method == "POST":

            vehicle_form = (
                VehicleRegistrationForm(
                    request.POST
                )
            )


            if vehicle_form.is_valid():

                vehicle = vehicle_form.save(
                    commit=False
                )

                vehicle.driver = (
                    driver_profile
                )

                vehicle.is_available = True

                vehicle.ride_mode = (
                    Vehicle.RideMode.IDLE
                )

                vehicle.save()


                messages.success(
                    request,
                    "Vehicle registered successfully.",
                )


                return redirect(
                    "/driver/dashboard/"
                )


        else:
            vehicle_form = (
                VehicleRegistrationForm()
            )


    else:
        vehicle_form = None


    # =====================================================
    # 6. Driver Ride List
    # =====================================================

    ride_rows = []


    if vehicle is not None:

        rides = (
            Ride.objects
            .filter(
                vehicle=vehicle
            )
            .order_by(
                "-id"
            )[:20]
        )


        for ride in rides:

            ride_passenger = (
                RidePassenger.objects
                .filter(
                    ride=ride
                )
                .select_related(
                    "ride_request",
                    "ride_request__pickup_node",
                    "ride_request__destination_node",
                    "ride_request__passenger__user",
                )
                .first()
            )


            ride_request = None
            passenger_username = "-"


            if ride_passenger:

                ride_request = (
                    ride_passenger
                    .ride_request
                )

                passenger_username = (
                    ride_request
                    .passenger
                    .user
                    .username
                )


            ride_rows.append(
                {
                    "ride": ride,

                    "ride_request":
                        ride_request,

                    "passenger_username":
                        passenger_username,
                }
            )


    # =====================================================
    # 7. Render
    # =====================================================

    return render(
        request,
        "fleet/driver_dashboard.html",
        {
            "driver_profile":
                driver_profile,

            "vehicle":
                vehicle,

            "vehicle_form":
                vehicle_form,

            "ride_rows":
                ride_rows,
        },
    )