from django.urls import path

from .web_views import (
    login_view,
    logout_view,
    register_view,
)


urlpatterns = [
    path(
        "login/",
        login_view,
        name="web-login",
    ),

    path(
        "register/",
        register_view,
        name="web-register",
    ),

    path(
        "logout/",
        logout_view,
        name="web-logout",
    ),
]