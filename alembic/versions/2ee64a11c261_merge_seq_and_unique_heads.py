"""merge_seq_and_unique_heads

Revision ID: 2ee64a11c261
Revises: 299dd15933ab, 5b8c7d2e1f3a
Create Date: 2026-04-28 03:00:00.000000

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "2ee64a11c261"
down_revision: str | Sequence[str] | None = ("299dd15933ab", "5b8c7d2e1f3a")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
