"""M2 batch 14: store idempotency claims for POST retries.

Revision ID: 20261122_0003
Revises: 20261116_0002
Create Date: 2026-11-22

The DDL mirrors ``app/models/idempotency.py`` one-for-one. ``(scope, key)`` is
unique so concurrent first requests cannot both own the same key; the service
layer resolves the loser's ``IntegrityError`` by re-reading the winner.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261122_0003"
down_revision: str | Sequence[str] | None = "20261116_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'completed')",
            name="ck_idempotency_records_state",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_records"),
        sa.UniqueConstraint(
            "scope", "key", name="uq_idempotency_records_scope_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
