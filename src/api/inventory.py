from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
import sqlalchemy

from src.api import auth
from src import database as db
from src.api.ledger import (
    CAPACITY_KEY_ML,
    CAPACITY_KEY_POTION,
    CAPACITY_RESOURCE_TYPE,
    CAPACITY_UNIT_GOLD_COST,
    ML_STORAGE_PER_TIER,
    add_ledger_entry,
    create_inventory_transaction,
    get_gold_balance,
    get_ml_balance,
    get_processed_response,
    get_total_potions,
    max_ml_storage_capacity,
    max_potion_storage_capacity,
    store_processed_response,
)

router = APIRouter(
    prefix="/inventory",
    tags=["inventory"],
    dependencies=[Depends(auth.get_api_key)],
)

CAPACITY_DELIVERY_ENDPOINT = "capacity_delivery"

# After buying capacity, keep this much gold so barrel/checkout cycles stay viable.
MIN_GOLD_AFTER_ANY_CAPACITY_PURCHASE = 2000

# Buy one potion slot tier when at most this many bottle slots remain.
POTION_SLOTS_BUY_THRESHOLD = 10


class InventoryAudit(BaseModel):
    number_of_potions: int
    ml_in_barrels: int
    gold: int


class CapacityPlan(BaseModel):
    potion_capacity: int = Field(
        ge=0, le=10, description="Potion capacity units, max 10"
    )
    ml_capacity: int = Field(
        ge=0, le=10, description="ML capacity units, max 10"
    )


def _ml_tiers_for_large_barrel_headroom(headroom_ml: int) -> int:
    """
    Tiers of ML capacity to request so headroom can fit at least one 10k ml wholesale barrel.
    headroom_ml = max_ml_storage - current_total_ml (may be negative if overfilled).
    """
    if headroom_ml >= ML_STORAGE_PER_TIER:
        return 0
    gap = ML_STORAGE_PER_TIER - headroom_ml
    return (gap + ML_STORAGE_PER_TIER - 1) // ML_STORAGE_PER_TIER


def decide_capacity_plan(
    *,
    gold: int,
    total_ml: int,
    max_ml: int,
    total_potions: int,
    max_potions: int,
) -> CapacityPlan:
    """
    Pure planning logic: buy ML tiers when we cannot fit a 10k barrel, optionally buy potion tiers when low on slots
    """
    headroom_ml = max_ml - total_ml
    ml_units = _ml_tiers_for_large_barrel_headroom(headroom_ml)
    ml_units = min(ml_units, 10)

    while ml_units > 0 and gold - ml_units * CAPACITY_UNIT_GOLD_COST < MIN_GOLD_AFTER_ANY_CAPACITY_PURCHASE:
        ml_units -= 1

    ml_cost = ml_units * CAPACITY_UNIT_GOLD_COST
    gold_after_ml = gold - ml_cost

    slots_remaining = max_potions - total_potions
    potion_units = 0
    if slots_remaining <= POTION_SLOTS_BUY_THRESHOLD:
        if gold_after_ml >= CAPACITY_UNIT_GOLD_COST + MIN_GOLD_AFTER_ANY_CAPACITY_PURCHASE:
            potion_units = 1

    potion_units = min(potion_units, 10)

    return CapacityPlan(potion_capacity=potion_units, ml_capacity=ml_units)


@router.get("/audit", response_model=InventoryAudit)
def get_inventory():
    """
    Returns an audit of the current inventory USING LEDGER BALANCES. Any discrepancies between
    what is reported here and my source of truth will be posted
    as errors on potion exchange.
    """
    with db.engine.begin() as connection:
        gold = get_gold_balance(connection)
        red_ml = get_ml_balance(connection, "red")
        green_ml = get_ml_balance(connection, "green")
        blue_ml = get_ml_balance(connection, "blue")
        dark_ml = get_ml_balance(connection, "dark")
        number_of_potions = get_total_potions(connection)

    ml_in_barrels = red_ml + green_ml + blue_ml + dark_ml

    return InventoryAudit(
        number_of_potions=number_of_potions,
        ml_in_barrels=ml_in_barrels,
        gold=gold,
    )


@router.post("/plan", response_model=CapacityPlan)
def get_capacity_plan():
    """
    Provides a daily capacity purchase plan.

    - Start with 1 capacity for 50 potions and 1 capacity for 10,000 ml of potion.
    - Each additional capacity unit costs 1000 gold.
    """
    with db.engine.begin() as connection:
        gold = get_gold_balance(connection)
        red_ml = get_ml_balance(connection, "red")
        green_ml = get_ml_balance(connection, "green")
        blue_ml = get_ml_balance(connection, "blue")
        dark_ml = get_ml_balance(connection, "dark")
        total_ml = red_ml + green_ml + blue_ml + dark_ml
        max_ml = max_ml_storage_capacity(connection)
        total_potions = get_total_potions(connection)
        max_potions = max_potion_storage_capacity(connection)

        return decide_capacity_plan(
            gold=gold,
            total_ml=total_ml,
            max_ml=max_ml,
            total_potions=total_potions,
            max_potions=max_potions,
        )


@router.post("/deliver/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def deliver_capacity_plan(capacity_purchase: CapacityPlan, order_id: int):
    """
    Processes the delivery of the planned capacity purchase. order_id is a
    unique value representing a single delivery; the call is idempotent.

    - Start with 1 capacity for 50 potions and 1 capacity for 10,000 ml of potion.
    - Each additional capacity unit costs 1000 gold.
    """
    ml_units = capacity_purchase.ml_capacity
    potion_units = capacity_purchase.potion_capacity
    gold_cost = CAPACITY_UNIT_GOLD_COST * (ml_units + potion_units)

    with db.engine.begin() as connection:
        cached = get_processed_response(connection, str(order_id), CAPACITY_DELIVERY_ENDPOINT)
        if cached is not None:
            return

        transaction_id = create_inventory_transaction(
            connection,
            "capacity_delivery",
            f"capacity delivery order {order_id}",
        )

        add_ledger_entry(connection, transaction_id, "gold", "gold", -gold_cost)

        if ml_units > 0:
            add_ledger_entry(
                connection,
                transaction_id,
                CAPACITY_RESOURCE_TYPE,
                CAPACITY_KEY_ML,
                ml_units,
            )

        if potion_units > 0:
            add_ledger_entry(
                connection,
                transaction_id,
                CAPACITY_RESOURCE_TYPE,
                CAPACITY_KEY_POTION,
                potion_units,
            )

        store_processed_response(
            connection,
            str(order_id),
            CAPACITY_DELIVERY_ENDPOINT,
            {"status": "ok"},
        )
