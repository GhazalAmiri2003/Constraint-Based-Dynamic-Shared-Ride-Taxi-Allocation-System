from django.db import models


class RecoveryEvent(models.Model):

    # =====================================================
    # Recovery Trigger
    # =====================================================

    class TriggerType(models.TextChoices):

        DRIVER_REJECT = (
            "DRIVER_REJECT",
            "Driver Reject",
        )

        DRIVER_UNAVAILABLE = (
            "DRIVER_UNAVAILABLE",
            "Driver Unavailable",
        )


    # =====================================================
    # Recovery Status
    # =====================================================

    class Status(models.TextChoices):

        PENDING = (
            "PENDING",
            "Pending",
        )

        PROCESSING = (
            "PROCESSING",
            "Processing",
        )

        COMPLETED = (
            "COMPLETED",
            "Completed",
        )

        FAILED = (
            "FAILED",
            "Failed",
        )


    # =====================================================
    # Relationships
    # =====================================================

    ride = models.ForeignKey(
        "rides.Ride",
        on_delete=models.CASCADE,
        related_name="recovery_events",
    )

    failed_vehicle = models.ForeignKey(
        "fleet.Vehicle",
        on_delete=models.PROTECT,
        related_name="recovery_events",
    )


    # =====================================================
    # Event Information
    # =====================================================

    trigger_type = models.CharField(
        max_length=30,
        choices=TriggerType.choices,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    message = models.TextField(
        blank=True,
    )


    # =====================================================
    # Metrics
    # =====================================================

    affected_passenger_groups = (
        models.PositiveIntegerField(
            default=0,
        )
    )

    recovery_duration_ms = (
        models.PositiveIntegerField(
            null=True,
            blank=True,
        )
    )


    # =====================================================
    # Timestamps
    # =====================================================

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )


    class Meta:

        ordering = [
            "-created_at",
        ]


    def __str__(self):

        return (
            f"Recovery #{self.id} "
            f"- Ride #{self.ride_id} "
            f"- {self.trigger_type}"
        )