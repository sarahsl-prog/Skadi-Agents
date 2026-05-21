"""merge heads for branch_budget

Revision ID: 56bfceb4d1ac
Revises: c2d8e3b4f5a6, 2ee64a11c261
Create Date: 2026-05-08 10:14:27.946215

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '56bfceb4d1ac'
down_revision: Union[str, Sequence[str], None] = ('c2d8e3b4f5a6', '2ee64a11c261')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
