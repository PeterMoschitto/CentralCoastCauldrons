from dataclasses import dataclass
import math
import random
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from typing import List

import sqlalchemy
from sqlalchemy.engine import Connection
from src.api import auth
from src import database as db

router = APIRouter(
    prefix="/barrels",
    tags=["barrels"],
    dependencies=[Depends(auth.get_api_key)],
)

# Random wholesale target: which pure elixir line (red/green/blue/dark) to restock this tick.
# Each entry is (name for messaging / counts, index into Barrel.potion_type for a pure barrel).
PURE_BARREL_COLOR_CHOICES: tuple[tuple[str, int], ...] = (
    ("red", 0),
    ("green", 1),
    ("blue", 2),
    ("dark", 3),
)


class Barrel(BaseModel):
    sku: str
    ml_per_barrel: int = Field(gt=0, description="Must be greater than 0")
    potion_type: List[float] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Must contain exactly 4 elements: [r, g, b, d] that sum to 1.0",
    )
    price: int = Field(ge=0, description="Price must be non-negative")
    quantity: int = Field(ge=0, description="Quantity must be non-negative")

    @field_validator("potion_type")
    @classmethod
    def validate_potion_type(cls, potion_type: List[float]) -> List[float]:
        if len(potion_type) != 4:
            raise ValueError("potion_type must have exactly 4 elements: [r, g, b, d]")
        if not abs(sum(potion_type) - 1.0) < 1e-6:
            raise ValueError("Sum of potion_type values must be exactly 1.0")
        return potion_type


class BarrelOrder(BaseModel):
    sku: str
    quantity: int = Field(gt=0, description="Quantity must be greater than 0")


@dataclass
class BarrelSummary:
    gold_paid: int


def calculate_barrel_summary(barrels: List[Barrel]) -> BarrelSummary:
    return BarrelSummary(gold_paid=sum(b.price * b.quantity for b in barrels))


def _ml_column_for_pure_barrel(barrel: Barrel) -> str | None:
    """Pure-color wholesale barrels: one of r,g,b,d is 1.0. Use isclose so JSON floats match."""
    pt = barrel.potion_type
    for i, col in enumerate(("red_ml", "green_ml", "blue_ml", "dark_ml")):
        if math.isclose(pt[i], 1.0, rel_tol=0, abs_tol=1e-5):
            return col
    return None


@router.post("/deliver/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def post_deliver_barrels(barrels_delivered: List[Barrel], order_id: int):
    """
    Processes barrels delivered based on the provided order_id. order_id is a unique value representing
    a single delivery; the call is idempotent based on the order_id.
    """
    _ = order_id

    delivery = calculate_barrel_summary(barrels_delivered)

    with db.engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                """
                UPDATE global_inventory SET
                gold = gold - :gold_paid
                """
            ),
            [{"gold_paid": delivery.gold_paid}],
        )

        # add ml for each barrel
        for barrel in barrels_delivered:
            total_ml = barrel.ml_per_barrel * barrel.quantity
            col = _ml_column_for_pure_barrel(barrel)
            if col is None:
                continue
            connection.execute(
                sqlalchemy.text(
                    f"UPDATE global_inventory SET {col} = {col} + :ml"
                ),
                {"ml": total_ml},
            )


def create_barrel_plan(
    gold: int,
    max_barrel_capacity: int,
    current_red_ml: int,
    current_green_ml: int,
    current_blue_ml: int,
    current_dark_ml: int,
    current_red_potions: int,
    current_green_potions: int,
    current_blue_potions: int,
    current_dark_potions: int,
    wholesale_catalog: List[Barrel],
) -> List[BarrelOrder]:
    """
    Pick a random elixir color (red, green, blue, or dark), then buy the smallest
    affordable pure barrel of that color if we hold fewer than 5 bottled potions
    of that pure type (counts are per-recipe from the potions table).
    """
    _ = (
        max_barrel_capacity,
        current_red_ml,
        current_green_ml,
        current_blue_ml,
        current_dark_ml,
    )

    potion_counts = {
        "red": current_red_potions,
        "green": current_green_potions,
        "blue": current_blue_potions,
        "dark": current_dark_potions,
    }

    color_name, idx = random.choice(PURE_BARREL_COLOR_CHOICES)

    if potion_counts[color_name] >= 5:
        return []

    matching_barrels = [
        barrel
        for barrel in wholesale_catalog
        if math.isclose(barrel.potion_type[idx], 1.0, rel_tol=0, abs_tol=1e-5)
    ]

    if not matching_barrels:
        return []

    small_barrel = min(matching_barrels, key=lambda b: b.ml_per_barrel)

    if small_barrel.price <= gold:
        return [BarrelOrder(sku=small_barrel.sku, quantity=1)]

    return []


def _null_sum_to_int(value: object) -> int:
    """SUM with no matching rows is NULL in SQL; treat as 0 for barrel logic."""
    return 0 if value is None else int(value)


def _pure_potion_bottle_counts(connection: Connection) -> tuple[int, int, int, int]:
    """Bottled counts for pure R/G/B/D recipes from the potions table."""
    row = connection.execute(
        sqlalchemy.text(
            """
            SELECT
                SUM(quantity) FILTER (
                    WHERE red_pct = 100 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 0
                ) AS pure_red,
                SUM(quantity) FILTER (
                    WHERE red_pct = 0 AND green_pct = 100 AND blue_pct = 0 AND dark_pct = 0
                ) AS pure_green,
                SUM(quantity) FILTER (
                    WHERE red_pct = 0 AND green_pct = 0 AND blue_pct = 100 AND dark_pct = 0
                ) AS pure_blue,
                SUM(quantity) FILTER (
                    WHERE red_pct = 0 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 100
                ) AS pure_dark
            FROM potions
            """
        )
    ).mappings().one()
    return (
        _null_sum_to_int(row["pure_red"]),
        _null_sum_to_int(row["pure_green"]),
        _null_sum_to_int(row["pure_blue"]),
        _null_sum_to_int(row["pure_dark"]),
    )


@router.post("/plan", response_model=List[BarrelOrder])
def get_wholesale_purchase_plan(wholesale_catalog: List[Barrel]):
    """
    Gets the plan for purchasing wholesale barrels. The call passes in a catalog of available barrels
    and the shop returns back which barrels they'd like to purchase and how many.
    """
    with db.engine.begin() as connection:
        row = connection.execute(
            sqlalchemy.text(
                """
                SELECT gold, red_ml, green_ml, blue_ml, dark_ml
                FROM global_inventory
                """
            )
        ).one()

        pure_red, pure_green, pure_blue, pure_dark = _pure_potion_bottle_counts(
            connection
        )

    return create_barrel_plan(
        gold=row.gold,
        max_barrel_capacity=10000,
        current_red_ml=row.red_ml,
        current_green_ml=row.green_ml,
        current_blue_ml=row.blue_ml,
        current_dark_ml=row.dark_ml,
        current_red_potions=pure_red,
        current_green_potions=pure_green,
        current_blue_potions=pure_blue,
        current_dark_potions=pure_dark,
        wholesale_catalog=wholesale_catalog,
    )
