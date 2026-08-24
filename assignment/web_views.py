from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from accounts.models import (
    PassengerProfile,
    UserProfile,
)
from assignment.hold_services import (
    TaxiHoldError,
    TaxiHoldService,
)
from assignment.models import TaxiHold
from assignment.services import (
    AssignmentError,
    AssignmentService,
)
from rides.models import RideRequest


# =========================================================
# Passenger Helper
# =========================================================

def get_passenger_for_user(user):
    """
    PassengerProfile کاربر را برمی‌گرداند.
    """

    if user.is_staff:
        return None

    profile = (
        UserProfile.objects
        .filter(user=user)
        .first()
    )

    if (
        profile is None
        or profile.role
        != UserProfile.Role.PASSENGER
    ):
        return None

    return (
        PassengerProfile.objects
        .filter(user=user)
        .first()
    )


# =========================================================
# Map Serialization Helpers
# =========================================================

def serialize_private_option_for_map(option):
    return {
        "rank": option.rank,
        "vehicle_id": option.vehicle_id,
        "driver_username": option.driver_username,
        "current_node_id": option.current_node_id,
        "current_node_name": option.current_node_name,
        "capacity": option.capacity,
        "pickup_eta_minutes": option.pickup_eta_minutes,
        "pickup_distance_km": option.pickup_distance_km,
        "pickup_path_node_ids": list(
            option.pickup_path_node_ids
        ),
        "trip_eta_minutes": option.trip_eta_minutes,
        "trip_distance_km": option.trip_distance_km,
        "trip_path_node_ids": list(
            option.trip_path_node_ids
        ),
        "total_eta_minutes": option.total_eta_minutes,
        "total_distance_km": option.total_distance_km,
        "estimated_price": float(
            option.estimated_price
        ),
    }


def serialize_hold_vehicle_for_map(active_hold):
    if (
        active_hold is None
        or active_hold.vehicle.current_node_id is None
    ):
        return None

    return {
        "vehicle_id":
            active_hold.vehicle_id,

        "current_node_id":
            active_hold.vehicle.current_node_id,

        "current_node_name":
            active_hold.vehicle.current_node.name,
    }


# =========================================================
# Taxi Options Page
# =========================================================

@login_required(login_url="/login/")
def passenger_taxi_options(
    request,
    ride_request_id,
):
    passenger = get_passenger_for_user(
        request.user
    )

    if passenger is None:
        if request.user.is_staff:
            return redirect("/admin/")

        return redirect("/login/")


    # Passenger فقط Request خودش
    ride_request = get_object_or_404(
        RideRequest.objects.select_related(
            "pickup_node",
            "destination_node",
        ),
        pk=ride_request_id,
        passenger=passenger,
    )


    # فقط Pending Request باید Options داشته باشد
    if (
        ride_request.status
        != RideRequest.Status.PENDING
    ):
        messages.error(
            request,
            "This ride request is no longer pending.",
        )

        return redirect(
            "/passenger/dashboard/"
        )


    # =====================================================
    # Check Existing Active Hold
    # =====================================================

    active_hold = (
        TaxiHoldService.get_active_hold(
            ride_request
        )
    )


    # اگر Hold داریم، نیازی نیست Options دوباره بسازیم
    if active_hold:
        return render(
            request,
            "assignment/passenger_taxi_options.html",
            {
                "ride_request":
                    ride_request,

                "options":
                    [],

                "active_hold":
                    active_hold,

                "private_map_options":
                    [],

                "active_hold_vehicle_data":
                    serialize_hold_vehicle_for_map(
                        active_hold
                    ),
            },
        )


    # =====================================================
    # Generate Ranked Options
    # =====================================================

    try:
        options = (
            AssignmentService
            .generate_private_taxi_options(
                ride_request
            )
        )

    except AssignmentError as error:
        messages.error(
            request,
            str(error),
        )

        return redirect(
            "/passenger/dashboard/"
        )


    return render(
        request,
        "assignment/passenger_taxi_options.html",
        {
            "ride_request":
                ride_request,

            "options":
                options,

            "active_hold":
                None,

            "private_map_options": [
                serialize_private_option_for_map(
                    option
                )
                for option in options
            ],

            "active_hold_vehicle_data":
                None,
        },
    )


# =========================================================
# Hold Taxi
# =========================================================

@login_required(login_url="/login/")
def passenger_hold_taxi(
    request,
    ride_request_id,
):
    if request.method != "POST":
        return redirect(
            "/passenger/dashboard/"
        )


    passenger = get_passenger_for_user(
        request.user
    )

    if passenger is None:
        return redirect("/login/")


    ride_request = get_object_or_404(
        RideRequest,
        pk=ride_request_id,
        passenger=passenger,
    )


    vehicle_id = request.POST.get(
        "vehicle_id"
    )


    if not vehicle_id:
        messages.error(
            request,
            "Please select a taxi.",
        )

        return redirect(
            f"/passenger/ride-requests/"
            f"{ride_request.id}/taxi-options/"
        )


    try:
        hold = (
            AssignmentService
            .create_private_taxi_hold(
                ride_request,
                int(vehicle_id),
            )
        )

    except (
        AssignmentError,
        ValueError,
    ) as error:
        messages.error(
            request,
            str(error),
        )

        return redirect(
            f"/passenger/ride-requests/"
            f"{ride_request.id}/taxi-options/"
        )


    messages.success(
        request,
        "Taxi temporarily held. Please confirm before the timer expires.",
    )


    return redirect(
        f"/passenger/ride-requests/"
        f"{ride_request.id}/taxi-options/"
    )


# =========================================================
# Confirm Hold
# =========================================================

@login_required(login_url="/login/")
def passenger_confirm_hold(
    request,
    hold_id,
):
    if request.method != "POST":
        return redirect(
            "/passenger/dashboard/"
        )


    passenger = get_passenger_for_user(
        request.user
    )

    if passenger is None:
        return redirect("/login/")


    hold = get_object_or_404(
        TaxiHold.objects.select_related(
            "ride_request",
            "vehicle",
        ),
        pk=hold_id,
        ride_request__passenger=passenger,
    )


    try:
        ride, confirmed_hold = (
            AssignmentService
            .confirm_private_taxi_hold(
                hold
            )
        )

    except AssignmentError as error:
        messages.error(
            request,
            str(error),
        )

        return redirect(
            f"/passenger/ride-requests/"
            f"{hold.ride_request_id}/taxi-options/"
        )


    messages.success(
        request,
        (
            f"Taxi confirmed successfully. "
            f"Ride #{ride.id} is now assigned."
        ),
    )


    return redirect(
        "/passenger/dashboard/"
    )


# =========================================================
# Release Hold
# =========================================================

@login_required(login_url="/login/")
def passenger_release_hold(
    request,
    hold_id,
):
    if request.method != "POST":
        return redirect(
            "/passenger/dashboard/"
        )


    passenger = get_passenger_for_user(
        request.user
    )

    if passenger is None:
        return redirect("/login/")


    hold = get_object_or_404(
        TaxiHold.objects.select_related(
            "ride_request",
            "vehicle",
        ),
        pk=hold_id,
        ride_request__passenger=passenger,
    )


    ride_request_id = (
        hold.ride_request_id
    )


    try:
        TaxiHoldService.release_hold(
            hold
        )

    except TaxiHoldError as error:
        messages.error(
            request,
            str(error),
        )

        return redirect(
            f"/passenger/ride-requests/"
            f"{ride_request_id}/taxi-options/"
        )


    messages.success(
        request,
        "Taxi hold released.",
    )


    return redirect(
        f"/passenger/ride-requests/"
        f"{ride_request_id}/taxi-options/"
    )