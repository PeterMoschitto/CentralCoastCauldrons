from fastapi import APIRouter, Depends, status
import sqlalchemy

from src.api import auth
from src import database as db


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(auth.get_api_key)],
)


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset():
    """
    Reset the game state.

    V3:
    - Start a brand new shop run
    - Clear carts, ledger history for the run, processed requests, and sale events
    - Reset compatibility columns from older schema
    - Re-seed the ledger with the starting gold balance of 100
    """
    with db.engine.begin() as connection:
        # Clear current-run history/state tables
        connection.execute(
            sqlalchemy.text(
                """
                TRUNCATE TABLE
                    sale_events,
                    processed_requests,
                    inventory_ledger_entries,
                    inventory_transactions,
                    cart_items,
                    carts
                RESTART IDENTITY CASCADE
                """
            )
        )

        # Reset old compatibility columns so older code paths / inspection stay clean
        connection.execute(sqlalchemy.text("UPDATE potions SET quantity = 0"))

        connection.execute(
            sqlalchemy.text(
                """
                UPDATE global_inventory
                SET gold = 100,
                    red_ml = 0,
                    green_ml = 0,
                    blue_ml = 0,
                    dark_ml = 0,
                    red_potions = 0,
                    green_potions = 0,
                    blue_potions = 0
                """
            )
        )

        # Baseline transaction for fresh-run ledger state
        transaction_id = connection.execute(
            sqlalchemy.text(
                """
                INSERT INTO inventory_transactions (transaction_type, description)
                VALUES ('reset', 'Shop burn reset baseline')
                RETURNING id
                """
            )
        ).scalar_one()

        # Starting gold = 100
        connection.execute(
            sqlalchemy.text(
                """
                INSERT INTO inventory_ledger_entries
                    (inventory_transaction_id, resource_type, resource_key, change)
                VALUES
                    (:transaction_id, 'gold', 'gold', 100)
                """
            ),
            {"transaction_id": transaction_id},
        )