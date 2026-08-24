from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import DriverProfile
from road_network.models import RoadNode

class Vehicle(models.Model):

    class RideMode(models.TextChoices):
        # ماشین هیچ Ride فعالی ندارد
        IDLE = "IDLE", "Idle"

        # ماشین در Private Ride است
        PRIVATE = "PRIVATE", "Private"

        # ماشین در Shared Ride است
        SHARED = "SHARED", "Shared"

    # هر Driver در Scope فعلی یک Vehicle دارد
    driver = models.OneToOneField(
        DriverProfile,
        on_delete=models.CASCADE,
        related_name="vehicle",
    )

    # Proposal: حداکثر ظرفیت = 4
    capacity = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(4),
        ]
    )

    # وضعیت عملیاتی ماشین
    is_available = models.BooleanField(
        default=True,
    )

    # نوع Ride فعلی ماشین
    ride_mode = models.CharField(
        max_length=10,
        choices=RideMode.choices,
        default=RideMode.IDLE,
    )

    # زمان ایجاد رکورد
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    # آخرین Update
    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                # DB هم ظرفیت 1 تا 4 را enforce می‌کند
                condition=models.Q(
                    capacity__gte=1,
                    capacity__lte=4,
                ),
                name="vehicle_capacity_between_1_and_4",
            ),
        ]

    # موقعیت فعلی Taxi روی Road Network
    current_node = models.ForeignKey(
        RoadNode,
        on_delete=models.PROTECT,
        related_name="vehicles",
        null=True,
        blank=True,
    )
    def __str__(self):
        return f"Vehicle #{self.id} - {self.driver.user.username}"