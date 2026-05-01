"""Add missing case-state columns + learning_queue retry fields

Revision ID: c2d8e3b4f5a6
Revises: b1c7f2a3e4d5
Create Date: 2026-05-01 08:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d8e3b4f5a6"
down_revision: str | Sequence[str] | None = "b1c7f2a3e4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE wolfpack.cases "
        "ADD COLUMN IF NOT EXISTS verdict_decision VARCHAR, "
        "ADD COLUMN IF NOT EXISTS overall_confidence INTEGER"
    )
    op.execute(
        "ALTER TABLE wolfpack.learning_queue "
        "ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS last_error TEXT"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE wolfpack.learning_queue DROP COLUMN IF EXISTS retry_count")
    op.execute("ALTER TABLE wolfpack.learning_queue DROP COLUMN IF EXISTS last_error")
    op.execute("ALTER TABLE wolfpack.cases DROP COLUMN IF EXISTS overall_confidence")
    op.execute("ALTER TABLE wolfpack.cases DROP COLUMN IF EXISTS verdict_decision")
