from dataclasses import dataclass
import math
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from typing import List

import sqlalchemy
from sqlalchemy.engine import Connection
from src.api import auth
from src.api.ledger import (
    add_ledger_entry,
    create_inventory_transaction,
    get_gold_balance,
    get_ml_balance,
    get_potion_balance,
    get_processed_response,
    store_processed_response,
)
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


def _resource_key_for_pure_barrel(barrel: Barrel) -> str | None:
    """
    Pure color wholesale barrels: exactly one of r,g,b,d is 1.0.
    Return the matching ledger ml resource key.
    """
    pt = barrel.potion_type
    for i, color in enumerate(("red", "green", "blue", "dark")):
        if math.isclose(pt[i], 1.0, rel_tol=0, abs_tol=1e-5):
            return color
    return None


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
    Compute raw-ml shortfalls from potion recipes in the potions table and
    current potion stock from the ledger.
    """
    rows = connection.execute(
        sqlalchemy.text(
            """
            SELECT sku, red_pct, green_pct, blue_pct, dark_pct
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
        current_qty = get_potion_balance(connection, row.sku)
        target = _target_for_recipe(recipe)
        needed_bottles = max(0, target - current_qty)

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
    Buy one affordable pure-color barrel for the color with the largest raw ml shortfall.
    Of those options, pick the best wholesale value: lowest price per ml
    (then largest ml if tied).
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

        affordable = [
            barrel
            for barrel in candidates
            if barrel.price <= gold and barrel.ml_per_barrel <= remaining_capacity
        ]
        if not affordable:
            continue

        chosen = min(
            affordable,
            key=lambda b: (b.price / b.ml_per_barrel, -b.ml_per_barrel),
        )
        return [BarrelOrder(sku=chosen.sku, quantity=1)]

    return []


@router.post("/deliver/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def post_deliver_barrels(barrels_delivered: List[Barrel], order_id: int):
    """
    V3:
    Record delivered barrels in the ledger:
    - subtract gold
    - add raw ml for pure color barrels

    Idempotent by order_id.
    """
    delivery = calculate_barrel_summary(barrels_delivered)

    with db.engine.begin() as connection:
        cached = get_processed_response(connection, str(order_id), "barrel_delivery")
        if cached is not None:
            return

        transaction_id = create_inventory_transaction(
            connection,
            "barrel_delivery",
            f"barrel delivery order {order_id}",
        )

        # Spend gold
        add_ledger_entry(
            connection,
            transaction_id,
            "gold",
            "gold",
            -delivery.gold_paid,
        )

        # Add ml for pure barrels
        for barrel in barrels_delivered:
            total_ml = barrel.ml_per_barrel * barrel.quantity
            color = _resource_key_for_pure_barrel(barrel)
            if color is None:
                continue

            add_ledger_entry(
                connection,
                transaction_id,
                "ml",
                color,
                total_ml,
            )

        store_processed_response(
            connection,
            str(order_id),
            "barrel_delivery",
            {"status": "ok"},
        )

@router.post("/plan", response_model=List[BarrelOrder])
def get_wholesale_purchase_plan(wholesale_catalog: List[Barrel]):
    """
    Gets the plan for purchasing wholesale barrels.
    """
    with db.engine.begin() as connection:
        gold = get_gold_balance(connection)
        red_ml = get_ml_balance(connection, "red")
        green_ml = get_ml_balance(connection, "green")
        blue_ml = get_ml_balance(connection, "blue")
        dark_ml = get_ml_balance(connection, "dark")

        return create_barrel_plan(
            gold=gold,
            max_barrel_capacity=10000,
            current_red_ml=red_ml,
            current_green_ml=green_ml,
            current_blue_ml=blue_ml,
            current_dark_ml=dark_ml,
            wholesale_catalog=wholesale_catalog,
            connection=connection,
        )