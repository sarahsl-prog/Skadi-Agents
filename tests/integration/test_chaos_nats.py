"""Chaos tests for NATS failure recovery.

Validates that the event bus is fan-out (not state store) and that
cases can resume after a NATS outage.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from wolfpack.config.settings import NATSConfig
from wolfpack.orchestrator.bus import NATSClient

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
async def nats_setup() -> AsyncGenerator[dict[str, Any]]:
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

    yield {"client": client, "container": container, "url": url}

    await client.close()
    container.stop()


class TestNATSFailureRecovery:
    """NATS container kill/restart scenarios."""

    @pytest.mark.asyncio
    async def test_publish_resumes_after_restart(self, nats_setup: dict[str, Any]) -> None:
        client = nats_setup["client"]
        container = nats_setup["container"]

        # Publish before failure
        ack = await client.publish("hunt.task.tracker", {"seq": 1})
        assert ack is not None

        # Kill NATS
        container.stop()

        # Publish should raise because connection is dead
        publish_failed = False
        try:
            await client.publish("hunt.task.tracker", {"seq": 2})
        except Exception:
            publish_failed = True
        assert publish_failed

        # Restart NATS on the same ports
        container.start()
        host = container.get_container_host_ip()
        port = container.get_exposed_port(4222)
        new_url = f"nats://{host}:{port}"

        # Create fresh client
        new_client = NATSClient(NATSConfig(url=new_url))
        await new_client.connect()
        await new_client.ensure_streams()

        # Publish after recovery
        ack2 = await new_client.publish("hunt.task.tracker", {"seq": 3})
        assert ack2 is not None

        await new_client.close()

    @pytest.mark.asyncio
    async def test_durable_consumer_survives_restart(self, nats_setup: dict[str, Any]) -> None:
        client = nats_setup["client"]
        container = nats_setup["container"]

        received: list[bytes] = []
        event = asyncio.Event()

        async def handler(msg: Any) -> None:
            received.append(msg.data)
            await msg.ack()
            if len(received) >= 2:
                event.set()

        await client.subscribe(
            "hunt.finding.tracker",
            durable="tracker-chaos-consumer",
            handler=handler,
        )

        # Publish two messages before restart
        await client.publish("hunt.finding.tracker", {"seq": 1})
        await client.publish("hunt.finding.tracker", {"seq": 2})

        # Wait for delivery
        await asyncio.wait_for(event.wait(), timeout=5.0)
        assert len(received) == 2

        # Kill and restart
        container.stop()
        container.start()
        host = container.get_container_host_ip()
        port = container.get_exposed_port(4222)
        new_url = f"nats://{host}:{port}"

        new_client = NATSClient(NATSConfig(url=new_url))
        await new_client.connect()
        await new_client.ensure_streams()

        # Publish a third message after recovery
        event.clear()
        received.clear()

        async def handler2(msg: Any) -> None:
            received.append(msg.data)
            await msg.ack()
            event.set()

        sub2 = await new_client.subscribe(
            "hunt.finding.tracker",
            durable="tracker-chaos-consumer",
            handler=handler2,
        )

        await new_client.publish("hunt.finding.tracker", {"seq": 3})
        await asyncio.wait_for(event.wait(), timeout=5.0)
        assert len(received) >= 1

        await sub2.unsubscribe()
        await new_client.close()
