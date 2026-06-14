"""Add status column to learning_queue

Revision ID: d3e4f5a6b7c8
Revises: 862fd17fc523
Create Date: 2026-06-14 01:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "862fd17fc523"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE wolfpack.learning_queue "
        "ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'pending'"
    )
    op.execute(
        "UPDATE wolfpack.learning_queue "
        "SET status = CASE "
        "  WHEN ingested_at IS NOT NULL THEN 'ingested' "
        "  WHEN retry_count >= 3 THEN 'failed' "
        "  ELSE 'pending' "
        "END "
        "WHERE status IS NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE wolfpack.learning_queue DROP COLUMN IF EXISTS status")
