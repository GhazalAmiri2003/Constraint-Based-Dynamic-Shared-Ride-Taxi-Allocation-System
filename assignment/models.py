from django.db import models
from django.db.models import Q

from fleet.models import Vehicle
from rides.models import RideRequest


class TaxiHold(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CONFIRMED = "CONFIRMED", "Confirmed"
        RELEASED = "RELEASED", "Released"
        EXPIRED = "EXPIRED", "Expired"

    # RideRequest که Taxi را موقتاً نگه داشته
    ride_request = models.ForeignKey(
        RideRequest,
        on_delete=models.CASCADE,
        related_name="taxi_holds",
    )

    # Taxi رزروشده
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name="taxi_holds",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    # زمان پایان Hold
    expires_at = models.DateTimeField()

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )


    class Meta:
        constraints = [
            # یک RideRequest همزمان فقط یک Hold فعال
            models.UniqueConstraint(
                fields=[
                    "ride_request"
                ],
                condition=Q(
                    status="ACTIVE"
                ),
                name=(
                    "unique_active_hold_per_request"
                ),
            ),

            # یک Taxi همزمان فقط برای یک Request Hold شود
            models.UniqueConstraint(
                fields=[
                    "vehicle"
                ],
                condition=Q(
                    status="ACTIVE"
                ),
                name=(
                    "unique_active_hold_per_vehicle"
                ),
            ),
        ]


    def __str__(self):
        return (
            f"Hold #{self.id} - "
            f"Request #{self.ride_request_id} - "
            f"Vehicle #{self.vehicle_id} - "
            f"{self.status}"
        )