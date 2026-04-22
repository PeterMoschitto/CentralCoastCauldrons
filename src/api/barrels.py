from dataclasses import dataclass
import math
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

# align barrel strat with bottler
PURE_TARGET = 3
MIXED_TARGET = 6

# extra reserve so we do not run dry immediately after one bottling cycle.
RAW_ML_RESERVE = {
    "red": 200,
    "green": 200,
    "blue": 200,
    "dark": 200,
}


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


def is_mixed_recipe(recipe: tuple[int, int, int, int]) -> bool:
    return sum(1 for pct in recipe if pct > 0) > 1


def _ml_column_for_pure_barrel(barrel: Barrel) -> str | None:
    """
    Pure color wholesale barrels: exactly one of r,g,b,d is 1.0.
    Return the matching global_inventory ml column.
    """
    pt = barrel.potion_type
    for i, col in enumerate(("red_ml", "green_ml", "blue_ml", "dark_ml")):
        if math.isclose(pt[i], 1.0, rel_tol=0, abs_tol=1e-5):
            return col
    return None


def _color_name_for_index(idx: int) -> str:
    return ("red", "green", "blue", "dark")[idx]


def _pure_barrels_by_color(wholesale_catalog: List[Barrel], color_idx: int) -> List[Barrel]:
    return [
        barrel
        for barrel in wholesale_catalog
        if math.isclose(barrel.potion_type[color_idx], 1.0, rel_tol=0, abs_tol=1e-5)
        and sum(1 for x in barrel.potion_type if x > 0) == 1
    ]


def _target_for_recipe(recipe: tuple[int, int, int, int]) -> int:
    return MIXED_TARGET if is_mixed_recipe(recipe) else PURE_TARGET


def _ingredient_shortfalls(
    connection: Connection,
    current_red_ml: int,
    current_green_ml: int,
    current_blue_ml: int,
    current_dark_ml: int,
) -> dict[str, int]:
    """
    Compute how short we are on raw ml by looking at all potion recipes
    and how far below target stock they are.

    For each potion recipe:
      needed_bottles = max(0, target - current_quantity)
      ingredient demand += needed_bottles * recipe_pct

    Then compare required raw ml to current raw ml.
    """
    rows = connection.execute(
        sqlalchemy.text(
            """
            SELECT red_pct, green_pct, blue_pct, dark_pct, quantity
            FROM potions
            """
        )
    ).fetchall()

    required_red = 0
    required_green = 0
    required_blue = 0
    required_dark = 0

    for row in rows:
        recipe = (row.red_pct, row.green_pct, row.blue_pct, row.dark_pct)
        target = _target_for_recipe(recipe)
        needed_bottles = max(0, target - row.quantity)

        required_red += needed_bottles * row.red_pct
        required_green += needed_bottles * row.green_pct
        required_blue += needed_bottles * row.blue_pct
        required_dark += needed_bottles * row.dark_pct

    desired = {
        "red": required_red + RAW_ML_RESERVE["red"],
        "green": required_green + RAW_ML_RESERVE["green"],
        "blue": required_blue + RAW_ML_RESERVE["blue"],
        "dark": required_dark + RAW_ML_RESERVE["dark"],
    }

    current = {
        "red": current_red_ml,
        "green": current_green_ml,
        "blue": current_blue_ml,
        "dark": current_dark_ml,
    }

    return {
        color: max(0, desired[color] - current[color])
        for color in ("red", "green", "blue", "dark")
    }


def create_barrel_plan(
    gold: int,
    max_barrel_capacity: int,
    current_red_ml: int,
    current_green_ml: int,
    current_blue_ml: int,
    current_dark_ml: int,
    wholesale_catalog: List[Barrel],
    *,
    connection: Connection,
) -> List[BarrelOrder]:
    """
    Buy the cheapest affordable pure barrel for the color with the largest raw ml shortfall.
    Shortfall is driven by potion recipes + current potion inventory in the potions table.
    """
    current_total_ml = current_red_ml + current_green_ml + current_blue_ml + current_dark_ml
    remaining_capacity = max_barrel_capacity - current_total_ml

    if remaining_capacity <= 0:
        return []

    shortfalls = _ingredient_shortfalls(
        connection,
        current_red_ml=current_red_ml,
        current_green_ml=current_green_ml,
        current_blue_ml=current_blue_ml,
        current_dark_ml=current_dark_ml,
    )

    # highest shortage first
    color_priority = sorted(
        shortfalls.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    for color_name, shortfall in color_priority:
        if shortfall <= 0:
            continue

        color_idx = {"red": 0, "green": 1, "blue": 2, "dark": 3}[color_name]
        candidates = _pure_barrels_by_color(wholesale_catalog, color_idx)

        if not candidates:
            continue

        # prefer the smallest affordable barrel that fits capacity
        affordable = [
            barrel
            for barrel in candidates
            if barrel.price <= gold and barrel.ml_per_barrel <= remaining_capacity
        ]
        if not affordable:
            continue

        chosen = min(affordable, key=lambda b: (b.ml_per_barrel, b.price))
        return [BarrelOrder(sku=chosen.sku, quantity=1)]

    return []


@router.post("/deliver/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def post_deliver_barrels(barrels_delivered: List[Barrel], order_id: int):
    """
    Record delivered barrels:
    - subtract gold
    - add raw ml for pure-color barrels
    """
    _ = order_id

    delivery = calculate_barrel_summary(barrels_delivered)

    with db.engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                """
                UPDATE global_inventory
                SET gold = gold - :gold_paid
                """
            ),
            {"gold_paid": delivery.gold_paid},
        )

        for barrel in barrels_delivered:
            total_ml = barrel.ml_per_barrel * barrel.quantity
            col = _ml_column_for_pure_barrel(barrel)
            if col is None:
                continue

            connection.execute(
                sqlalchemy.text(
                    f"""
                    UPDATE global_inventory
                    SET {col} = {col} + :ml
                    """
                ),
                {"ml": total_ml},
            )


@router.post("/plan", response_model=List[BarrelOrder])
def get_wholesale_purchase_plan(wholesale_catalog: List[Barrel]):
    """
    Gets the plan for purchasing wholesale barrels.
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

        return create_barrel_plan(
            gold=row.gold,
            max_barrel_capacity=10000,
            current_red_ml=row.red_ml,
            current_green_ml=row.green_ml,
            current_blue_ml=row.blue_ml,
            current_dark_ml=row.dark_ml,
            wholesale_catalog=wholesale_catalog,
            connection=connection,
        )