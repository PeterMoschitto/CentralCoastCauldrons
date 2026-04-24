from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
import sqlalchemy
from src.api import auth
from src.api.ledger import (
    add_ledger_entry,
    create_inventory_transaction,
    get_potion_balance,
    get_processed_response,
    store_processed_response,
)
from enum import Enum
from typing import List, Optional, Sequence
from src import database as db


def summarize_checkout_totals(lines: Sequence[tuple[int, int]]) -> tuple[int, int]:
    """
    Compute checkout totals from cart lines.

    Each line is (quantity, unit_price_in_gold). Returns:
    (total_potions_bought, total_gold_paid).
    """
    total_potions = sum(qty for qty, _ in lines)
    total_gold = sum(qty * price for qty, price in lines)
    return total_potions, total_gold


def has_insufficient_stock(lines: Sequence[tuple[int, int]]) -> bool:
    """
    Each line is (line_quantity, stock_on_hand).
    Returns True if any requested line quantity exceeds stock.
    """
    return any(qty > stock for qty, stock in lines)


router = APIRouter(
    prefix="/carts",
    tags=["cart"],
    dependencies=[Depends(auth.get_api_key)],
)


class SearchSortOptions(str, Enum):
    customer_name = "customer_name"
    item_sku = "item_sku"
    line_item_total = "line_item_total"
    timestamp = "timestamp"


class SearchSortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class LineItem(BaseModel):
    line_item_id: int
    item_sku: str
    customer_name: str
    line_item_total: int
    timestamp: str


class SearchResponse(BaseModel):
    previous: Optional[str] = None
    next: Optional[str] = None
    results: List[LineItem]


@router.get("/search/", response_model=SearchResponse, tags=["search"])
def search_orders(
    customer_name: str = "",
    potion_sku: str = "",
    search_page: str = "",
    sort_col: SearchSortOptions = SearchSortOptions.timestamp,
    sort_order: SearchSortOrder = SearchSortOrder.desc,
):
    """
    Search for cart line items by customer name and/or potion sku.
    Placeholder implementation for now.
    """
    _ = customer_name
    _ = potion_sku
    _ = search_page
    _ = sort_col
    _ = sort_order

    return SearchResponse(previous=None, next=None, results=[])


class Customer(BaseModel):
    customer_id: str
    customer_name: str
    character_class: str
    character_species: str
    level: int = Field(ge=1, le=20)


@router.post("/visits/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
def post_visits(visit_id: int, customers: List[Customer]):
    """
    Shares the customers that visited the store on that tick.
    """
    _ = visit_id
    _ = customers
    return


class CartCreateResponse(BaseModel):
    cart_id: int


@router.post("/", response_model=CartCreateResponse)
def create_cart(new_cart: Customer):
    """
    Creates a new cart for a specific customer.
    """
    with db.engine.begin() as connection:
        cart_id = connection.execute(
            sqlalchemy.text(
                """
                INSERT INTO carts (
                    customer_id,
                    customer_name,
                    character_class,
                    character_species,
                    level
                )
                VALUES (
                    :customer_id,
                    :customer_name,
                    :character_class,
                    :character_species,
                    :level
                )
                RETURNING id
                """
            ),
            {
                "customer_id": new_cart.customer_id,
                "customer_name": new_cart.customer_name,
                "character_class": new_cart.character_class,
                "character_species": new_cart.character_species,
                "level": new_cart.level,
            },
        ).scalar_one()

    return CartCreateResponse(cart_id=int(cart_id))


class CartItem(BaseModel):
    quantity: int = Field(ge=1, description="Quantity must be at least 1")


@router.post("/{cart_id}/items/{item_sku}", status_code=status.HTTP_204_NO_CONTENT)
def set_item_quantity(cart_id: int, item_sku: str, cart_item: CartItem):
    with db.engine.begin() as connection:
        cart_row = connection.execute(
            sqlalchemy.text(
                """
                SELECT id, checked_out
                FROM carts
                WHERE id = :cart_id
                """
            ),
            {"cart_id": cart_id},
        ).one_or_none()

        if cart_row is None:
            raise HTTPException(status_code=404, detail="Cart not found")

        if cart_row.checked_out:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cart has already been checked out",
            )

        potion_row = connection.execute(
            sqlalchemy.text(
                """
                SELECT id
                FROM potions
                WHERE sku = :sku
                """
            ),
            {"sku": item_sku},
        ).one_or_none()

        if potion_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown item sku: {item_sku}",
            )

        potion_id = potion_row.id

        existing = connection.execute(
            sqlalchemy.text(
                """
                SELECT id
                FROM cart_items
                WHERE cart_id = :cart_id AND potion_id = :potion_id
                """
            ),
            {"cart_id": cart_id, "potion_id": potion_id},
        ).one_or_none()

        if existing is not None:
            connection.execute(
                sqlalchemy.text(
                    """
                    UPDATE cart_items
                    SET quantity = :quantity
                    WHERE id = :line_id
                    """
                ),
                {"quantity": cart_item.quantity, "line_id": existing.id},
            )
        else:
            connection.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO cart_items (cart_id, potion_id, quantity)
                    VALUES (:cart_id, :potion_id, :quantity)
                    """
                ),
                {
                    "cart_id": cart_id,
                    "potion_id": potion_id,
                    "quantity": cart_item.quantity,
                },
            )

    return


class CheckoutResponse(BaseModel):
    total_potions_bought: int
    total_gold_paid: int


class CartCheckout(BaseModel):
    payment: str


@router.post("/{cart_id}/checkout", response_model=CheckoutResponse)
def checkout(cart_id: int, cart_checkout: CartCheckout):
    """
    Handles the checkout process for a specific cart.

    V3:
    - reads potion stock from the ledger
    - writes potion and gold changes to the ledger
    - logs sale_events
    - is idempotent by cart_id
    """
    _ = cart_checkout

    with db.engine.begin() as connection:
        cached = get_processed_response(connection, str(cart_id), "checkout")
        if cached is not None:
            return CheckoutResponse(**cached)

        cart_row = connection.execute(
            sqlalchemy.text(
                """
                SELECT id,
                        checked_out,
                        customer_id,
                        customer_name,
                        character_class,
                        character_species,
                        level
                FROM carts
                WHERE id = :cart_id
                """
            ),
            {"cart_id": cart_id},
        ).one_or_none()

        if cart_row is None:
            raise HTTPException(status_code=404, detail="Cart not found")

        if cart_row.checked_out:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cart has already been checked out",
            )

        lines = connection.execute(
            sqlalchemy.text(
                """
                SELECT ci.quantity AS line_qty,
                       p.id AS potion_id,
                       p.sku AS sku,
                       p.price AS price
                FROM cart_items ci
                JOIN potions p ON p.id = ci.potion_id
                WHERE ci.cart_id = :cart_id
                """
            ),
            {"cart_id": cart_id},
        ).fetchall()

        if not lines:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cart has no items",
            )

        stock_lines = [
            (row.line_qty, get_potion_balance(connection, row.sku))
            for row in lines
        ]

        if has_insufficient_stock(stock_lines):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Not enough stock for one or more items in this cart",
            )

        total_potions_bought, total_gold_paid = summarize_checkout_totals(
            [(row.line_qty, row.price) for row in lines]
        )

        transaction_id = create_inventory_transaction(
            connection,
            "checkout",
            f"checkout cart {cart_id}",
        )

        # Ledger entries: potions decrease, gold increases
        for row in lines:
            add_ledger_entry(
                connection,
                transaction_id,
                "potion",
                row.sku,
                -row.line_qty,
            )

        add_ledger_entry(
            connection,
            transaction_id,
            "gold",
            "gold",
            total_gold_paid,
        )

        # Sale instrumentation
        now = datetime.utcnow()
        sold_day = now.strftime("%A")
        sold_hour = now.hour

        for row in lines:
            connection.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO sale_events (
                        inventory_transaction_id,
                        customer_id,
                        customer_name,
                        character_class,
                        character_species,
                        level,
                        potion_sku,
                        quantity,
                        unit_price,
                        sold_day,
                        sold_hour
                    )
                    VALUES (
                        :inventory_transaction_id,
                        :customer_id,
                        :customer_name,
                        :character_class,
                        :character_species,
                        :level,
                        :potion_sku,
                        :quantity,
                        :unit_price,
                        :sold_day,
                        :sold_hour
                    )
                    """
                ),
                {
                    "inventory_transaction_id": transaction_id,
                    "customer_id": cart_row.customer_id,
                    "customer_name": cart_row.customer_name,
                    "character_class": cart_row.character_class,
                    "character_species": cart_row.character_species,
                    "level": cart_row.level,
                    "potion_sku": row.sku,
                    "quantity": row.line_qty,
                    "unit_price": row.price,
                    "sold_day": sold_day,
                    "sold_hour": sold_hour,
                },
            )

        connection.execute(
            sqlalchemy.text(
                """
                UPDATE carts
                SET checked_out = true
                WHERE id = :cart_id
                """
            ),
            {"cart_id": cart_id},
        )

        response = {
            "total_potions_bought": total_potions_bought,
            "total_gold_paid": total_gold_paid,
        }

        store_processed_response(connection, str(cart_id), "checkout", response)

    return CheckoutResponse(**response)