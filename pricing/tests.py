import pytest

from decimal import Decimal

from pricing.services import (
    PricingError,
    PricingService,
)


def test_private_price_is_calculated_correctly():
    price = (
        PricingService
        .calculate_private_price(
            distance_km=5,
            travel_time_minutes=8,
        )
    )

    assert price == Decimal("11.10")


def test_zero_distance_and_time_returns_base_fare():
    price = (
        PricingService
        .calculate_private_price(
            distance_km=0,
            travel_time_minutes=0,
        )
    )

    assert (
        price
        == PricingService.BASE_FARE
    )


def test_negative_distance_is_rejected():
    with pytest.raises(
        PricingError
    ):
        (
            PricingService
            .calculate_private_price(
                distance_km=-1,
                travel_time_minutes=5,
            )
        )


def test_negative_travel_time_is_rejected():
    with pytest.raises(
        PricingError
    ):
        (
            PricingService
            .calculate_private_price(
                distance_km=2,
                travel_time_minutes=-3,
            )
        )