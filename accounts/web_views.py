from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    login,
    logout,
)
from django.db import transaction
from django.shortcuts import redirect, render

from accounts.models import (
    DriverProfile,
    PassengerProfile,
    UserProfile,
)

from .web_forms import RegisterForm


# =========================================================
# Role Redirect
# =========================================================

def redirect_after_login(user):

    # Admin / Staff
    if user.is_staff:
        return redirect("/admin/")

    # UserProfile را مستقیم پیدا می‌کنیم
    profile = (
        UserProfile.objects
        .filter(user=user)
        .first()
    )

    if profile is None:
        return redirect("/login/")


    if (
        profile.role
        == UserProfile.Role.PASSENGER
    ):
        return redirect(
            "/passenger/dashboard/"
        )


    if (
        profile.role
        == UserProfile.Role.DRIVER
    ):
        return redirect(
            "/driver/dashboard/"
        )


    return redirect("/")
# =========================================================
# Login
# =========================================================

def login_view(request):

    # اگر قبلاً Login کرده
    if request.user.is_authenticated:
        return redirect_after_login(
            request.user
        )


    if request.method == "POST":

        username = request.POST.get(
            "username",
            "",
        ).strip()

        password = request.POST.get(
            "password",
            "",
        )


        user = authenticate(
            request,
            username=username,
            password=password,
        )


        if user is None:
            messages.error(
                request,
                "Invalid username or password.",
            )

        else:
            login(
                request,
                user,
            )

            return redirect_after_login(
                user
            )


    return render(
        request,
        "accounts/login.html",
    )


# =========================================================
# Register
# =========================================================

@transaction.atomic
def register_view(request):

    if request.user.is_authenticated:
        return redirect_after_login(
            request.user
        )


    if request.method == "POST":
        form = RegisterForm(
            request.POST
        )

        if form.is_valid():

            user = form.save(
                commit=False
            )

            user.email = form.cleaned_data.get(
                "email",
                "",
            )

            user.save()


            role = form.cleaned_data[
                "role"
            ]


            # ---------------------------------------------
            # UserProfile
            # ---------------------------------------------

            UserProfile.objects.create(
                user=user,
                role=role,
            )


            # ---------------------------------------------
            # Role-specific Profile
            # ---------------------------------------------

            if (
                role
                == UserProfile.Role.PASSENGER
            ):
                PassengerProfile.objects.create(
                    user=user
                )

            elif (
                role
                == UserProfile.Role.DRIVER
            ):
                DriverProfile.objects.create(
                    user=user,
                    availability_status=(
                        DriverProfile
                        .AvailabilityStatus
                        .OFFLINE
                    ),
                )


            # بعد از Register مستقیم Login
            login(
                request,
                user,
            )


            messages.success(
                request,
                "Registration successful.",
            )


            return redirect_after_login(
                user
            )

    else:
        form = RegisterForm()


    return render(
        request,
        "accounts/register.html",
        {
            "form": form,
        },
    )


# =========================================================
# Logout
# =========================================================

def logout_view(request):

    logout(request)

    return redirect(
        "/login/"
    )