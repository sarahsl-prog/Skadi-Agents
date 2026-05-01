"""Add retry_count and last_error to learning_queue

Revision ID: b1c7f2a3e4d5
Revises: 299dd15933ab
Create Date: 2026-05-01 07:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c7f2a3e4d5"
down_revision: str | Sequence[str] | None = "299dd15933ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE wolfpack.learning_queue "
        "ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS last_error TEXT"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE wolfpack.learning_queue DROP COLUMN IF EXISTS retry_count")
    op.execute("ALTER TABLE wolfpack.learning_queue DROP COLUMN IF EXISTS last_error")
