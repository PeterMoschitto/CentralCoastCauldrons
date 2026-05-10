"""add barrel_catalog_offerings for metric 2; set Yellow potion list price to 45 gold

Revision ID: a7e9b1c42d80
Revises: f8a3c91d2e10
Create Date: 2026-05-06

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7e9b1c42d80"
down_revision: Union[str, None] = "f8a3c91d2e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "barrel_catalog_offerings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "snapshot_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("ml_per_barrel", sa.Integer(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("catalog_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("red_frac", sa.Double(), nullable=False),
        sa.Column("green_frac", sa.Double(), nullable=False),
        sa.Column("blue_frac", sa.Double(), nullable=False),
        sa.Column("dark_frac", sa.Double(), nullable=False),
        sa.Column("liquid_type", sa.Text(), nullable=False),
        sa.Column("cost_per_ml", sa.Numeric(14, 8), nullable=False),
        sa.CheckConstraint("ml_per_barrel > 0", name="ck_barrel_offer_ml_positive"),
        sa.CheckConstraint("price >= 0", name="ck_barrel_offer_price_non_negative"),
        sa.CheckConstraint("catalog_quantity >= 0", name="ck_barrel_offer_qty_non_negative"),
    )
    op.create_index(
        "ix_barrel_catalog_offerings_snapshot_at",
        "barrel_catalog_offerings",
        ["snapshot_at"],
        unique=False,
    )

    op.execute(
        """
        UPDATE potions
        SET price = 45
        WHERE sku = 'r50g50b0d0';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE potions
        SET price = 50
        WHERE sku = 'r50g50b0d0';
        """
    )
    op.drop_index("ix_barrel_catalog_offerings_snapshot_at", table_name="barrel_catalog_offerings")
    op.drop_table("barrel_catalog_offerings")
