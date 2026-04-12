"""add potions carts and cart_items tables

Revision ID: 97d394630dfe
Revises: 9358ac0306a8
Create Date: 2026-04-11 13:28:42.241305

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97d394630dfe'
down_revision: Union[str, None] = '9358ac0306a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "potions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("red_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("green_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blue_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dark_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("price >= 0", name="ck_potions_price_non_negative"),
        sa.CheckConstraint("quantity >= 0", name="ck_potions_quantity_non_negative"),
        sa.CheckConstraint("red_pct >= 0", name="ck_potions_red_pct_non_negative"),
        sa.CheckConstraint("green_pct >= 0", name="ck_potions_green_pct_non_negative"),
        sa.CheckConstraint("blue_pct >= 0", name="ck_potions_blue_pct_non_negative"),
        sa.CheckConstraint("dark_pct >= 0", name="ck_potions_dark_pct_non_negative"),
        sa.CheckConstraint("red_pct + green_pct + blue_pct + dark_pct = 100", name="ck_potions_pct_sum_100"),
    )

    op.create_table(
        "carts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("customer_name", sa.String(), nullable=False),
        sa.Column("checked_out", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "cart_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cart_id", sa.Integer(), nullable=False),
        sa.Column("potion_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["cart_id"], ["carts.id"]),
        sa.ForeignKeyConstraint(["potion_id"], ["potions.id"]),
        sa.CheckConstraint("quantity >= 0", name="ck_cart_items_quantity_non_negative"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("cart_items")
    op.drop_table("carts")
    op.drop_table("potions")
