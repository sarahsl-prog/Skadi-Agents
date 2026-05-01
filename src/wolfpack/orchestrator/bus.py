"""NATS JetStream client wrapper for inter-agent messaging.

The :class:`NATSClient` manages connection lifecycle, stream creation,
publish with ack confirmation, and durable consumer subscription with
manual ack/redelivery.

OpenTelemetry trace context and baggage are automatically propagated
through NATS message headers so that distributed traces span across
the event bus.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import nats
from nats.aio.msg import Msg
from nats.js.api import ConsumerConfig

from wolfpack.config.settings import NATSConfig
from wolfpack.observability.nats_propagation import extract_nats_headers, inject_nats_headers


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
        self,
        subject: str,
        payload: bytes | str | dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Publish a message to *subject* and return the server ack.

        OTel trace context and baggage are automatically injected into
        NATS headers unless *headers* already contains OTel keys.

        Args:
            subject: NATS subject (e.g. ``hunt.finding.tracker``).
            payload: Message body - bytes, string, or dict (JSON-encoded).
            headers: Optional NATS message headers (merged with OTel).

        Raises:
            RuntimeError: If the client is not connected.
        """
        if self._js is None:
            raise RuntimeError("NATSClient not connected - call connect() first")

        if isinstance(payload, dict):
            payload = json.dumps(payload).encode()
        elif isinstance(payload, str):
            payload = payload.encode()

        merged_headers = inject_nats_headers()
        if headers:
            merged_headers.update(headers)

        return await self._js.publish(
            subject, payload, headers=merged_headers
        )

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

        OTel trace context and baggage are restored from NATS headers
        before invoking *handler*.

        Args:
            subject: NATS subject to subscribe to.
            durable: Durable consumer name (e.g. ``tracker-consumer``).
            handler: Callback invoked for each message.  Must call
                ``msg.ack()`` when processing succeeds.
            max_ack_pending: Maximum unacknowledged messages allowed.
        """
        if self._js is None:
            raise RuntimeError("NATSClient not connected - call connect() first")

        def _wrapped_handler(msg: Msg) -> Any:
            extract_nats_headers(dict(msg.headers) if msg.headers else None)
            return handler(msg)

        return await self._js.subscribe(
            subject,
            durable=durable,
            cb=_wrapped_handler,
            manual_ack=True,
            config=ConsumerConfig(max_ack_pending=max_ack_pending),
        )

    async def close(self) -> None:
        """Drain and close the NATS connection."""
        if self._nc is not None:
            await self._nc.close()
            self._nc = None
            self._js = None
