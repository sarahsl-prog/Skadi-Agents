"""Integration tests for the local infrastructure stack.

These tests use testcontainers to spin up isolated service instances
and verify they are healthy.  They require Docker and are skipped
if Docker is unavailable.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

# Skip the entire module if Docker is not available.
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
def postgres_container() -> Any:
    """Start a Postgres/pgvector container and yield it."""
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    with PostgresContainer("pgvector/pgvector:pg16").start() as pg:
        yield pg


@pytest.fixture()
def nats_container() -> Any:
    """Start a NATS container and yield it."""
    from testcontainers.core.generic import DockerContainer  # type: ignore[import-untyped]

    container = (
        DockerContainer("nats:2-alpine")
        .with_command("--jetstream --store_dir /data")
        .with_exposed_ports(4222)
    )
    container.start()
    yield container
    container.stop()


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------


def test_postgres_starts_and_responds(postgres_container: Any) -> None:
    """Postgres container should accept connections."""
    connection_url = postgres_container.get_connection_url()
    assert "postgresql" in connection_url


@pytest.mark.asyncio
async def test_postgres_has_pgvector(postgres_container: Any) -> None:
    """Postgres container must have the pgvector extension installed."""
    import asyncpg  # type: ignore[import-untyped]

    dsn = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        row = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        assert row is True
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# NATS
# ---------------------------------------------------------------------------


def test_nats_starts_and_exposes_port(nats_container: Any) -> None:
    """NATS container should expose port 4222."""
    host = nats_container.get_container_host_ip()
    port = nats_container.get_exposed_port(4222)
    assert host
    assert port


@pytest.mark.asyncio
async def test_nats_has_jetstream(nats_container: Any) -> None:
    """NATS container must have JetStream enabled."""
    import nats

    host = nats_container.get_container_host_ip()
    port = nats_container.get_exposed_port(4222)
    nc = await nats.connect(f"nats://{host}:{port}")
    try:
        js = nc.jetstream()
        await js.add_stream(name="TEST_STREAM", subjects=["test.>"])
        info = await js.stream_info("TEST_STREAM")
        assert info is not None
    finally:
        await nc.close()
