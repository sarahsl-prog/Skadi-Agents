"""Add seq column to evidence_ledger for ordered chain

Revision ID: 299dd15933ab
Revises: 3c1346d808bb
Create Date: 2026-04-28 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "299dd15933ab"
down_revision: str | Sequence[str] | None = "3c1346d808bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add sequence column for chain ordering independent of id
    op.execute(
        "ALTER TABLE wolfpack.evidence_ledger ADD COLUMN IF NOT EXISTS seq BIGINT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_evidence_ledger_case_seq "
        "ON wolfpack.evidence_ledger (case_id, seq)"
    )

    # Drop existing trigger and function
    op.execute(
        "DROP TRIGGER IF EXISTS evidence_ledger_hash_trigger ON wolfpack.evidence_ledger"
    )
    op.execute("DROP FUNCTION IF EXISTS wolfpack.compute_ledger_hash()")
    op.execute("DROP FUNCTION IF EXISTS wolfpack.verify_chain(UUID)")

    # Recreate trigger with seq computation
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wolfpack.compute_ledger_hash()
        RETURNS TRIGGER AS $$
        DECLARE
            prev_content_hash TEXT;
            lock_key BIGINT;
        BEGIN
            -- Serialize inserts per case_id
            lock_key := hashtextextended('wolfpack.ledger.' || NEW.case_id::text, 0);
            PERFORM pg_advisory_xact_lock(lock_key);

            -- Compute next sequence number for this case
            SELECT COALESCE(MAX(seq), 0) + 1 INTO NEW.seq
            FROM wolfpack.evidence_ledger
            WHERE case_id = NEW.case_id;

            -- Look up previous entry by sequence
            SELECT content_hash INTO prev_content_hash
            FROM wolfpack.evidence_ledger
            WHERE case_id = NEW.case_id AND seq = NEW.seq - 1;

            NEW.prev_hash := prev_content_hash;

            -- Compute deterministic SHA-256 over canonical JSON
            NEW.content_hash := encode(
                digest(
                    jsonb_build_object(
                        'entry_type', NEW.entry_type,
                        'case_id', NEW.case_id,
                        'branch_id', NEW.branch_id,
                        'schema_version', NEW.schema_version,
                        'agent_run_id', NEW.agent_run_id,
                        'content', NEW.content,
                        'seq', NEW.seq
                    )::text,
                    'sha256'
                ),
                'hex'
            );

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.execute(
        """
        CREATE TRIGGER evidence_ledger_hash_trigger
        BEFORE INSERT ON wolfpack.evidence_ledger
        FOR EACH ROW
        EXECUTE FUNCTION wolfpack.compute_ledger_hash()
        """
    )

    # Recreate verify_chain using seq ordering
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wolfpack.verify_chain(p_case_id UUID)
        RETURNS TABLE(is_valid BOOLEAN, broken_at BIGINT) AS $$
        DECLARE
            rec RECORD;
            expected_prev_hash TEXT := NULL;
            computed_hash TEXT;
            found_any BOOLEAN := FALSE;
        BEGIN
            FOR rec IN
                SELECT
                    id,
                    entry_type,
                    case_id,
                    branch_id,
                    schema_version,
                    agent_run_id,
                    content,
                    content_hash,
                    prev_hash,
                    seq
                FROM wolfpack.evidence_ledger
                WHERE case_id = p_case_id
                ORDER BY seq ASC
            LOOP
                found_any := TRUE;

                computed_hash := encode(
                    digest(
                        jsonb_build_object(
                            'entry_type', rec.entry_type,
                            'case_id', rec.case_id,
                            'branch_id', rec.branch_id,
                            'schema_version', rec.schema_version,
                            'agent_run_id', rec.agent_run_id,
                            'content', rec.content,
                            'seq', rec.seq
                        )::text,
                        'sha256'
                    ),
                    'hex'
                );

                IF computed_hash != rec.content_hash THEN
                    is_valid := FALSE;
                    broken_at := rec.id;
                    RETURN NEXT;
                    RETURN;
                END IF;

                IF rec.prev_hash IS DISTINCT FROM expected_prev_hash THEN
                    is_valid := FALSE;
                    broken_at := rec.id;
                    RETURN NEXT;
                    RETURN;
                END IF;

                expected_prev_hash := rec.content_hash;
            END LOOP;

            is_valid := TRUE;
            broken_at := NULL;
            RETURN NEXT;
            RETURN;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP FUNCTION IF EXISTS wolfpack.verify_chain(UUID)")
    op.execute(
        "DROP TRIGGER IF EXISTS evidence_ledger_hash_trigger ON wolfpack.evidence_ledger"
    )
    op.execute("DROP FUNCTION IF EXISTS wolfpack.compute_ledger_hash()")
    op.execute(
        "DROP INDEX IF EXISTS wolfpack.ix_evidence_ledger_case_seq"
    )
    op.execute(
        "ALTER TABLE wolfpack.evidence_ledger DROP COLUMN IF EXISTS seq"
    )
