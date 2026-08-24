from django.conf import settings
from django.db import models


class Notification(models.Model):

    # =====================================================
    # Notification Types
    # =====================================================

    class Type(models.TextChoices):

        RECOVERY_STARTED = (
            "RECOVERY_STARTED",
            "Recovery Started",
        )

        RECOVERY_COMPLETED = (
            "RECOVERY_COMPLETED",
            "Recovery Completed",
        )

        RECOVERY_FAILED = (
            "RECOVERY_FAILED",
            "Recovery Failed",
        )


    # =====================================================
    # Recipient
    # =====================================================

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )


    # =====================================================
    # Optional Related Objects
    # =====================================================

    ride_request = models.ForeignKey(
        "rides.RideRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )


    recovery_event = models.ForeignKey(
        "recovery.RecoveryEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )


    # =====================================================
    # Content
    # =====================================================

    notification_type = models.CharField(
        max_length=30,
        choices=Type.choices,
    )

    title = models.CharField(
        max_length=150,
    )

    message = models.TextField()


    # =====================================================
    # State
    # =====================================================

    is_read = models.BooleanField(
        default=False,
    )


    # =====================================================
    # Timestamp
    # =====================================================

    created_at = models.DateTimeField(
        auto_now_add=True,
    )


    class Meta:

        ordering = [
            "-created_at",
        ]


    def __str__(self):

        return (
            f"Notification #{self.id} "
            f"- {self.notification_type}"
        )