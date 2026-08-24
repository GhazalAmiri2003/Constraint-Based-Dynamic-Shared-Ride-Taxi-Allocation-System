from django.urls import path

from .views import (
    DriverRegisterView,
    LoginView,
    LogoutView,
    MeView,
    PassengerRegisterView,
)


urlpatterns = [
    path(
        "register/passenger/",
        PassengerRegisterView.as_view(),
        name="register-passenger",
    ),
    path(
        "register/driver/",
        DriverRegisterView.as_view(),
        name="register-driver",
    ),
    path(
        "login/",
        LoginView.as_view(),
        name="login",
    ),
    path(
        "logout/",
        LogoutView.as_view(),
        name="logout",
    ),
    path(
        "me/",
        MeView.as_view(),
        name="me",
    ),
]