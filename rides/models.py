from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import PassengerProfile
from road_network.models import RoadNode
# Vehicle مربوط به Taxi
from fleet.models import Vehicle

class RideRequest(models.Model):

    class RideType(models.TextChoices):
        # سفر اختصاصی
        PRIVATE = "PRIVATE", "Private"

        # سفر اشتراکی
        SHARED = "SHARED", "Shared"

    class Status(models.TextChoices):
        # منتظر Assignment
        PENDING = "PENDING", "Pending"

        # Taxi به Request اختصاص داده شده
        ASSIGNED = "ASSIGNED", "Assigned"

        # سفر با موفقیت تمام شده
        COMPLETED = "COMPLETED", "Completed"

        # Passenger درخواست را لغو کرده
        CANCELLED = "CANCELLED", "Cancelled"

    # Passenger صاحب درخواست
    passenger = models.ForeignKey(
        PassengerProfile,
        on_delete=models.CASCADE,
        related_name="ride_requests",
    )

    # PRIVATE یا SHARED
    ride_type = models.CharField(
        max_length=10,
        choices=RideType.choices,
    )

    # تعداد افراد این Passenger Group
    passenger_count = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(4),
        ]
    )

    # Node شروع سفر
    pickup_node = models.ForeignKey(
        RoadNode,
        on_delete=models.PROTECT,
        related_name="pickup_ride_requests",
    )

    # Node مقصد
    destination_node = models.ForeignKey(
        RoadNode,
        on_delete=models.PROTECT,
        related_name="destination_ride_requests",
    )

    # توضیح اختیاری
    notes = models.CharField(
        max_length=255,
        blank=True,
    )

    # وضعیت Request
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # زمان ثبت
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
                # Passenger count باید 1 تا 4 باشد
                condition=models.Q(
                    passenger_count__gte=1,
                    passenger_count__lte=4,
                ),
                name="ride_request_passenger_count_1_to_4",
            ),
        ]

    def __str__(self):
        return (
            f"Request #{self.id} - "
            f"{self.passenger.user.username} - "
            f"{self.ride_type}"
        )



class Ride(models.Model):

    class Status(models.TextChoices):
        # Taxi به Ride اختصاص داده شده
        ASSIGNED = "ASSIGNED", "Assigned"

        # Driver سفر را قبول کرده
        ACCEPTED = "ACCEPTED", "Accepted"

        # Passenger سوار شده و سفر شروع شده
        IN_PROGRESS = "IN_PROGRESS", "In Progress"

        # سفر تمام شده
        COMPLETED = "COMPLETED", "Completed"

        # سفر قبل از پایان لغو شده
        CANCELLED = "CANCELLED", "Cancelled"

        # Driver این Assignment را رد کرده
        REJECTED = "REJECTED", "Rejected"

    # Taxi انجام‌دهنده Ride
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name="rides",
    )

    # PRIVATE یا SHARED
    ride_type = models.CharField(
        max_length=10,
        choices=RideRequest.RideType.choices,
    )

    # وضعیت عملیاتی Ride
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ASSIGNED,
    )

    # زمان Assignment
    assigned_at = models.DateTimeField(
        auto_now_add=True,
    )

    # زمان Accept توسط Driver
    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # زمان شروع واقعی Ride
    started_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # زمان پایان Ride
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # آخرین تغییر
    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return (
            f"Ride #{self.id} - "
            f"{self.vehicle} - "
            f"{self.status}"
        )


class RidePassenger(models.Model):

    # Ride مربوط به این Passenger Group
    ride = models.ForeignKey(
        Ride,
        on_delete=models.CASCADE,
        related_name="passenger_groups",
    )

    # Request اصلی Passenger
    ride_request = models.ForeignKey(
        RideRequest,
        on_delete=models.PROTECT,
        related_name="ride_links",
    )

    # زمان اضافه شدن Group به Ride
    joined_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                # یک Request در یک Ride دوبار ثبت نشود
                fields=[
                    "ride",
                    "ride_request",
                ],
                name="unique_ride_request_per_ride",
            ),
        ]

    def __str__(self):
        return (
            f"Ride #{self.ride_id} - "
            f"Request #{self.ride_request_id}"
        )