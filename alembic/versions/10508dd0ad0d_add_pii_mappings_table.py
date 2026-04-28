"""add_pii_mappings_table

Revision ID: 10508dd0ad0d
Revises: ece0843deee4
Create Date: 2026-04-27 22:30:53.669067

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "10508dd0ad0d"
down_revision: str | Sequence[str] | None = "ece0843deee4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "pii_mappings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("original_value", sa.Text(), nullable=False),
        sa.Column("identifier_type", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["case_id"], ["wolfpack.cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="wolfpack",
    )
    op.create_index(
        "ix_pii_mappings_case_id", "pii_mappings", ["case_id"], schema="wolfpack"
    )
    op.create_index(
        "ix_pii_mappings_token", "pii_mappings", ["token"], schema="wolfpack"
    )
    op.create_index(
        "ix_pii_mappings_case_token",
        "pii_mappings",
        ["case_id", "token"],
        unique=True,
        schema="wolfpack",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_pii_mappings_case_token", table_name="pii_mappings", schema="wolfpack")
    op.drop_index("ix_pii_mappings_token", table_name="pii_mappings", schema="wolfpack")
    op.drop_index("ix_pii_mappings_case_id", table_name="pii_mappings", schema="wolfpack")
    op.drop_table("pii_mappings", schema="wolfpack")
