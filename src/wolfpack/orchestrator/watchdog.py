"""Review timeout watchdog.

Polls for cases stuck in ``review`` status and auto-escalates them when
a configurable timeout expires.  Runs as a background asyncio task.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

GetCasesFn = Callable[[], Awaitable[list[dict[str, Any]]]]
EscalateFn = Callable[[str], Awaitable[None]]


class ReviewWatchdog:
    """Background poller that auto-escalates review cases on timeout.

    Args:
        get_cases_in_review: Async callable returning a list of case dicts.
            Each dict must contain at least ``case_id`` and
            ``review_started_at`` (ISO-8601 string or datetime).
        escalate_case: Async callable invoked with the ``case_id`` to escalate.
        timeout_hours: How long a case may sit in review before escalation.
        poll_interval_seconds: Sleep duration between polls.
    """

    def __init__(
        self,
        *,
        get_cases_in_review: GetCasesFn,
        escalate_case: EscalateFn,
        timeout_hours: float = 24.0,
        poll_interval_seconds: float = 60.0,
    ) -> None:
        self._get_cases = get_cases_in_review
        self._escalate = escalate_case
        self._timeout = timedelta(hours=timeout_hours)
        self._poll_interval = poll_interval_seconds
        self._task: asyncio.Task[Any] | None = None

    @property
    def running(self) -> bool:
        """Return ``True`` if the background polling task is active."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Begin the background polling loop."""
        if self.running:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel and await the background polling loop."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def check_timeouts(self) -> None:
        """Single sweep: escalate every case whose review has expired."""
        cases = await self._get_cases()
        now = datetime.now(UTC)
        for case in cases:
            started_at = case.get("review_started_at")
            if started_at is None:
                continue
            if isinstance(started_at, str):
                started_at = datetime.fromisoformat(started_at)
            if now - started_at > self._timeout:
                case_id = case["case_id"]
                logger.warning(
                    "Auto-escalating case %s after review timeout (%s hours)",
                    case_id,
                    self._timeout.total_seconds() / 3600,
                )
                await self._escalate(case_id)

    async def _run(self) -> None:
        while True:
            try:
                await self.check_timeouts()
            except Exception:
                logger.exception("Watchdog check failed")
            await asyncio.sleep(self._poll_interval)
