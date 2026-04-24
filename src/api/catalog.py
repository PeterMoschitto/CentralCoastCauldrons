import sqlalchemy
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Annotated

from src import database as db
from src.api.ledger import get_potion_balance

router = APIRouter()


class CatalogItem(BaseModel):
    sku: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_]{1,20}$")]
    name: str
    quantity: Annotated[int, Field(ge=1, le=10000)]
    price: Annotated[int, Field(ge=1, le=500)]
    potion_type: List[int] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Must contain exactly 4 elements: [r, g, b, d]",
    )


def is_mixed_potion(row) -> bool:
    nonzero_parts = sum(
        1 for pct in [row.red_pct, row.green_pct, row.blue_pct, row.dark_pct] if pct > 0
    )
    return nonzero_parts > 1


def create_catalog() -> List[CatalogItem]:
    with db.engine.begin() as connection:
        rows = connection.execute(
            sqlalchemy.text(
                """
                SELECT sku, name, price, red_pct, green_pct, blue_pct, dark_pct
                FROM potions
                """
            )
        ).fetchall()

        rows = sorted(rows, key=lambda row: (not is_mixed_potion(row), row.name))

        catalog: List[CatalogItem] = []

        for row in rows:
            quantity = get_potion_balance(connection, row.sku)

            if quantity <= 0:
                continue

            catalog.append(
                CatalogItem(
                    sku=row.sku,
                    name=row.name,
                    quantity=quantity,
                    price=row.price,
                    potion_type=[
                        row.red_pct,
                        row.green_pct,
                        row.blue_pct,
                        row.dark_pct,
                    ],
                )
            )

    return catalog


@router.get("/catalog/", tags=["catalog"], response_model=List[CatalogItem])
def get_catalog() -> List[CatalogItem]:
    """
    Retrieves the catalog of items. Each unique item combination should have only a single price.
    You can have at most 6 potion SKUs offered in your catalog at one time.
    """
    return create_catalog()