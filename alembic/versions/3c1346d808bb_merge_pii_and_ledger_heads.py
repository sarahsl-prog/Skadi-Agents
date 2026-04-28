"""merge_pii_and_ledger_heads

Revision ID: 3c1346d808bb
Revises: 10508dd0ad0d, 3008912527ab
Create Date: 2026-04-28 02:55:04.659008

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "3c1346d808bb"
down_revision: str | Sequence[str] | None = ("10508dd0ad0d", "3008912527ab")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
