from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from typing import List, Sequence
import sqlalchemy
from sqlalchemy.engine import Connection

from src.api import auth
from src.api.ledger import (
    add_ledger_entry,
    create_inventory_transaction,
    get_ml_balance,
    get_potion_balance,
    get_processed_response,
    store_processed_response,
)
from src import database as db

router = APIRouter(
    prefix="/bottler",
    tags=["bottler"],
    dependencies=[Depends(auth.get_api_key)],
)


PURE_TARGET = 3
MIXED_TARGET = 6


class PotionMixes(BaseModel):
    potion_type: List[int] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Must contain exactly 4 elements: [r, g, b, d]",
    )
    quantity: int = Field(
        ..., ge=1, le=10000, description="Quantity must be between 1 and 10,000"
    )

    @field_validator("potion_type")
    @classmethod
    def validate_potion_type(cls, potion_type: List[int]) -> List[int]:
        if sum(potion_type) != 100:
            raise ValueError("Sum of potion_type values must be exactly 100")
        return potion_type


def is_mixed_recipe(recipe: tuple[int, int, int, int]) -> bool:
    return sum(1 for pct in recipe if pct > 0) > 1


def uses_dark(recipe: tuple[int, int, int, int]) -> bool:
    return recipe[3] > 0


def max_bottles_for_recipe(
    r: int,
    g: int,
    b: int,
    d: int,
    red_ml: int,
    green_ml: int,
    blue_ml: int,
    dark_ml: int,
) -> int:
    limits: List[int] = []

    if r > 0:
        limits.append(red_ml // r)
    if g > 0:
        limits.append(green_ml // g)
    if b > 0:
        limits.append(blue_ml // b)
    if d > 0:
        limits.append(dark_ml // d)

    if not limits:
        return 0

    return min(limits)


def _catalog_rows_for_planning(
    connection: Connection,
) -> list[tuple[str, int, int, int, int, int]]:
    """
    Read potion recipes from potions metadata and current inventory from the ledger.

    Returns rows as:
        (sku, red_pct, green_pct, blue_pct, dark_pct, current_quantity)
    """
    rows = connection.execute(
        sqlalchemy.text(
            """
            SELECT sku, red_pct, green_pct, blue_pct, dark_pct
            FROM potions
            ORDER BY id
            """
        )
    ).fetchall()

    seen: set[tuple[int, int, int, int]] = set()
    out: list[tuple[str, int, int, int, int, int]] = []

    for row in rows:
        recipe = (row.red_pct, row.green_pct, row.blue_pct, row.dark_pct)
        if recipe in seen:
            continue

        seen.add(recipe)
        current_quantity = get_potion_balance(connection, row.sku)

        out.append(
            (
                row.sku,
                row.red_pct,
                row.green_pct,
                row.blue_pct,
                row.dark_pct,
                current_quantity,
            )
        )

    return out


def _potion_sku_for_recipe(
    connection: Connection, r: int, g: int, b: int, d: int
) -> str:
    """
    Return the existing potions.sku for this recipe.
    """
    row = connection.execute(
        sqlalchemy.text(
            """
            SELECT sku
            FROM potions
            WHERE red_pct = :r
              AND green_pct = :g
              AND blue_pct = :b
              AND dark_pct = :d
            LIMIT 1
            """
        ),
        {"r": r, "g": g, "b": b, "d": d},
    ).one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No potion recipe exists for [{r}, {g}, {b}, {d}]",
        )

    return str(row.sku)


def create_bottle_plan(
    red_ml: int,
    green_ml: int,
    blue_ml: int,
    dark_ml: int,
    *,
    catalog: Sequence[tuple[str, int, int, int, int, int]],
) -> List[PotionMixes]:
    """
    Bottle toward target inventory levels.

    Catalog rows are:
        (sku, red_pct, green_pct, blue_pct, dark_pct, current_quantity)
    """
    r_stock, g_stock, b_stock, d_stock = red_ml, green_ml, blue_ml, dark_ml
    plan: List[PotionMixes] = []

    def target_for_recipe(recipe: tuple[int, int, int, int]) -> int:
        return MIXED_TARGET if is_mixed_recipe(recipe) else PURE_TARGET

    def sort_key(row: tuple[str, int, int, int, int, int]):
        _, r, g, b, d, current_qty = row
        recipe = (r, g, b, d)
        return (
            not is_mixed_recipe(recipe),
            not uses_dark(recipe),
            current_qty,
        )

    ordered_catalog = sorted(catalog, key=sort_key)

    for _, r_pct, g_pct, b_pct, d_pct, current_qty in ordered_catalog:
        recipe = (r_pct, g_pct, b_pct, d_pct)
        target_qty = target_for_recipe(recipe)

        needed = max(0, target_qty - current_qty)
        if needed == 0:
            continue

        max_possible = max_bottles_for_recipe(
            r_pct,
            g_pct,
            b_pct,
            d_pct,
            r_stock,
            g_stock,
            b_stock,
            d_stock,
        )

        qty = min(needed, max_possible)
        if qty <= 0:
            continue

        plan.append(
            PotionMixes(
                potion_type=[r_pct, g_pct, b_pct, d_pct],
                quantity=qty,
            )
        )

        r_stock -= qty * r_pct
        g_stock -= qty * g_pct
        b_stock -= qty * b_pct
        d_stock -= qty * d_pct

    return plan


@router.post("/deliver/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def post_deliver_bottles(potions_delivered: List[PotionMixes], order_id: int):
    """
    V3:
    Record delivery of bottled potions in the ledger:
    - subtract raw ml
    - add potion inventory

    Idempotent by order_id.
    """
    with db.engine.begin() as connection:
        cached = get_processed_response(connection, str(order_id), "bottle_delivery")
        if cached is not None:
            return

        transaction_id = create_inventory_transaction(
            connection,
            "bottle_delivery",
            f"bottle delivery order {order_id}",
        )

        for potion in potions_delivered:
            r, g, b, d = potion.potion_type
            q = potion.quantity

            red_ml_used = q * r
            green_ml_used = q * g
            blue_ml_used = q * b
            dark_ml_used = q * d

            sku = _potion_sku_for_recipe(connection, r, g, b, d)

            # Safety check against current ledger balances
            if get_ml_balance(connection, "red") < red_ml_used:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient red ml for this delivery",
                )
            if get_ml_balance(connection, "green") < green_ml_used:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient green ml for this delivery",
                )
            if get_ml_balance(connection, "blue") < blue_ml_used:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient blue ml for this delivery",
                )
            if get_ml_balance(connection, "dark") < dark_ml_used:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient dark ml for this delivery",
                )

            if red_ml_used:
                add_ledger_entry(connection, transaction_id, "ml", "red", -red_ml_used)
            if green_ml_used:
                add_ledger_entry(connection, transaction_id, "ml", "green", -green_ml_used)
            if blue_ml_used:
                add_ledger_entry(connection, transaction_id, "ml", "blue", -blue_ml_used)
            if dark_ml_used:
                add_ledger_entry(connection, transaction_id, "ml", "dark", -dark_ml_used)

            add_ledger_entry(connection, transaction_id, "potion", sku, q)

        store_processed_response(
            connection,
            str(order_id),
            "bottle_delivery",
            {"status": "ok"},
        )


@router.post("/plan", response_model=List[PotionMixes])
def get_bottle_plan():
    """
    Gets the plan for bottling potions.

    Colors are expressed as integers from 0 to 100 and must sum to exactly 100.
    V3 reads raw ml from the ledger.
    """
    with db.engine.begin() as connection:
        red_ml = get_ml_balance(connection, "red")
        green_ml = get_ml_balance(connection, "green")
        blue_ml = get_ml_balance(connection, "blue")
        dark_ml = get_ml_balance(connection, "dark")

        catalog = _catalog_rows_for_planning(connection)

    return create_bottle_plan(
        red_ml=red_ml,
        green_ml=green_ml,
        blue_ml=blue_ml,
        dark_ml=dark_ml,
        catalog=catalog,
    )


if __name__ == "__main__":
    pass