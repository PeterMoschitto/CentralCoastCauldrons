"""processed_requests: composite primary key (request_id, endpoint)

A single column PK on request_id caused duplicate key errors when inserting the second
idempotent record for a different endpoint.

Revision ID: c1d2e3f4a5b6
Revises: 72f1945e1575
Create Date: 2026-04-26

"""
from typing import Sequence, Union

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "72f1945e1575"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("processed_requests_pkey", "processed_requests", type_="primary")
    op.create_primary_key(
        "processed_requests_pkey",
        "processed_requests",
        ["request_id", "endpoint"],
    )


def downgrade() -> None:
    # Fails if two rows share the same request_id (the state this migration fixes).
    op.drop_constraint("processed_requests_pkey", "processed_requests", type_="primary")
    op.create_primary_key("processed_requests_pkey", "processed_requests", ["request_id"])
