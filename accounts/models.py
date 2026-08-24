from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):

    class Role(models.TextChoices):
        PASSENGER = "PASSENGER", "Passenger"
        DRIVER = "DRIVER", "Driver"
        ADMIN = "ADMIN", "Administrator"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.role}"


class PassengerProfile(models.Model):

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="passenger_profile",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Passenger: {self.user.username}"


class DriverProfile(models.Model):

    class AvailabilityStatus(models.TextChoices):
        ONLINE = "ONLINE", "Online"
        OFFLINE = "OFFLINE", "Offline"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="driver_profile",
    )

    availability_status = models.CharField(
        max_length=10,
        choices=AvailabilityStatus.choices,
        default=AvailabilityStatus.OFFLINE,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Driver: {self.user.username}"