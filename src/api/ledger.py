import json
import sqlalchemy
from sqlalchemy.engine import Connection

# Shop capacity tiers (Potion Exchange): base storage plus purchased units in ledger.
CAPACITY_RESOURCE_TYPE = "capacity"
CAPACITY_KEY_ML = "ml"
CAPACITY_KEY_POTION = "potion"

ML_STORAGE_BASE = 10_000
ML_STORAGE_PER_TIER = 10_000
POTION_STORAGE_BASE = 50
POTION_STORAGE_PER_TIER = 50
CAPACITY_UNIT_GOLD_COST = 1000


def ledger_balance(connection: Connection, resource_type: str, resource_key: str) -> int:
    value = connection.execute(
        sqlalchemy.text(
            """
            SELECT COALESCE(SUM(change), 0)
            FROM inventory_ledger_entries
            where resource_type = :resource_type
            and resource_key = :resource_key
            """
        ),
        {
            "resource_type": resource_type,
            "resource_key": resource_key,
        },
    ).scalar_one()
    return int(value)


def get_gold_balance(connection) -> int:
    result = connection.execute(
        sqlalchemy.text(
            """
            SELECT COALESCE(SUM(change), 0) AS gold
            FROM inventory_ledger_entries
            WHERE resource_type = 'gold'
              AND resource_key = 'gold'
            """
        )
    ).one()

    return int(result.gold)


def get_ml_balance(connection, color: str) -> int:
    result = connection.execute(
        sqlalchemy.text(
            """
            SELECT COALESCE(SUM(change), 0) AS ml
            FROM inventory_ledger_entries
            WHERE resource_type = 'ml'
              AND resource_key = :color
            """
        ),
        {"color": color},
    ).one()

    return int(result.ml)


def get_potion_balance(connection, sku: str) -> int:
    result = connection.execute(
        sqlalchemy.text(
            """
            SELECT COALESCE(SUM(change), 0) AS quantity
            FROM inventory_ledger_entries
            WHERE resource_type = 'potion'
              AND resource_key = :sku
            """
        ),
        {"sku": sku},
    ).one()

    return int(result.quantity)


def total_potion_balance(connection: Connection) -> int:
    value = connection.execute(
        sqlalchemy.text(
            """
            SELECT COALESCE(SUM(change), 0)
            FROM inventory_ledger_entries
            WHERE resource_type = 'potion'
            """
        )
    ).scalar_one()
    return int(value)


def get_total_potions(connection: Connection) -> int:
    """Total bottled potion units (all SKUs) from the ledger; alias for inventory audit."""
    return total_potion_balance(connection)


def purchased_ml_capacity_units(connection: Connection) -> int:
    """Extra ML capacity tiers purchased (each tier adds ML_STORAGE_PER_TIER ml of max storage)."""
    return max(0, ledger_balance(connection, CAPACITY_RESOURCE_TYPE, CAPACITY_KEY_ML))


def purchased_potion_capacity_units(connection: Connection) -> int:
    """Extra potion slot tiers purchased (each tier adds POTION_STORAGE_PER_TIER bottle slots)."""
    return max(0, ledger_balance(connection, CAPACITY_RESOURCE_TYPE, CAPACITY_KEY_POTION))


def max_ml_storage_capacity(connection: Connection) -> int:
    """Maximum total ml held in barrels (base tier plus ledger-recorded purchases)."""
    return ML_STORAGE_BASE + ML_STORAGE_PER_TIER * purchased_ml_capacity_units(connection)


def max_potion_storage_capacity(connection: Connection) -> int:
    """Maximum bottled potion count (base tier plus ledger-recorded purchases)."""
    return POTION_STORAGE_BASE + POTION_STORAGE_PER_TIER * purchased_potion_capacity_units(connection)


def create_inventory_transaction(connection: Connection, transaction_type: str, description: str | None = None) -> int:
    row = connection.execute(
        sqlalchemy.text(
            """
            INSERT INTO inventory_transactions (transaction_type, description)
            VALUES (:transaction_type, :description)
            RETURNING id
            """
        ),
        {
            "transaction_type": transaction_type,
            "description": description,
        },
    ).one()
    return int(row.id)


def add_ledger_entry(
    connection: Connection,
    inventory_transaction_id: int,
    resource_type: str,
    resource_key: str,
    change: int,
) -> None:
    connection.execute(
        sqlalchemy.text(
            """
            INSERT INTO inventory_ledger_entries
                (inventory_transaction_id, resource_type, resource_key, change)
            VALUES
                (:inventory_transaction_id, :resource_type, :resource_key, :change)
            """
        ),
        {
            "inventory_transaction_id": inventory_transaction_id,
            "resource_type": resource_type,
            "resource_key": resource_key,
            "change": change,
        },
    )


def get_processed_response(connection: Connection, request_id: str, endpoint: str):
    row = connection.execute(
        sqlalchemy.text(
            """
            SELECT response
            FROM processed_requests
            WHERE request_id = :request_id
              AND endpoint = :endpoint
            """
        ),
        {
            "request_id": request_id,
            "endpoint": endpoint,
        },
    ).one_or_none()

    if row is None:
        return None

    r = row.response
    if isinstance(r, str):
        r = json.loads(r)
    return r


def store_processed_response(
    connection: Connection, request_id: str, endpoint: str, response: dict
) -> None:
    """One INSERT per successful idempotent operation """
    connection.execute(
        sqlalchemy.text(
            """
            INSERT INTO processed_requests (request_id, endpoint, response)
            VALUES (:request_id, :endpoint, CAST(:response_json AS jsonb))
            """
        ),
        {
            "request_id": request_id,
            "endpoint": endpoint,
            "response_json": json.dumps(response),
        },
    )
