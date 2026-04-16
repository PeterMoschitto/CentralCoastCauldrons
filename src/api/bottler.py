from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from typing import List, Sequence
from src.api import auth
import sqlalchemy
from sqlalchemy.engine import Connection
from src import database as db

router = APIRouter(
    prefix="/bottler",
    tags=["bottler"],
    dependencies=[Depends(auth.get_api_key)],
)

# V2: Bottling only updates potions.quantity
# Planning reads recipes from the potions table. If the table is empty, we merge in _PURE_RECIPES
# below so the first ticks can still bottle pure colors from raw ml; deliver() INSERTs new rows
# for any mix. After that, behavior is driven by DB rows.
_PURE_RECIPES: tuple[tuple[int, int, int, int], ...] = (
    (100, 0, 0, 0),
    (0, 100, 0, 0),
    (0, 0, 100, 0),
    (0, 0, 0, 100),
)

_DEFAULT_PRICE = 50


def _sku_for_recipe(r: int, g: int, b: int, d: int) -> str:
    """deterministic SKU for [r,g,b,d]; must match catalog pattern"""
    s = f"r{r}g{g}b{b}d{d}"
    if len(s) <= 20:
        return s
    return f"m{r:02d}{g:02d}{b:02d}{d:02d}"


def _catalog_recipes_for_planning(connection: Connection) -> list[tuple[int, int, int, int]]:
    rows = connection.execute(
        sqlalchemy.text(
            """
            SELECT red_pct, green_pct, blue_pct, dark_pct
            FROM potions
            ORDER BY id
            """
        )
    ).fetchall()
    seen: set[tuple[int, int, int, int]] = set()
    out: list[tuple[int, int, int, int]] = []
    for row in rows:
        t = (row.red_pct, row.green_pct, row.blue_pct, row.dark_pct)
        if t not in seen:
            seen.add(t)
            out.append(t)
    for t in _PURE_RECIPES:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return out


def _ensure_potion_row(
    connection: Connection, r: int, g: int, b: int, d: int
) -> int:
    """return potions.id for this recipe, inserting a new catalog row if needed."""
    existing = connection.execute(
        sqlalchemy.text(
            """
            SELECT id FROM potions
            WHERE red_pct = :r AND green_pct = :g AND blue_pct = :b AND dark_pct = :d
            LIMIT 1
            """
        ),
        {"r": r, "g": g, "b": b, "d": d},
    ).one_or_none()
    if existing is not None:
        return int(existing.id)

    sku = _sku_for_recipe(r, g, b, d)
    name = f"{r}/{g}/{b}/{d}"
    return int(
        connection.execute(
            sqlalchemy.text(
                """
                INSERT INTO potions (sku, name, price, red_pct, green_pct, blue_pct, dark_pct, quantity)
                VALUES (:sku, :name, :price, :r, :g, :b, :d, 0)
                RETURNING id
                """
            ),
            {
                "sku": sku,
                "name": name,
                "price": _DEFAULT_PRICE,
                "r": r,
                "g": g,
                "b": b,
                "d": d,
            },
        ).scalar_one()
    )


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
    """How many 100ml bottles fit given RGBD ml stock and per-bottle ml (r,g,b,d)."""
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


def create_bottle_plan(
    red_ml: int,
    green_ml: int,
    blue_ml: int,
    dark_ml: int,
    *,
    catalog: Sequence[tuple[int, int, int, int]],
) -> List[PotionMixes]:
    """
    Greedily bottle using rows from the potions catalog (order preserved).
    Each tuple is (red_pct, green_pct, blue_pct, dark_pct) summing to 100.
    """
    r_stock, g_stock, b_stock, d_stock = red_ml, green_ml, blue_ml, dark_ml
    plan: List[PotionMixes] = []

    for r_pct, g_pct, b_pct, d_pct in catalog:
        qty = max_bottles_for_recipe(
            r_pct, g_pct, b_pct, d_pct, r_stock, g_stock, b_stock, d_stock
        )
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
    Delivery of potions requested after plan. order_id is a unique value representing
    a single delivery; the call is idempotent based on the order_id.
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

            potion_id = _ensure_potion_row(connection, r, g, b, d)

            inv_result = connection.execute(
                sqlalchemy.text(
                    """
                    UPDATE global_inventory
                    SET red_ml = red_ml - :red_ml_used,
                        green_ml = green_ml - :green_ml_used,
                        blue_ml = blue_ml - :blue_ml_used,
                        dark_ml = dark_ml - :dark_ml_used
                    WHERE red_ml >= :red_ml_used AND green_ml >= :green_ml_used
                      AND blue_ml >= :blue_ml_used AND dark_ml >= :dark_ml_used
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
    Each bottle has a quantity of what proportion of red, green, and blue potions to add.
    Colors are expressed in integers from 0 to 100 that must sum up to exactly 100.
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

        catalog = _catalog_recipes_for_planning(connection)

    return create_bottle_plan(
        red_ml=row.red_ml,
        green_ml=row.green_ml,
        blue_ml=row.blue_ml,
        dark_ml=row.dark_ml,
        catalog=catalog,
    )


if __name__ == "__main__":
    pass
