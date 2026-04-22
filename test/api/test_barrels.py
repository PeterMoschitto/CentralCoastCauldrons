from unittest.mock import Mock, patch
from typing import List

from src.api.barrels import (
    Barrel,
    BarrelOrder,
    calculate_barrel_summary,
    create_barrel_plan,
)


def test_barrel_delivery_summary() -> None:
    delivery: List[Barrel] = [
        Barrel(
            sku="SMALL_RED_BARREL",
            ml_per_barrel=1000,
            potion_type=[1.0, 0.0, 0.0, 0.0],
            price=100,
            quantity=10,
        ),
        Barrel(
            sku="SMALL_GREEN_BARREL",
            ml_per_barrel=1000,
            potion_type=[0.0, 1.0, 0.0, 0.0],
            price=150,
            quantity=5,
        ),
    ]

    summary = calculate_barrel_summary(delivery)

    assert summary.gold_paid == 1750


@patch("src.api.barrels._ingredient_shortfalls")
def test_buy_cheapest_red_barrel_when_red_shortfall_is_highest(
    mock_shortfalls: Mock,
) -> None:
    mock_shortfalls.return_value = {
        "red": 500,
        "green": 100,
        "blue": 50,
        "dark": 0,
    }

    wholesale_catalog: List[Barrel] = [
        Barrel(
            sku="LARGE_RED_BARREL",
            ml_per_barrel=3000,
            potion_type=[1.0, 0.0, 0.0, 0.0],
            price=250,
            quantity=10,
        ),
        Barrel(
            sku="SMALL_RED_BARREL",
            ml_per_barrel=1000,
            potion_type=[1.0, 0.0, 0.0, 0.0],
            price=120,
            quantity=10,
        ),
        Barrel(
            sku="SMALL_BLUE_BARREL",
            ml_per_barrel=1000,
            potion_type=[0.0, 0.0, 1.0, 0.0],
            price=100,
            quantity=10,
        ),
    ]

    orders = create_barrel_plan(
        gold=200,
        max_barrel_capacity=10000,
        current_red_ml=0,
        current_green_ml=0,
        current_blue_ml=0,
        current_dark_ml=0,
        wholesale_catalog=wholesale_catalog,
        connection=Mock(),
    )

    assert isinstance(orders, list)
    assert len(orders) == 1
    assert isinstance(orders[0], BarrelOrder)
    assert orders[0].sku == "SMALL_RED_BARREL"
    assert orders[0].quantity == 1


@patch("src.api.barrels._ingredient_shortfalls")
def test_buy_dark_barrel_when_dark_shortfall_is_highest(
    mock_shortfalls: Mock,
) -> None:
    mock_shortfalls.return_value = {
        "red": 0,
        "green": 0,
        "blue": 0,
        "dark": 600,
    }

    wholesale_catalog: List[Barrel] = [
        Barrel(
            sku="SMALL_DARK_BARREL",
            ml_per_barrel=800,
            potion_type=[0.0, 0.0, 0.0, 1.0],
            price=120,
            quantity=5,
        ),
        Barrel(
            sku="SMALL_RED_BARREL",
            ml_per_barrel=1000,
            potion_type=[1.0, 0.0, 0.0, 0.0],
            price=100,
            quantity=5,
        ),
    ]

    orders = create_barrel_plan(
        gold=200,
        max_barrel_capacity=10000,
        current_red_ml=0,
        current_green_ml=0,
        current_blue_ml=0,
        current_dark_ml=0,
        wholesale_catalog=wholesale_catalog,
        connection=Mock(),
    )

    assert len(orders) == 1
    assert orders[0].sku == "SMALL_DARK_BARREL"
    assert orders[0].quantity == 1


@patch("src.api.barrels._ingredient_shortfalls")
def test_no_barrel_plan_when_nothing_is_affordable(
    mock_shortfalls: Mock,
) -> None:
    mock_shortfalls.return_value = {
        "red": 400,
        "green": 200,
        "blue": 0,
        "dark": 0,
    }

    wholesale_catalog: List[Barrel] = [
        Barrel(
            sku="SMALL_RED_BARREL",
            ml_per_barrel=1000,
            potion_type=[1.0, 0.0, 0.0, 0.0],
            price=500,
            quantity=5,
        ),
        Barrel(
            sku="SMALL_GREEN_BARREL",
            ml_per_barrel=1000,
            potion_type=[0.0, 1.0, 0.0, 0.0],
            price=600,
            quantity=5,
        ),
    ]

    orders = create_barrel_plan(
        gold=100,
        max_barrel_capacity=10000,
        current_red_ml=0,
        current_green_ml=0,
        current_blue_ml=0,
        current_dark_ml=0,
        wholesale_catalog=wholesale_catalog,
        connection=Mock(),
    )

    assert orders == []


@patch("src.api.barrels._ingredient_shortfalls")
def test_no_barrel_plan_when_capacity_is_full(
    mock_shortfalls: Mock,
) -> None:
    mock_shortfalls.return_value = {
        "red": 1000,
        "green": 1000,
        "blue": 1000,
        "dark": 1000,
    }

    wholesale_catalog: List[Barrel] = [
        Barrel(
            sku="SMALL_RED_BARREL",
            ml_per_barrel=1000,
            potion_type=[1.0, 0.0, 0.0, 0.0],
            price=100,
            quantity=10,
        )
    ]

    orders = create_barrel_plan(
        gold=500,
        max_barrel_capacity=10000,
        current_red_ml=2500,
        current_green_ml=2500,
        current_blue_ml=2500,
        current_dark_ml=2500,
        wholesale_catalog=wholesale_catalog,
        connection=Mock(),
    )

    assert orders == []