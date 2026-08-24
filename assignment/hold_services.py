from datetime import timedelta

from django.conf import settings
from django.db import (
    IntegrityError,
    transaction,
)
from django.db.models import Q
from django.utils import timezone

from fleet.models import Vehicle
from rides.models import RideRequest

from .models import TaxiHold


class TaxiHoldError(Exception):
    # خطاهای Temporary Hold
    pass


class TaxiHoldService:

    # =====================================================
    # Expire old holds
    # =====================================================

    @staticmethod
    def _expire_stale_holds(
        ride_request,
        vehicle,
    ):
        """
        Holdهای ACTIVE مربوط به Request یا Vehicle
        را Lock می‌کند و اگر زمانشان تمام شده باشد
        EXPIRED می‌کند.
        """

        now = timezone.now()

        active_holds = (
            TaxiHold.objects
            .select_for_update()
            .filter(
                Q(ride_request=ride_request)
                | Q(vehicle=vehicle),
                status=TaxiHold.Status.ACTIVE,
            )
        )

        for hold in active_holds:

            if hold.expires_at <= now:

                hold.status = (
                    TaxiHold.Status.EXPIRED
                )

                hold.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )


    # =====================================================
    # Create Hold
    # =====================================================

    @staticmethod
    @transaction.atomic
    def create_hold(
        ride_request,
        vehicle,
    ):
        """
        Taxi را برای مدت کوتاه برای RideRequest
        رزرو می‌کند.

        هر Request فقط یک Hold فعال دارد.
        هر Vehicle هم فقط یک Hold فعال دارد.
        """

        # ---------------------------------------------
        # 1. Lock RideRequest
        # ---------------------------------------------

        locked_request = (
            RideRequest.objects
            .select_for_update()
            .get(
                pk=ride_request.pk
            )
        )


        # Request باید هنوز Pending باشد
        if (
            locked_request.status
            != RideRequest.Status.PENDING
        ):
            raise TaxiHoldError(
                "Only pending ride requests can hold a taxi."
            )


        # فعلاً فقط Private Ride
        if (
            locked_request.ride_type
            != RideRequest.RideType.PRIVATE
        ):
            raise TaxiHoldError(
                "Temporary hold currently supports private rides only."
            )


        # ---------------------------------------------
        # 2. Lock Vehicle
        # ---------------------------------------------

        try:
            locked_vehicle = (
                Vehicle.objects
                .select_for_update()
                .get(
                    pk=vehicle.pk
                )
            )

        except Vehicle.DoesNotExist:
            raise TaxiHoldError(
                "Selected taxi does not exist."
            )


        # ---------------------------------------------
        # 3. Expire old holds
        # ---------------------------------------------

        TaxiHoldService._expire_stale_holds(
            locked_request,
            locked_vehicle,
        )


        # ---------------------------------------------
        # 4. Existing Hold for this Request
        # ---------------------------------------------

        request_hold = (
            TaxiHold.objects
            .select_for_update()
            .filter(
                ride_request=locked_request,
                status=TaxiHold.Status.ACTIVE,
            )
            .first()
        )


        if request_hold:

            # همان Request همان Taxi را دوباره انتخاب کرده
            if (
                request_hold.vehicle_id
                == locked_vehicle.id
            ):
                return request_hold

            # Request قبلاً Taxi دیگری را Hold کرده
            raise TaxiHoldError(
                "This ride request already has an active taxi hold."
            )


        # ---------------------------------------------
        # 5. Existing Hold for this Vehicle
        # ---------------------------------------------

        vehicle_hold = (
            TaxiHold.objects
            .select_for_update()
            .filter(
                vehicle=locked_vehicle,
                status=TaxiHold.Status.ACTIVE,
            )
            .first()
        )


        if vehicle_hold:
            raise TaxiHoldError(
                "Selected taxi is temporarily held by another ride request."
            )


        # ---------------------------------------------
        # 6. Calculate Expiration
        # ---------------------------------------------

        duration_seconds = getattr(
            settings,
            "TAXI_HOLD_DURATION_SECONDS",
            120,
        )

        expires_at = (
            timezone.now()
            + timedelta(
                seconds=duration_seconds
            )
        )


        # ---------------------------------------------
        # 7. Create Hold
        # ---------------------------------------------

        try:
            hold = TaxiHold.objects.create(
                ride_request=locked_request,
                vehicle=locked_vehicle,
                status=TaxiHold.Status.ACTIVE,
                expires_at=expires_at,
            )

        except IntegrityError as error:
            # Database constraint هم لایه دوم حفاظت است
            raise TaxiHoldError(
                "Taxi could not be held because it is already reserved."
            ) from error


        return hold


    # =====================================================
    # Release Hold
    # =====================================================


    # =====================================================
    # Release Hold
    # =====================================================

    @staticmethod
    def release_hold(
            hold,
    ):
        """
        Hold فعال را RELEASED می‌کند.

        اگر Hold منقضی شده باشد:
        ACTIVE → EXPIRED
        و بعد Error برمی‌گرداند.
        """

        expired = False
        released_hold = None

        with transaction.atomic():

            # Hold را Lock می‌کنیم
            locked_hold = (
                TaxiHold.objects
                .select_for_update()
                .get(
                    pk=hold.pk
                )
            )

            # ---------------------------------------------
            # Expiration Check
            # ---------------------------------------------

            if (
                    locked_hold.status
                    == TaxiHold.Status.ACTIVE
                    and locked_hold.expires_at
                    <= timezone.now()
            ):
                locked_hold.status = (
                    TaxiHold.Status.EXPIRED
                )

                locked_hold.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

                # Error را بعد از Commit می‌دهیم
                expired = True

            else:

                # فقط Hold فعال قابل Release است
                if (
                        locked_hold.status
                        != TaxiHold.Status.ACTIVE
                ):
                    raise TaxiHoldError(
                        "Only active taxi holds can be released."
                    )

                locked_hold.status = (
                    TaxiHold.Status.RELEASED
                )

                locked_hold.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

                released_hold = locked_hold

        # Transaction اینجا Commit شده
        if expired:
            raise TaxiHoldError(
                "Taxi hold has already expired."
            )

        return released_hold

    # =====================================================
    # Check Hold
    # =====================================================

    @staticmethod
    @transaction.atomic
    def get_active_hold(
        ride_request,
    ):
        """
        Active Hold یک RideRequest را برمی‌گرداند.
        اگر منقضی شده باشد آن را EXPIRED می‌کند.
        """

        hold = (
            TaxiHold.objects
            .select_for_update()
            .filter(
                ride_request=ride_request,
                status=TaxiHold.Status.ACTIVE,
            )
            .first()
        )


        if not hold:
            return None


        if hold.expires_at <= timezone.now():

            hold.status = (
                TaxiHold.Status.EXPIRED
            )

            hold.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            return None


        return hold