"""add ledger tables for v3

also reduce prices of pure potions

Revision ID: 72f1945e1575
Revises: 4e0caa5fb8bc
Create Date: 2026-04-23 17:27:17.712882

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "72f1945e1575"
down_revision: Union[str, None] = "4e0caa5fb8bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Pure potion price discount: new_price = floor(old * _PURE_DISCOUNT_NUM / _PURE_DISCOUNT_DEN)
_PURE_DISCOUNT_NUM = 4
_PURE_DISCOUNT_DEN = 5


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "inventory_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()")),
        sa.Column("transaction_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )

    op.create_table(
        "inventory_ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inventory_transaction_id", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_key", sa.Text(), nullable=False),
        sa.Column("change", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["inventory_transaction_id"],
            ["inventory_transactions.id"],
        ),
    )

    op.create_table(
        "processed_requests",
        sa.Column("request_id", sa.Text(), primary_key=True),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()")),
    )

    op.create_table(
        "sale_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inventory_transaction_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Text()),
        sa.Column("customer_name", sa.Text()),
        sa.Column("character_class", sa.Text()),
        sa.Column("character_species", sa.Text()),
        sa.Column("level", sa.Integer()),
        sa.Column("potion_sku", sa.Text()),
        sa.Column("quantity", sa.Integer()),
        sa.Column("unit_price", sa.Integer()),
        sa.Column("sold_at", sa.TIMESTAMP(), server_default=sa.text("now()")),
        sa.Column("sold_day", sa.Text()),
        sa.Column("sold_hour", sa.Integer()),
        sa.ForeignKeyConstraint(
            ["inventory_transaction_id"],
            ["inventory_transactions.id"],
        ),
    )

    op.add_column("carts", sa.Column("character_class", sa.Text(), nullable=True))
    op.add_column("carts", sa.Column("character_species", sa.Text(), nullable=True))
    op.add_column("carts", sa.Column("level", sa.Integer(), nullable=True))

    # Lower list price for pure recipes
    op.execute(
        f"""
        UPDATE potions
        SET price = GREATEST(1, (price * {_PURE_DISCOUNT_NUM}) / {_PURE_DISCOUNT_DEN})
        WHERE
          (red_pct = 100 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 100 AND blue_pct = 0 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 0 AND blue_pct = 100 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 100);
        """
    )


def downgrade() -> None:
    # Restore pure potion prices 
    op.execute(
        f"""
        UPDATE potions
        SET price = GREATEST(1, (price * {_PURE_DISCOUNT_DEN} + {_PURE_DISCOUNT_NUM} - 1) / {_PURE_DISCOUNT_NUM})
        WHERE
          (red_pct = 100 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 100 AND blue_pct = 0 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 0 AND blue_pct = 100 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 100);
        """
    )

    op.drop_column("carts", "level")
    op.drop_column("carts", "character_species")
    op.drop_column("carts", "character_class")

    op.drop_table("sale_events")
    op.drop_table("processed_requests")
    op.drop_table("inventory_ledger_entries")
    op.drop_table("inventory_transactions")