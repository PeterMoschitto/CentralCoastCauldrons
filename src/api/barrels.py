from dataclasses import dataclass
import math
import random
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from typing import List

import sqlalchemy
from src.api import auth
from src import database as db

router = APIRouter(
    prefix="/barrels",
    tags=["barrels"],
    dependencies=[Depends(auth.get_api_key)],
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
    """Pure-color wholesale barrels: one of r,g,b is 1.0. Use isclose so JSON floats match."""
    pt = barrel.potion_type
    for i, col in enumerate(("red_ml", "green_ml", "blue_ml")):
        if math.isclose(pt[i], 1.0, rel_tol=0, abs_tol=1e-5):
            return col
    return None


@router.post("/deliver/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def post_deliver_barrels(barrels_delivered: List[Barrel], order_id: int):
    """
    Processes barrels delivered based on the provided order_id. order_id is a unique value representing
    a single delivery; the call is idempotent based on the order_id.
    """
    print(f"barrels delivered: {barrels_delivered} order_id: {order_id}")

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

        # add ml for each barrel (float-safe; strict == 1 can miss JSON 1.0)
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
    pass


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
    wholesale_catalog: List[Barrel],
) -> List[BarrelOrder]:
    print(
        f"gold: {gold}, max_barrel_capacity: {max_barrel_capacity}, current_red_ml: {current_red_ml}, current_green_ml: {current_green_ml}, current_blue_ml: {current_blue_ml}, current_dark_ml: {current_dark_ml}, wholesale_catalog: {wholesale_catalog}"
    )

    # randomly pick red, green, blue
    random_color = random.choice(["red", "green", "blue"])

    #maps to potion count and the randomly selected color 
    potion_counts = {
        "red": current_red_potions,
        "green": current_green_potions,
        "blue": current_blue_potions,
    }

    color_index = {
        "red": 0,
        "green": 1,
        "blue": 2,
    }

    #if more than 5 potions buy nothing
    if potion_counts[random_color] >= 5:
        return []

    # find pure barrel (isclose: JSON floats may not satisfy == 1)
    idx = color_index[random_color]
    matching_barrels = [
        barrel
        for barrel in wholesale_catalog
        if math.isclose(barrel.potion_type[idx], 1.0, rel_tol=0, abs_tol=1e-5)
    ]

    # dont buy if not pure barrel
    if not matching_barrels:
        return []
    
    # smallest barrel of random color
    small_barrel = min(matching_barrels, key=lambda b: b.ml_per_barrel)

    # make sure we can afford it
    if small_barrel.price <= gold:
        return [BarrelOrder(sku=small_barrel.sku, quantity=1)]

    # return an empty list if no affordable red barrel is found
    return []


@router.post("/plan", response_model=List[BarrelOrder])
def get_wholesale_purchase_plan(wholesale_catalog: List[Barrel]):
    """
    Gets the plan for purchasing wholesale barrels. The call passes in a catalog of available barrels
    and the shop returns back which barrels they'd like to purchase and how many.
    """
    print(f"barrel catalog: {wholesale_catalog}")

    with db.engine.begin() as connection:
        row = connection.execute(
            sqlalchemy.text(
                """
                SELECT gold, red_ml, green_ml, blue_ml,
                    red_potions, green_potions, blue_potions
                FROM global_inventory
                """
            )
        ).one()

    gold = row.gold
    current_red_ml = row.red_ml
    current_green_ml = row.green_ml
    current_blue_ml = row.blue_ml
    current_red_potions = row.red_potions
    current_green_potions = row.green_potions
    current_blue_potions = row.blue_potions

    

    # TODO: fill in values correctly based on what is in your database
    return create_barrel_plan(
        gold=gold,
        max_barrel_capacity=10000,
        current_red_ml=current_red_ml,
        current_green_ml=current_green_ml,
        current_blue_ml=current_blue_ml,
        current_dark_ml=0,
        current_red_potions = current_red_potions,
        current_green_potions = current_green_potions,
        current_blue_potions = current_blue_potions,
        wholesale_catalog=wholesale_catalog,
    )
