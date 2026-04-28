"""phase1_ledger_hash_chain

Revision ID: 3008912527ab
Revises: ece0843deee4
Create Date: 2026-04-27 17:35:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3008912527ab'
down_revision: str | Sequence[str] | None = 'ece0843deee4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Trigger function: compute content_hash and link prev_hash on insert.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wolfpack.compute_ledger_hash()
        RETURNS TRIGGER AS $$
        DECLARE
            prev_content_hash TEXT;
            lock_key BIGINT;
        BEGIN
            -- Serialize inserts per case_id to prevent forked chains.
            lock_key := hashtextextended('wolfpack.ledger.' || NEW.case_id::text, 0);
            PERFORM pg_advisory_xact_lock(lock_key);

            -- Look up previous entry for the same case and lock it.
            SELECT content_hash INTO prev_content_hash
            FROM wolfpack.evidence_ledger
            WHERE case_id = NEW.case_id
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE;

            NEW.prev_hash := prev_content_hash;

            -- Compute deterministic SHA-256 over canonical JSON.
            NEW.content_hash := encode(
                digest(
                    jsonb_build_object(
                        'entry_type', NEW.entry_type,
                        'case_id', NEW.case_id,
                        'branch_id', NEW.branch_id,
                        'schema_version', NEW.schema_version,
                        'agent_run_id', NEW.agent_run_id,
                        'content', NEW.content
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

    # SQL function: verify integrity of a case's ledger chain.
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
                    prev_hash
                FROM wolfpack.evidence_ledger
                WHERE case_id = p_case_id
                ORDER BY id ASC
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
                            'content', rec.content
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
        "DROP TRIGGER IF EXISTS evidence_ledger_hash_trigger "
        "ON wolfpack.evidence_ledger"
    )
    op.execute("DROP FUNCTION IF EXISTS wolfpack.compute_ledger_hash()")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
