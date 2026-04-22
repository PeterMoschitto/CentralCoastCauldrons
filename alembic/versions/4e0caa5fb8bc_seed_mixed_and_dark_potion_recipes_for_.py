"""seed mixed and dark potion recipes for bottler update

Revision ID: 4e0caa5fb8bc
Revises: c4a8f1e2b9d0
Create Date: 2026-04-21 17:42:43.250828

"""
from typing import Sequence, Union

from alembic import op


revision: str = "4e0caa5fb8bc"
down_revision: Union[str, None] = "c4a8f1e2b9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO potions (sku, name, price, red_pct, green_pct, blue_pct, dark_pct, quantity)
        VALUES
            ('r50g0b50d0',   '50/0/50/0',   60, 50,  0, 50,  0, 0),
            ('r50g50b0d0',   '50/50/0/0',   60, 50, 50,  0,  0, 0),
            ('r0g50b50d0',   '0/50/50/0',   60,  0, 50, 50,  0, 0),
            ('r25g25b25d25', '25/25/25/25', 70, 25, 25, 25, 25, 0),
            ('r0g0b0d100',   '0/0/0/100',   65,  0,  0,  0,100, 0)
        ON CONFLICT (sku) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM potions
        WHERE sku IN (
            'r50g0b50d0',
            'r50g50b0d0',
            'r0g50b50d0',
            'r25g25b25d25',
            'r0g0b0d100'
        )
        """
    )