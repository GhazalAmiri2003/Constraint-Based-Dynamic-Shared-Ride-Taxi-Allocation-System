from django.db import models
from django.db.models import Q


# =========================================================
# Route
# =========================================================

class Route(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    # هر Shared Ride یک Route فعال خودش را دارد
    ride = models.OneToOneField(
        "rides.Ride",
        on_delete=models.CASCADE,
        related_name="route",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    # Snapshot آخرین route calculation
    total_estimated_time_minutes = (
        models.PositiveIntegerField(
            default=0
        )
    )

    total_estimated_distance_km = (
        models.FloatField(
            default=0.0
        )
    )

    # با هر تغییر واقعی در stop order زیاد می‌شود.
    # بعداً برای stale-route detection مفید است.
    revision = models.PositiveIntegerField(
        default=1
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return (
            f"Route #{self.id} "
            f"- Ride #{self.ride_id} "
            f"- {self.status}"
        )


# =========================================================
# RouteStop
# =========================================================

class RouteStop(models.Model):

    class StopType(models.TextChoices):
        PICKUP = "PICKUP", "Pickup"
        DROPOFF = "DROPOFF", "Drop-off"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    # Route مادر
    route = models.ForeignKey(
        Route,
        on_delete=models.CASCADE,
        related_name="stops",
    )

    # Passenger Group
    #
    # به جای PassengerProfile مستقیم،
    # از RidePassenger استفاده می‌کنیم چون
    # Shared Engine با passenger group کار می‌کند.
    ride_passenger = models.ForeignKey(
        "rides.RidePassenger",
        on_delete=models.CASCADE,
        related_name="route_stops",
    )

    # RoadNode این Stop
    node = models.ForeignKey(
        "road_network.RoadNode",
        on_delete=models.PROTECT,
        related_name="route_stops",
    )

    stop_type = models.CharField(
        max_length=10,
        choices=StopType.choices,
    )

    # ترتیب Stop در Route
    # از 1 شروع می‌کنیم.
    sequence_number = (
        models.PositiveIntegerField()
    )

    # ETA واقعی ذخیره‌شده برای UI / audit
    estimated_arrival_time = (
        models.DateTimeField(
            null=True,
            blank=True,
        )
    )

    # ETA نسبی که Simulation Engine محاسبه می‌کند.
    # یعنی چند دقیقه از موقعیت فعلی Taxi
    # تا رسیدن به این Stop.
    estimated_arrival_minutes = (
        models.PositiveIntegerField(
            null=True,
            blank=True,
        )
    )

    actual_arrival_time = (
        models.DateTimeField(
            null=True,
            blank=True,
        )
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:

        ordering = [
            "sequence_number",
            "id",
        ]

        constraints = [

            # در یک Route دو Stop نمی‌توانند
            # sequence یکسان داشته باشند.
            models.UniqueConstraint(
                fields=[
                    "route",
                    "sequence_number",
                ],
                name=(
                    "unique_sequence_per_route"
                ),
            ),

            # برای هر Passenger Group در یک Route
            # فقط یک Pickup و یک Dropoff.
            models.UniqueConstraint(
                fields=[
                    "route",
                    "ride_passenger",
                    "stop_type",
                ],
                name=(
                    "unique_passenger_stop_type"
                ),
            ),

            # Sequence از 1 شروع می‌شود.
            models.CheckConstraint(
                condition=Q(
                    sequence_number__gte=1
                ),
                name=(
                    "route_stop_sequence_gte_1"
                ),
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "route",
                    "status",
                    "sequence_number",
                ],
                name="route_stop_lookup_idx",
            ),
        ]

    def __str__(self):
        return (
            f"Route #{self.route_id} "
            f"- Stop {self.sequence_number} "
            f"- {self.stop_type} "
            f"- Node #{self.node_id}"
        )




# =========================================================
# Shared Passenger Baseline
# =========================================================

class SharedPassengerBaseline(models.Model):
    """
    Baseline ثابت هر passenger group در Shared Ride.

    این مقدار بعد از insertionهای بعدی overwrite نمی‌شود،
    تا delay به مرور "عادی‌سازی" نشود.
    """

    ride_passenger = models.OneToOneField(
        "rides.RidePassenger",
        on_delete=models.CASCADE,
        related_name="shared_baseline",
    )

    # Direct Pickup → Destination time
    # بدون هیچ Shared detour
    direct_trip_time_minutes = (
        models.PositiveIntegerField()
    )

    # زمانی که هنگام Confirm به Passenger وعده داده شده
    baseline_expected_dropoff_at = (
        models.DateTimeField()
    )

    # Baseline روی کدام نسخه Route ایجاد شده
    baseline_route_revision = (
        models.PositiveIntegerField()
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    direct_trip_time_minutes__gte=1
                ),
                name=(
                    "shared_baseline_direct_time_gte_1"
                ),
            ),

            models.CheckConstraint(
                condition=Q(
                    baseline_route_revision__gte=1
                ),
                name=(
                    "shared_baseline_revision_gte_1"
                ),
            ),
        ]

    def __str__(self):
        return (
            f"Shared Baseline - "
            f"RidePassenger #{self.ride_passenger_id}"
        )