from notifications.models import Notification


class NotificationService:

    # =====================================================
    # Recovery Started
    # =====================================================

    @staticmethod
    def recovery_started(
        *,
        ride_request,
        recovery_event,
    ):

        return Notification.objects.create(

            recipient=(
                ride_request
                .passenger
                .user
            ),

            ride_request=ride_request,

            recovery_event=recovery_event,

            notification_type=(
                Notification.Type.RECOVERY_STARTED
            ),

            title=(
                "Taxi reassignment started"
            ),

            message=(
                "Your taxi became unavailable before pickup. "
                "The system is searching for a replacement taxi."
            ),
        )


    # =====================================================
    # Recovery Completed
    # =====================================================

    @staticmethod
    def recovery_completed(
        *,
        ride_request,
        recovery_event,
        replacement_vehicle_id,
    ):

        return Notification.objects.create(

            recipient=(
                ride_request
                .passenger
                .user
            ),

            ride_request=ride_request,

            recovery_event=recovery_event,

            notification_type=(
                Notification.Type.RECOVERY_COMPLETED
            ),

            title=(
                "Replacement taxi assigned"
            ),

            message=(
                "A replacement taxi has been assigned "
                f"to your request. "
                f"Taxi #{replacement_vehicle_id}."
            ),
        )


    # =====================================================
    # Recovery Failed
    # =====================================================

    @staticmethod
    def recovery_failed(
        *,
        ride_request,
        recovery_event,
    ):

        return Notification.objects.create(

            recipient=(
                ride_request
                .passenger
                .user
            ),

            ride_request=ride_request,

            recovery_event=recovery_event,

            notification_type=(
                Notification.Type.RECOVERY_FAILED
            ),

            title=(
                "Taxi reassignment failed"
            ),

            message=(
                "The system could not find a feasible "
                "replacement taxi for your request."
            ),
        )