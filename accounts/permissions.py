from rest_framework.permissions import BasePermission

from .models import UserProfile


class IsDriver(BasePermission):
    # فقط Driver
    message = "Only drivers can perform this action."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if not hasattr(request.user, "profile"):
            return False

        return request.user.profile.role == UserProfile.Role.DRIVER


class IsPassenger(BasePermission):
    # فقط Passenger
    message = "Only passengers can perform this action."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if not hasattr(request.user, "profile"):
            return False

        return request.user.profile.role == UserProfile.Role.PASSENGER