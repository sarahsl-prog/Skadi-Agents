"""NATS JetStream client wrapper for inter-agent messaging.

The :class:`NATSClient` manages connection lifecycle, stream creation,
publish with ack confirmation, and durable consumer subscription with
manual ack/redelivery.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import nats
from nats.aio.msg import Msg
from nats.js.api import ConsumerConfig

from wolfpack.config.settings import NATSConfig


class NATSClient:
    """Async NATS JetStream client for WolfPack event bus."""

    def __init__(self, settings: NATSConfig) -> None:
        self._url = settings.url
        self._nc: Any = None
        self._js: Any = None

    @property
    def connected(self) -> bool:
        """Return ``True`` if the underlying NATS connection is active."""
        return self._nc is not None and self._nc.is_connected

    async def connect(self) -> None:
        """Open NATS connection and initialise JetStream context."""
        self._nc = await nats.connect(self._url)
        self._js = self._nc.jetstream()

    async def ensure_streams(self) -> None:
        """Create JetStream streams if they do not already exist.

        Streams created:
        - ``hunt_tasks``    → ``hunt.task.*``
        - ``hunt_findings`` → ``hunt.finding.*``
        - ``hunt_branches`` → ``hunt.branch.*``
        - ``hunt_status``   → ``hunt.status.*``
        """
        if self._js is None:
            raise RuntimeError("NATSClient not connected - call connect() first")

        streams = [
            ("hunt_tasks", ["hunt.task.*"]),
            ("hunt_findings", ["hunt.finding.*"]),
            ("hunt_branches", ["hunt.branch.*"]),
            ("hunt_status", ["hunt.status.*"]),
        ]
        for name, subjects in streams:
            try:
                await self._js.add_stream(name=name, subjects=subjects)
            except nats.js.errors.BadRequestError:
                # Stream likely already exists; idempotent.
                pass

    async def publish(
        self, subject: str, payload: bytes | str | dict[str, Any]
    ) -> Any:
        """Publish a message to *subject* and return the server ack.

        Args:
            subject: NATS subject (e.g. ``hunt.finding.tracker``).
            payload: Message body - bytes, string, or dict (JSON-encoded).

        Raises:
            RuntimeError: If the client is not connected.
        """
        if self._js is None:
            raise RuntimeError("NATSClient not connected - call connect() first")

        if isinstance(payload, dict):
            payload = json.dumps(payload).encode()
        elif isinstance(payload, str):
            payload = payload.encode()
        return await self._js.publish(subject, payload)

    async def subscribe(
        self,
        subject: str,
        durable: str,
        handler: Callable[[Msg], Any],
        *,
        max_ack_pending: int = 10,
    ) -> Any:
        """Create a durable consumer on *subject*.

        The consumer uses manual ack so that unacknowledged messages are
        redelivered.  ``max_ack_pending`` provides back-pressure.

        Args:
            subject: NATS subject to subscribe to.
            durable: Durable consumer name (e.g. ``tracker-consumer``).
            handler: Callback invoked for each message.  Must call
                ``msg.ack()`` when processing succeeds.
            max_ack_pending: Maximum unacknowledged messages allowed.
        """
        if self._js is None:
            raise RuntimeError("NATSClient not connected - call connect() first")

        return await self._js.subscribe(
            subject,
            durable=durable,
            cb=handler,
            manual_ack=True,
            config=ConsumerConfig(max_ack_pending=max_ack_pending),
        )

    async def close(self) -> None:
        """Drain and close the NATS connection."""
        if self._nc is not None:
            await self._nc.close()
            self._nc = None
            self._js = None
