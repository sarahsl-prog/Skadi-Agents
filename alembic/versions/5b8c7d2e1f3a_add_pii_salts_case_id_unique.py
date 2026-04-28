"""add_pii_salts_case_id_unique

Revision ID: 5b8c7d2e1f3a
Revises: 3c1346d808bb
Create Date: 2026-04-28 03:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b8c7d2e1f3a"
down_revision: str | Sequence[str] | None = "3c1346d808bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        "uq_pii_salts_case_id",
        "pii_salts",
        ["case_id"],
        schema="wolfpack",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_pii_salts_case_id",
        "pii_salts",
        schema="wolfpack",
        type_="unique",
    )
