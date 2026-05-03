"""Operational and security alerts for WolfPack.

Each alert type is a callable class that evaluates a condition and returns
a payload dict when triggered (or ``None`` if not triggered).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any


class AlertSpec:
    """Metadata about an alert condition."""

    def __init__(
        self,
        alert_id: str,
        name: str,
        description: str,
        severity: str,
    ) -> None:
        self.alert_id = alert_id
        self.name = name
        self.description = description
        self.severity = severity


class SchemaRetrySpikeAlert:
    """Triggers when schema validation retry rate spikes."""

    SPEC = AlertSpec(
        "schema_retry_spike",
        "Schema Retry Spike",
        "Agent retry rate exceeded 20% over a 5-minute window.",
        "warning",
    )

    def __init__(
        self,
        threshold_percent: float = 20.0,
        window_seconds: float = 300.0,
        get_rate: Callable[[], float] | None = None,
    ) -> None:
        self._threshold = threshold_percent
        self._window = timedelta(seconds=window_seconds)
        self._get_rate = get_rate or self._default_rate

    @staticmethod
    def _default_rate() -> float:
        # In a real deployment this reads from OTel metrics or internal counters.
        return 0.0

    async def check(self) -> dict[str, Any] | None:
        rate = self._get_rate()
        if rate > self._threshold:
            return {
                "alert_id": self.SPEC.alert_id,
                "name": self.SPEC.name,
                "description": self.SPEC.description,
                "severity": self.SPEC.severity,
                "threshold": self._threshold,
                "current_rate": rate,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        return None


class LedgerHashMismatchAlert:
    """Triggers when a ledger hash chain verification fails."""

    SPEC = AlertSpec(
        "ledger_hash_mismatch",
        "Ledger Hash Mismatch",
        "Evidence ledger integrity verification failed for a case.",
        "critical",
    )

    def __init__(self, verify_chain_fn: Callable[[str], Any] | None = None) -> None:
        self._verify = verify_chain_fn

    async def check(self) -> dict[str, Any] | None:
        # Stub: in production this iterates active cases and calls verify_chain.
        # Here we accept an injected function so the alert remains testable.
        if self._verify is None:
            return None
        result = await asyncio.to_thread(self._verify, "__scan_all__")
        if result and not result[0]:
            return {
                "alert_id": self.SPEC.alert_id,
                "name": self.SPEC.name,
                "description": self.SPEC.description,
                "severity": self.SPEC.severity,
                "broken_case": result[1],
                "timestamp": datetime.now(UTC).isoformat(),
            }
        return None


class BranchDepthAlert:
    """Triggers when branch depth or count approaches budget limits."""

    SPEC = AlertSpec(
        "branch_depth",
        "Branch Depth Warning",
        "Branch depth or count is approaching the configured maximum.",
        "warning",
    )

    def __init__(
        self,
        max_depth: int = 3,
        max_branches: int = 10,
        get_depth_fn: Callable[[], tuple[int, int]] | None = None,
    ) -> None:
        self._max_depth = max_depth
        self._max_branches = max_branches
        self._get_depth = get_depth_fn or (lambda: (0, 0))

    async def check(self) -> dict[str, Any] | None:
        depth, branches = self._get_depth()
        if depth >= self._max_depth or branches >= int(self._max_branches * 0.8):
            return {
                "alert_id": self.SPEC.alert_id,
                "name": self.SPEC.name,
                "description": self.SPEC.description,
                "severity": self.SPEC.severity,
                "max_depth": self._max_depth,
                "max_branches": self._max_branches,
                "current_depth": depth,
                "current_branches": branches,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        return None


class ReviewTimeoutEscalationAlert:
    """Triggers on review timeout escalation and escalation-rate spike."""

    SPEC = AlertSpec(
        "review_timeout_escalation",
        "Review Timeout Escalation",
        "Analyst review timed out and was auto-escalated.",
        "warning",
    )

    def __init__(
        self,
        max_escalations_per_day: int = 5,
        get_count_fn: Callable[[], int] | None = None,
    ) -> None:
        self._max = max_escalations_per_day
        self._get_count = get_count_fn or (lambda: 0)

    async def check(self) -> dict[str, Any] | None:
        count = self._get_count()
        if count > self._max:
            return {
                "alert_id": self.SPEC.alert_id,
                "name": self.SPEC.name,
                "description": self.SPEC.description,
                "severity": "warning",
                "max_escalations_per_day": self._max,
                "escalation_count_24h": count,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        return None


class NATSConsumerLagAlert:
    """Triggers when NATS JetStream consumer pending messages exceed threshold."""

    SPEC = AlertSpec(
        "nats_consumer_lag",
        "NATS Consumer Lag",
        "NATS consumer pending message count exceeded 1000.",
        "warning",
    )

    def __init__(
        self,
        threshold: int = 1000,
        get_lag_fn: Callable[[], int] | None = None,
    ) -> None:
        self._threshold = threshold
        self._get_lag = get_lag_fn or (lambda: 0)

    async def check(self) -> dict[str, Any] | None:
        lag = self._get_lag()
        if lag > self._threshold:
            return {
                "alert_id": self.SPEC.alert_id,
                "name": self.SPEC.name,
                "description": self.SPEC.description,
                "severity": self.SPEC.severity,
                "threshold": self._threshold,
                "pending_messages": lag,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        return None


def get_builtin_alerts(
    *,
    retry_rate_fn: Callable[[], float] | None = None,
    branch_depth_fn: Callable[[], tuple[int, int]] | None = None,
    escalation_count_fn: Callable[[], int] | None = None,
    nats_lag_fn: Callable[[], int] | None = None,
    verify_chain_fn: Callable[[str], Any] | None = None,
) -> list[Any]:
    """Return a list of all built-in alert instances."""
    return [
        SchemaRetrySpikeAlert(get_rate=retry_rate_fn),
        BranchDepthAlert(get_depth_fn=branch_depth_fn),
        ReviewTimeoutEscalationAlert(get_count_fn=escalation_count_fn),
        NATSConsumerLagAlert(get_lag_fn=nats_lag_fn),
        LedgerHashMismatchAlert(verify_chain_fn=verify_chain_fn),
    ]
