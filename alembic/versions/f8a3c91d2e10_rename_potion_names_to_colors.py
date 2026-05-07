"""rename potion display names to colors; set list prices (pure 35, mixed 50)

Revision ID: f8a3c91d2e10
Revises: c1d2e3f4a5b6
Create Date: 2026-05-06

"""

from typing import Sequence, Union

from alembic import op


revision: str = "f8a3c91d2e10"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE potions SET name = 'Red'
        WHERE red_pct = 100 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 0;

        UPDATE potions SET name = 'Green'
        WHERE red_pct = 0 AND green_pct = 100 AND blue_pct = 0 AND dark_pct = 0;

        UPDATE potions SET name = 'Blue'
        WHERE red_pct = 0 AND green_pct = 0 AND blue_pct = 100 AND dark_pct = 0;

        UPDATE potions SET name = 'Dark'
        WHERE red_pct = 0 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 100;

        UPDATE potions SET name = 'Purple' WHERE sku = 'r50g0b50d0';
        UPDATE potions SET name = 'Yellow' WHERE sku = 'r50g50b0d0';
        UPDATE potions SET name = 'Cyan' WHERE sku = 'r0g50b50d0';
        UPDATE potions SET name = 'Rainbow' WHERE sku = 'r25g25b25d25';
        UPDATE potions SET name = 'Dark' WHERE sku = 'r0g0b0d100';

        UPDATE potions
        SET price = 35
        WHERE
          (red_pct = 100 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 100 AND blue_pct = 0 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 0 AND blue_pct = 100 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 100);

        UPDATE potions
        SET price = 50
        WHERE NOT (
          (red_pct = 100 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 100 AND blue_pct = 0 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 0 AND blue_pct = 100 AND dark_pct = 0)
          OR (red_pct = 0 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 100)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE potions
        SET price = CASE sku
          WHEN 'r50g0b50d0' THEN 60
          WHEN 'r50g50b0d0' THEN 60
          WHEN 'r0g50b50d0' THEN 60
          WHEN 'r25g25b25d25' THEN 70
          WHEN 'r0g0b0d100' THEN 65
          ELSE price
        END;

        UPDATE potions SET price = 44
        WHERE price = 35
          AND (
            (red_pct = 100 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 0)
            OR (red_pct = 0 AND green_pct = 100 AND blue_pct = 0 AND dark_pct = 0)
            OR (red_pct = 0 AND green_pct = 0 AND blue_pct = 100 AND dark_pct = 0)
          );

        UPDATE potions SET price = 60 WHERE price = 50;

        UPDATE potions SET name = '100/0/0/0'
        WHERE red_pct = 100 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 0;

        UPDATE potions SET name = '0/100/0/0'
        WHERE red_pct = 0 AND green_pct = 100 AND blue_pct = 0 AND dark_pct = 0;

        UPDATE potions SET name = '0/0/100/0'
        WHERE red_pct = 0 AND green_pct = 0 AND blue_pct = 100 AND dark_pct = 0;

        UPDATE potions SET name = '0/0/0/100'
        WHERE red_pct = 0 AND green_pct = 0 AND blue_pct = 0 AND dark_pct = 100;

        UPDATE potions SET name = '50/0/50/0' WHERE sku = 'r50g0b50d0';
        UPDATE potions SET name = '50/50/0/0' WHERE sku = 'r50g50b0d0';
        UPDATE potions SET name = '0/50/50/0' WHERE sku = 'r0g50b50d0';
        UPDATE potions SET name = '25/25/25/25' WHERE sku = 'r25g25b25d25';
        UPDATE potions SET name = '0/0/0/100' WHERE sku = 'r0g0b0d100';
        """
    )
