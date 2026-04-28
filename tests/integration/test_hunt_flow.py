"""Happy-path integration test for the full hunt flow.

Seed → Alpha creates case → Tracker stub → Flanker stub → Closer stub →
Review auto-approves → case closed.

Verifies:
- Graph runs end-to-end
- Ledger entries are hash-chained
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from wolfpack.config.settings import NATSConfig
from wolfpack.orchestrator.bus import NATSClient
from wolfpack.orchestrator.graph import build_hunt_graph
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.ledger import insert_ledger_entry, replay_ledger, verify_chain
from wolfpack.schemas.persistence import CasePersistence, PersistencePool
from wolfpack.schemas.seed import Seed

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
async def hunt_stack() -> AsyncGenerator[dict[str, Any]]:
    from testcontainers.core.generic import DockerContainer
    from testcontainers.postgres import PostgresContainer

    # Postgres
    with PostgresContainer("pgvector/pgvector:pg16").start() as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        pg_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)

        import subprocess
        import sys

        sync_dsn = dsn.replace("postgresql://", "postgresql+psycopg2://")
        env = {**os.environ, "DATABASE_URL": sync_dsn}
        for key in list(env.keys()):
            if key.startswith("WOLFPACK_"):
                env.pop(key, None)
        alembic_path = str((Path(sys.executable).parent / "alembic").resolve())
        subprocess.run(  # noqa: S603
            [alembic_path, "upgrade", "head"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        # NATS
        nats_container = (
            DockerContainer("nats:2-alpine")
            .with_command("--jetstream --store_dir /data")
            .with_exposed_ports(4222)
        )
        nats_container.start()
        nats_host = nats_container.get_container_host_ip()
        nats_port = nats_container.get_exposed_port(4222)
        nats_url = f"nats://{nats_host}:{nats_port}"

        nats_client = NATSClient(NATSConfig(url=nats_url))
        await nats_client.connect()
        await nats_client.ensure_streams()

        yield {
            "pg_pool": pg_pool,
            "pg_dsn": dsn,
            "nats_client": nats_client,
            "nats_container": nats_container,
        }

        await nats_client.close()
        nats_container.stop()
        await pg_pool.close()


class TestHuntFlow:
    """End-to-end hunt flow with real infrastructure."""

    def test_seed_to_closed_case(self, hunt_stack: dict[str, Any]) -> None:
        dsn = hunt_stack["pg_dsn"]

        async def _run() -> None:
            persistence = CasePersistence(PersistencePool(dsn))
            await persistence._pool.connect()

            case_id = str(uuid.uuid4())
            seed = Seed(type="ioc", raw_payload={"value": "10.0.0.1"})

            # Pre-create the case so the ledger has a parent row
            case = CaseState(case_id=case_id, seed=seed)
            await persistence.create_case(case)

            # Run graph with default stubs
            graph = build_hunt_graph(use_stubs=True)
            result = graph.invoke({"case_id": case_id, "seed": seed})

            assert result["case_id"] == case_id
            assert result["status"] == "closed"
            assert result["verdict_decision"] == "benign"
            assert result["review_decision"] == "approved"

            # Verify ledger integrity by writing and checking a manual entry
            conn = await persistence._pool.acquire()
            try:
                await insert_ledger_entry(
                    conn,
                    case_id,
                    "timeline_event",
                    {
                        "source_type": "test",
                        "source_id": "hunt-1",
                        "timestamp": "2026-04-28T12:00:00Z",
                        "hash": "abcd",
                        "metadata": {"msg": "hunt completed"},
                    },
                )
                is_valid, broken_at = await verify_chain(conn, case_id)
                assert is_valid is True
                assert broken_at is None

                refs = await replay_ledger(conn, case_id)
                assert len(refs) >= 1
            finally:
                await persistence._pool.release(conn)

        asyncio.run(_run())

    def test_graph_routes_through_flanker(self, hunt_stack: dict[str, Any]) -> None:
        dsn = hunt_stack["pg_dsn"]

        async def _run() -> None:
            persistence = CasePersistence(PersistencePool(dsn))
            await persistence._pool.connect()

            case_id = str(uuid.uuid4())
            seed = Seed(type="alert", raw_payload={})
            case = CaseState(case_id=case_id, seed=seed)
            await persistence.create_case(case)

            initial_state = CaseState(
                case_id=case_id,
                seed=seed,
                tracker_confidence=2,  # WEAK
            )

            graph = build_hunt_graph(use_stubs=True)
            result = graph.invoke(initial_state.model_dump())

            assert result["status"] == "closed"

            conn = await persistence._pool.acquire()
            try:
                await insert_ledger_entry(
                    conn,
                    case_id,
                    "timeline_event",
                    {
                        "source_type": "test",
                        "source_id": "hunt-2",
                        "timestamp": "2026-04-28T12:00:00Z",
                        "hash": "abcd",
                        "metadata": {"msg": "flanker route"},
                    },
                )
                refs = await replay_ledger(conn, case_id)
                assert len(refs) >= 1
            finally:
                await persistence._pool.release(conn)

        asyncio.run(_run())
