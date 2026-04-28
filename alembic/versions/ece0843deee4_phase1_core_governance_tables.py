"""phase1_core_governance_tables

Revision ID: ece0843deee4
Revises:
Create Date: 2026-04-27 09:30:16.239467

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ece0843deee4'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create application schema
    op.execute("CREATE SCHEMA IF NOT EXISTS wolfpack")

    # --- Core case-state tables ---
    op.create_table(
        'cases',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('seed', postgresql.JSONB(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='new'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id'),
        schema='wolfpack',
    )

    op.create_table(
        'branches',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('parent_branch_id', sa.UUID(), nullable=True),
        sa.Column('hypothesis', postgresql.JSONB(), nullable=False),
        sa.Column('depth', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(), nullable=False, server_default='open'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['case_id'], ['wolfpack.cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_branch_id'], ['wolfpack.branches.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        schema='wolfpack',
    )
    op.create_index('ix_branches_case_id', 'branches', ['case_id'], schema='wolfpack')

    op.create_table(
        'hypotheses',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('branch_id', sa.UUID(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['branch_id'], ['wolfpack.branches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='wolfpack',
    )
    op.create_index('ix_hypotheses_branch_id', 'hypotheses', ['branch_id'], schema='wolfpack')

    op.create_table(
        'pivots',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('branch_id', sa.UUID(), nullable=False),
        sa.Column('from_entity', postgresql.JSONB(), nullable=False),
        sa.Column('to_entity', postgresql.JSONB(), nullable=False),
        sa.Column('pivot_type', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['branch_id'], ['wolfpack.branches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='wolfpack',
    )
    op.create_index('ix_pivots_branch_id', 'pivots', ['branch_id'], schema='wolfpack')

    # --- Evidence ledger ---
    op.create_table(
        'evidence_ledger',
        sa.Column('id', sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('branch_id', sa.UUID(), nullable=True),
        sa.Column('entry_type', sa.String(), nullable=False),
        sa.Column('content', postgresql.JSONB(), nullable=False),
        sa.Column('prev_hash', sa.String(), nullable=True),
        sa.Column('content_hash', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('agent_run_id', sa.String(), nullable=True),
        sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1'),
        sa.ForeignKeyConstraint(['case_id'], ['wolfpack.cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['branch_id'], ['wolfpack.branches.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'id', name='uq_evidence_ledger_case_entry'),
        schema='wolfpack',
    )
    op.create_index('ix_evidence_ledger_case_id', 'evidence_ledger', ['case_id'], schema='wolfpack')

    # --- Governance tables ---
    op.create_table(
        'learning_queue',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('verdict', sa.String(), nullable=True),
        sa.Column('approved_by', sa.String(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['wolfpack.cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='wolfpack',
    )

    op.create_table(
        'retention_policy',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('policy_key', sa.String(), nullable=False, unique=True),
        sa.Column('policy_value', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        schema='wolfpack',
    )

    op.create_table(
        'crypto_shred_keys',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('wrapped_dek', sa.LargeBinary(), nullable=False),
        sa.Column('kek_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('shredded_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['wolfpack.cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='wolfpack',
    )

    op.create_table(
        'pii_salts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('salt', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['case_id'], ['wolfpack.cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='wolfpack',
    )

    op.create_table(
        'breakglass_audit',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('analyst_id', sa.String(), nullable=False),
        sa.Column('field_accessed', sa.String(), nullable=False),
        sa.Column('accessed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['case_id'], ['wolfpack.cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='wolfpack',
    )

    # --- Seed default retention policy ---
    op.execute(
        """
        INSERT INTO wolfpack.retention_policy (id, policy_key, policy_value)
        VALUES (gen_random_uuid(), 'default_retention_days', '365')
        ON CONFLICT (policy_key) DO NOTHING
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('breakglass_audit', schema='wolfpack')
    op.drop_table('pii_salts', schema='wolfpack')
    op.drop_table('crypto_shred_keys', schema='wolfpack')
    op.drop_table('retention_policy', schema='wolfpack')
    op.drop_table('learning_queue', schema='wolfpack')
    op.drop_table('evidence_ledger', schema='wolfpack')
    op.drop_table('pivots', schema='wolfpack')
    op.drop_table('hypotheses', schema='wolfpack')
    op.drop_table('branches', schema='wolfpack')
    op.drop_table('cases', schema='wolfpack')
    op.execute("DROP SCHEMA IF EXISTS wolfpack CASCADE")
