"""M2 batch 5: preserve ending blueprint order.

Revision ID: 20261116_0002
Revises: 20261115_0001
Create Date: 2026-11-16

Existing rows receive position 0. The ORM orders by ``(position, priority)``,
so old archives retain their previous priority order until they are rewritten.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261116_0002"
down_revision: str | Sequence[str] | None = "20261115_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("endings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "position",
                sa.SmallInteger(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_endings_position",
            "position >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("endings", schema=None) as batch_op:
        batch_op.drop_constraint("ck_endings_position", type_="check")
        batch_op.drop_column("position")
