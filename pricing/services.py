from decimal import (
    Decimal,
    ROUND_HALF_UP,
)


class PricingError(Exception):
    # خطاهای محاسبه قیمت
    pass


class PricingService:
    """
    Standard private-ride pricing formula.

    Price =
        base fare
        + trip distance cost
        + trip time cost
    """

    BASE_FARE = Decimal("2.00")

    RATE_PER_KM = Decimal("1.50")

    RATE_PER_MINUTE = Decimal("0.20")


    @classmethod
    def calculate_private_price(
        cls,
        distance_km,
        travel_time_minutes,
    ):
        # -----------------------------
        # Validation
        # -----------------------------

        distance = Decimal(
            str(distance_km)
        )

        travel_time = Decimal(
            str(travel_time_minutes)
        )


        if distance < 0:
            raise PricingError(
                "Distance cannot be negative."
            )

        if travel_time < 0:
            raise PricingError(
                "Travel time cannot be negative."
            )


        # -----------------------------
        # Price calculation
        # -----------------------------

        price = (
            cls.BASE_FARE
            + (
                distance
                * cls.RATE_PER_KM
            )
            + (
                travel_time
                * cls.RATE_PER_MINUTE
            )
        )


        # دو رقم اعشار
        return price.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )