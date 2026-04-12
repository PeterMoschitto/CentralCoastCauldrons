"""add dark_ml to global_inventory

Revision ID: c4a8f1e2b9d0
Revises: 97d394630dfe
Create Date: 2026-04-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4a8f1e2b9d0"
down_revision: Union[str, None] = "97d394630dfe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "global_inventory",
        sa.Column("dark_ml", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_dark_ml_non_negative", "global_inventory", "dark_ml >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_dark_ml_non_negative", "global_inventory", type_="check")
    op.drop_column("global_inventory", "dark_ml")
