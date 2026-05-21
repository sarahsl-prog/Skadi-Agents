"""Learning queue processor.

Moves approved analyst decisions into the case-history knowledge base.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from wolfpack.eval.replay import ReplayHarness

_LOGGER = logging.getLogger(__name__)
from wolfpack.learning.summary import format_case_summary
from wolfpack.rag.case_history import CaseHistoryPipeline
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.persistence import CasePersistence


class LearningQueueWorker:
    """Processes approved learning-queue entries and ingests case summaries.

    Attributes:
        pool: asyncpg connection pool for Postgres.
        pipeline: case-history RAG pipeline (Haystack / pgvector).
        persistence: higher-level persistence helper.
        schedule_minutes: how often to run polling loop.
        batch_size: max entries processed per tick.
        retry_limit: max retry attempts before permanently failing.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        pipeline: CaseHistoryPipeline | None = None,
        persistence: CasePersistence | None = None,
        schedule_minutes: int = 5,
        batch_size: int = 50,
        retry_limit: int = 3,
    ) -> None:
        self._pool = pool
        self._pipeline = pipeline
        self._persistence = persistence
        self.schedule_minutes = schedule_minutes
        self.batch_size = batch_size
        self.retry_limit = retry_limit

    # ------------------------------------------------------------------ #
    # Configuration helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def from_pool(
        cls,
        pool: asyncpg.Pool,
        pipeline: CaseHistoryPipeline | None = None,
        schedule_minutes: int = 5,
        batch_size: int = 50,
    ) -> LearningQueueWorker:
        """Build a worker from a raw connection pool.

        The provided *pool* is used directly; no separate persistence pool
        is created since the worker shares the caller's pool.
        """
        from wolfpack.schemas.persistence import CasePersistence

        persistence = CasePersistence(pool=pool)
        return cls(
            pool=pool,
            pipeline=pipeline,
            persistence=persistence,
            schedule_minutes=schedule_minutes,
            batch_size=batch_size,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def process_batch(self) -> None:
        """Fetch approved but uningested entries, process them, ingest."""
        entries = await self._fetch_entries()
        for entry in entries:
            try:
                await self._process_entry(entry)
            except Exception as exc:
                await self._handle_failure(entry["id"], exc)

    async def run_tick(self) -> None:
        """Single scheduling tick: acquire connection and process batch."""
        if self._pipeline is not None:
            await self._pipeline.ensure_schema()
        await self.process_batch()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _fetch_entries(self) -> list[asyncpg.Record | dict[str, Any]]:
        """Return approved entries where ingested_at IS NULL."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, case_id, retry_count
                FROM wolfpack.learning_queue
                WHERE approved_by IS NOT NULL
                  AND ingested_at IS NULL
                  AND (retry_count IS NULL OR retry_count < $1)
                ORDER BY approved_at ASC
                LIMIT $2
                """,
                self.retry_limit,
                self.batch_size,
            )
        return list(rows)

    async def _process_entry(self, entry: asyncpg.Record | dict[str, Any]) -> None:
        case_id = str(entry["case_id"])

        # 1. Fetch full case state
        case_state = await self._get_full_case_state(case_id)
        if case_state is None:
            raise RuntimeError(f"Case state missing for {case_id}")

        # 2. Reconstruct verdict packet from case state fields
        from wolfpack.schemas.verdict import VerdictPacket

        verdict = VerdictPacket(
            decision=(
                case_state.verdict_decision if case_state.verdict_decision else "INCONCLUSIVE"
            ),
            confidence=(
                case_state.overall_confidence
                if case_state.overall_confidence
                else Confidence.COINCIDENCE
            ),
        )

        # 3. Quality gate: need plausible or above (soft fail → skip)
        min_confidence = Confidence.PLAUSIBLE
        if verdict.confidence < min_confidence:
            _LOGGER.warning(
                "Skipping case %s: confidence %s < %s",
                case_id,
                verdict.confidence,
                min_confidence,
            )
            await self._set_failure_status(str(entry["id"]), "low_confidence")
            return

        # 4. Format summary — pseudonymise entities with the per-case salt
        # (same salt used by the live PII pipeline) instead of a hardcoded one.
        from wolfpack.schemas.pii import get_pii_salt

        salt_bytes = await get_pii_salt(self._pool, case_id)
        salt = salt_bytes.hex() if salt_bytes is not None else None
        summary = format_case_summary(case_state, verdict=verdict, salt=salt)

        # 5. Ingest into case-history
        if self._pipeline is not None:
            await self._pipeline.ingest_case_summary(summary)

        # 6. Mark as ingested
        await self._mark_ingested(str(entry["id"]))

    async def _mark_ingested(self, entry_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE wolfpack.learning_queue
                SET ingested_at = NOW(),
                    retry_count = COALESCE(retry_count, 0)
                WHERE id = $1
                """,
                entry_id,
            )

    async def _set_failure_status(self, entry_id: str, reason: str) -> None:
        """Mark entry as permanently failed (no more retries)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE wolfpack.learning_queue
                SET last_error = $2,
                    ingested_at = NOW()
                WHERE id = $1
                """,
                entry_id,
                reason,
            )

    async def _handle_failure(self, entry_id: str, exc: Exception) -> None:
        """Increment retry count for the entry."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE wolfpack.learning_queue
                SET retry_count = COALESCE(retry_count, 0) + 1,
                    last_error = $2
                WHERE id = $1
                """,
                entry_id,
                str(exc)[:500],
            )

    # ------------------------------------------------------------------ #
    # Full case state reconstruction
    # ------------------------------------------------------------------ #

    async def _get_full_case_state(self, case_id: str) -> Any | None:
        """Fetch case + branches/hypotheses/evidence and reconstruct CaseState."""
        from wolfpack.schemas.case_state import BranchState, CaseState
        from wolfpack.schemas.evidence import EvidenceRef
        from wolfpack.schemas.hypothesis import Hypothesis
        from wolfpack.schemas.seed import Seed

        async with self._pool.acquire() as conn:
            case_row = await conn.fetchrow(
                "SELECT id, seed, status, version, created_at, updated_at,"
                " verdict_decision, overall_confidence "
                "FROM wolfpack.cases WHERE id = $1",
                case_id,
            )
            if case_row is None:
                return None

            seed_data = case_row["seed"]
            if isinstance(seed_data, str):
                import json

                seed_data = json.loads(seed_data)

            case = CaseState(
                case_id=str(case_row["id"]),
                seed=Seed.model_validate(seed_data),
                status=case_row["status"],
                version=case_row["version"],
                created_at=case_row["created_at"],
                updated_at=case_row["updated_at"],
                verdict_decision=case_row.get("verdict_decision"),
                overall_confidence=case_row.get("overall_confidence"),
            )

            # Branches with nested hypotheses and evidence
            branch_rows = await conn.fetch(
                "SELECT id, case_id, parent_branch_id, hypothesis,"
                " depth, status, version, created_at "
                "FROM wolfpack.branches WHERE case_id = $1",
                case_id,
            )
            for row in branch_rows:
                hyp_data = row["hypothesis"]
                if isinstance(hyp_data, str):
                    hyp_data = json.loads(hyp_data)
                from wolfpack.schemas.branch import BranchSpec

                spec = BranchSpec.model_validate(hyp_data)
                branch = BranchState(
                    branch_id=str(row["id"]),
                    case_id=str(row["case_id"]),
                    parent_branch_id=(
                        str(row["parent_branch_id"]) if row["parent_branch_id"] else None
                    ),
                    spec=spec,
                    status=row["status"],
                    version=row["version"],
                    created_at=row["created_at"],
                )
                # Hypotheses for branch
                hyp_rows = await conn.fetch(
                    "SELECT description, confidence, status"
                    " FROM wolfpack.hypotheses WHERE branch_id = $1",
                    branch.branch_id,
                )
                for h in hyp_rows:
                    branch.hypotheses.append(
                        Hypothesis(
                            description=h["description"],
                            confidence=Confidence(int(h["confidence"])),
                            status=h["status"],
                        )
                    )
                # Evidence refs for branch
                ev_rows = await conn.fetch(
                    "SELECT case_id, branch_id, entry_type, content,"
                    " created_at, agent_run_id"
                    " FROM wolfpack.evidence_ledger"
                    " WHERE case_id = $1 AND branch_id = $2",
                    case_id,
                    branch.branch_id,
                )
                for e in ev_rows:
                    content = e["content"]
                    if isinstance(content, str):
                        content = json.loads(content)
                    ref = EvidenceRef.model_validate(content)
                    branch.evidence_refs.append(ref)
                    # Aggregate every branch evidence ref up to the case level
                    # so format_case_summary sees the full set.
                    case.evidence_refs.append(ref)
                case.branches.append(branch)

            return case

    async def run_eval_replay(
        self,
        golden_sets_dir: str | None = None,
    ) -> dict[str, Any]:
        """Run replay harness evaluating case-history retrieval quality."""
        replay = ReplayHarness(
            pipeline=self._pipeline,
            golden_sets_dir=golden_sets_dir,
        )
        return await replay.run_all()
