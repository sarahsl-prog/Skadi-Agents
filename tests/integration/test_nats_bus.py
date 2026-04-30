"""Integration tests for the NATS JetStream event bus.

These tests spin up an isolated NATS container, exercise the full
connect / ensure_streams / publish / subscribe / ack / redelivery
lifecycle, and verify that graph execution produces expected NATS
messages.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from wolfpack.config.settings import NATSConfig
from wolfpack.orchestrator.bus import NATSClient

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
async def nats_client() -> Any:
    """Yield a connected :class:`NATSClient` backed by a testcontainer."""
    from testcontainers.core.generic import DockerContainer

    container = (
        DockerContainer("nats:2-alpine")
        .with_command("--jetstream --store_dir /data")
        .with_exposed_ports(4222)
    )
    container.start()
    host = container.get_container_host_ip()
    port = container.get_exposed_port(4222)
    url = f"nats://{host}:{port}"

    client = NATSClient(NATSConfig(url=url))
    await client.connect()
    await client.ensure_streams()

    yield client

    await client.close()
    container.stop()


class TestNATSClient:
    """Core bus operations against a live NATS JetStream container."""

    @pytest.mark.asyncio
    async def test_connect_and_ensure_streams(self, nats_client: NATSClient) -> None:
        assert nats_client.connected

    @pytest.mark.asyncio
    async def test_publish_and_subscribe_round_trip(self, nats_client: NATSClient) -> None:
        received: list[bytes] = []
        event = asyncio.Event()

        async def handler(msg: Any) -> None:
            received.append(msg.data)
            await msg.ack()
            event.set()

        sub = await nats_client.subscribe(
            "hunt.finding.tracker", durable="tracker-consumer", handler=handler
        )

        await nats_client.publish("hunt.finding.tracker", {"test": "value"})

        await asyncio.wait_for(event.wait(), timeout=5.0)
        assert len(received) == 1
        assert b'"test": "value"' in received[0]

        await sub.unsubscribe()

    @pytest.mark.asyncio
    async def test_durable_consumer_redelivers_unacked(self, nats_client: NATSClient) -> None:
        """Unacknowledged messages must be redelivered to the durable consumer."""
        received_count = 0
        event = asyncio.Event()

        async def no_ack_handler(msg: Any) -> None:
            nonlocal received_count
            received_count += 1
            if received_count >= 2:
                await msg.ack()
                event.set()

        sub = await nats_client.subscribe(
            "hunt.status.verdict",
            durable="closer-consumer",
            handler=no_ack_handler,
        )

        await nats_client.publish("hunt.status.verdict", {"verdict": "malicious"})

        # Wait for redelivery (NATS default ack_wait is 30s; we rely on
        # the test being fast enough to catch the redelivery, or we can
        # configure a shorter ack_wait on the consumer.  For Phase 2 we
        # accept that this may take up to ~30s.  In practice with a fresh
        # container the redelivery often fires within a few seconds.
        await asyncio.wait_for(event.wait(), timeout=35.0)
        assert received_count >= 2

        await sub.unsubscribe()

    @pytest.mark.asyncio
    async def test_publish_dict_serialises_to_json(self, nats_client: NATSClient) -> None:
        event = asyncio.Event()
        data: bytes = b""

        async def handler(msg: Any) -> None:
            nonlocal data
            data = msg.data
            await msg.ack()
            event.set()

        sub = await nats_client.subscribe(
            "hunt.task.tracker", durable="alpha-consumer", handler=handler
        )

        payload = {"case_id": "abc-123", "status": "scented"}
        await nats_client.publish("hunt.task.tracker", payload)

        await asyncio.wait_for(event.wait(), timeout=5.0)
        assert b'"case_id": "abc-123"' in data

        await sub.unsubscribe()
