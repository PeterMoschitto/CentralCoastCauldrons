from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from typing import List, Sequence
import sqlalchemy
from sqlalchemy.engine import Connection

from src.api import auth
from src import database as db

router = APIRouter(
    prefix="/bottler",
    tags=["bottler"],
    dependencies=[Depends(auth.get_api_key)],
)


# Target inventory levels
# Mixed potions get a higher target than pure potions
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
    """A recipe is mixed if more than one color component is nonzero."""
    return sum(1 for pct in recipe if pct > 0) > 1


def uses_dark(recipe: tuple[int, int, int, int]) -> bool:
    """Whether the recipe uses any dark liquid."""
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
    """
    Return the maximum number of 100 ml bottles that can be made for a recipe.
    Recipe values are ml-per-bottle because the percentages sum to 100.
    """
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
) -> list[tuple[int, int, int, int, int]]:
    """
    Read potion recipes and current inventory from the potions table.

    Returns rows as:
        (red_pct, green_pct, blue_pct, dark_pct, current_quantity)
    """
    rows = connection.execute(
        sqlalchemy.text(
            """
            SELECT red_pct, green_pct, blue_pct, dark_pct, quantity
            FROM potions
            ORDER BY id
            """
        )
    ).fetchall()

    # Deduplicate by recipe 
    seen: set[tuple[int, int, int, int]] = set()
    out: list[tuple[int, int, int, int, int]] = []

    for row in rows:
        recipe = (row.red_pct, row.green_pct, row.blue_pct, row.dark_pct)
        if recipe not in seen:
            seen.add(recipe)
            out.append(
                (
                    row.red_pct,
                    row.green_pct,
                    row.blue_pct,
                    row.dark_pct,
                    row.quantity,
                )
            )

    return out


def _potion_id_for_recipe(
    connection: Connection, r: int, g: int, b: int, d: int
) -> int:
    """
    Return the existing potions.id for this recipe.
    """
    row = connection.execute(
        sqlalchemy.text(
            """
            SELECT id
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

    return int(row.id)


def create_bottle_plan(
    red_ml: int,
    green_ml: int,
    blue_ml: int,
    dark_ml: int,
    *,
    catalog: Sequence[tuple[int, int, int, int, int]],
) -> List[PotionMixes]:
    """
    Bottle toward target inventory levels.

    Catalog rows are:
        (red_pct, green_pct, blue_pct, dark_pct, current_quantity)

    Strategy:
    1. Prioritize mixed recipes before pure recipes
    2. Among recipes of the same type, prioritize lower current stock first
    3. Dark recipes fully supported and participate naturally
    """
    r_stock, g_stock, b_stock, d_stock = red_ml, green_ml, blue_ml, dark_ml
    plan: List[PotionMixes] = []

    def target_for_recipe(recipe: tuple[int, int, int, int]) -> int:
        return MIXED_TARGET if is_mixed_recipe(recipe) else PURE_TARGET

    def sort_key(row: tuple[int, int, int, int, int]):
        r, g, b, d, current_qty = row
        recipe = (r, g, b, d)

        # Sort order:
        # mixed first, then pure
        # lower current quantity first
        # dark using mixed recipes slightly ahead of non dark mixed recipes
        return (
            not is_mixed_recipe(recipe),
            not uses_dark(recipe),
            current_qty,
        )

    ordered_catalog = sorted(catalog, key=sort_key)

    for r_pct, g_pct, b_pct, d_pct, current_qty in ordered_catalog:
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
    Record delivery of bottled potions.

    This subtracts raw ml from global_inventory and increments potions.quantity.
    """
    _ = order_id 

    with db.engine.begin() as connection:
        for potion in potions_delivered:
            r, g, b, d = potion.potion_type
            q = potion.quantity

            red_ml_used = q * r
            green_ml_used = q * g
            blue_ml_used = q * b
            dark_ml_used = q * d

            potion_id = _potion_id_for_recipe(connection, r, g, b, d)

            inv_result = connection.execute(
                sqlalchemy.text(
                    """
                    UPDATE global_inventory
                    SET red_ml = red_ml - :red_ml_used,
                        green_ml = green_ml - :green_ml_used,
                        blue_ml = blue_ml - :blue_ml_used,
                        dark_ml = dark_ml - :dark_ml_used
                    WHERE red_ml >= :red_ml_used
                      AND green_ml >= :green_ml_used
                      AND blue_ml >= :blue_ml_used
                      AND dark_ml >= :dark_ml_used
                    """
                ),
                {
                    "red_ml_used": red_ml_used,
                    "green_ml_used": green_ml_used,
                    "blue_ml_used": blue_ml_used,
                    "dark_ml_used": dark_ml_used,
                },
            )

            if inv_result.rowcount != 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient raw ml for this delivery",
                )

            connection.execute(
                sqlalchemy.text(
                    """
                    UPDATE potions
                    SET quantity = quantity + :q
                    WHERE id = :potion_id
                    """
                ),
                {"q": q, "potion_id": potion_id},
            )


@router.post("/plan", response_model=List[PotionMixes])
def get_bottle_plan():
    """
    Gets the plan for bottling potions.

    Colors are expressed as integers from 0 to 100 and must sum to exactly 100.
    """
    with db.engine.begin() as connection:
        row = connection.execute(
            sqlalchemy.text(
                """
                SELECT red_ml, green_ml, blue_ml, dark_ml
                FROM global_inventory
                """
            )
        ).one()

        catalog = _catalog_rows_for_planning(connection)

    return create_bottle_plan(
        red_ml=row.red_ml,
        green_ml=row.green_ml,
        blue_ml=row.blue_ml,
        dark_ml=row.dark_ml,
        catalog=catalog,
    )


if __name__ == "__main__":
    pass