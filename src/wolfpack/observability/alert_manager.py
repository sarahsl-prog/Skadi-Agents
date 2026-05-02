"""Alert manager with deduplication and webhook routing.

Runs a configurable set of alert monitors on a schedule, deduplicates
consecutive identical alerts within a cooldown window, and routes them
to a configured webhook.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from opentelemetry import trace

from wolfpack.config.settings import Settings
from wolfpack.observability.alerts import get_builtin_alerts

TRACER = trace.get_tracer("wolfpack")


class AlertManager:
    """Periodic alert monitor runner with deduplication.

    Usage::

        manager = AlertManager(settings, cooldown_seconds=300)
        await manager.start()
        # ... runs forever until stop() is called
        await manager.stop()
    """

    def __init__(
        self,
        settings: Settings | None = None,
        cooldown_seconds: float = 300.0,
        poll_interval_seconds: float = 60.0,
        monitors: list[Any] | None = None,
        webhook_url: str | None = None,
    ) -> None:
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._poll_interval = poll_interval_seconds
        self._monitors = monitors or []
        self._webhook_url = webhook_url or (
            settings.webhook_config.url if settings and settings.webhook_config else None
        )
        self._task: asyncio.Task[Any] | None = None
        self._last_fired: dict[str, datetime] = {}

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Begin the background polling loop."""
        if self.running:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel and await the polling loop."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self) -> list[dict[str, Any]]:
        """Run all monitors once and return newly triggered alerts."""
        triggered: list[dict[str, Any]] = []
        for monitor in self._monitors:
            result = await monitor.check()
            if result and self._should_fire(result):
                self._record_fire(result)
                triggered.append(result)
                await self._dispatch(result)
        return triggered

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception as exc:
                # OTel span event for background error
                with TRACER.start_as_current_span("alert_manager.poll") as span:
                    span.record_exception(exc)
                    span.set_status(trace.StatusCode.ERROR, str(exc))
            await asyncio.sleep(self._poll_interval)

    _DEDUP_EXCLUDE: frozenset[str] = frozenset(
        {"timestamp", "fired_at", "dispatched_at", "seq", "id"}
    )

    def _alert_key(self, alert: dict[str, Any]) -> str:
        """Build a canonical hash that excludes volatile / non-identity fields."""
        filtered = {
            k: v for k, v in alert.items() if k not in self._DEDUP_EXCLUDE
        }
        canonical = json.dumps(filtered, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def _should_fire(self, alert: dict[str, Any]) -> bool:
        key = self._alert_key(alert)
        last = self._last_fired.get(key)
        if last is None:
            return True
        return datetime.now(UTC) - last > self._cooldown

    def _record_fire(self, alert: dict[str, Any]) -> None:
        self._last_fired[self._alert_key(alert)] = datetime.now(UTC)

    async def _dispatch(self, alert: dict[str, Any]) -> None:
        with TRACER.start_as_current_span("alert_manager.dispatch") as span:
            span.set_attribute("alert.id", alert.get("alert_id", "unknown"))
            span.set_attribute("alert.severity", alert.get("severity", "unknown"))
            if self._webhook_url is None:
                span.add_event("alert_manager.dispatch_skipped", {"reason": "no_webhook_url"})
                return
            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        self._webhook_url,
                        json=alert,
                        timeout=30.0,
                    )
                    resp.raise_for_status()
                span.add_event("alert_manager.dispatch_sent", {"status_code": resp.status_code})
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
