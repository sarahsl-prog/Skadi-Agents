"""add branch_budget table

Revision ID: 62ce519b2603
Revises: 56bfceb4d1ac
Create Date: 2026-05-08 10:15:03.030868

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62ce519b2603'
down_revision: Union[str, Sequence[str], None] = '56bfceb4d1ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'branch_budget',
        sa.Column('case_id', sa.Text(), nullable=False),
        sa.Column('branch_count', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('case_id'),
        schema='wolfpack',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('branch_budget', schema='wolfpack')
