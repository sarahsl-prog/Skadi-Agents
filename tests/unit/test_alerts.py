"""Unit tests for the built-in operational/security alerts."""

from __future__ import annotations

from wolfpack.observability.alerts import (
    BranchDepthAlert,
    LedgerHashMismatchAlert,
    NATSConsumerLagAlert,
    ReviewTimeoutEscalationAlert,
    SchemaRetrySpikeAlert,
    get_builtin_alerts,
)


async def test_schema_retry_spike_triggers_above_threshold() -> None:
    alert = SchemaRetrySpikeAlert(threshold_percent=20.0, get_rate=lambda: 25.0)
    res = await alert.check()
    assert res is not None
    assert res["severity"] == "warning"
    assert res["current_rate"] == 25.0


async def test_schema_retry_spike_silent_below_threshold() -> None:
    alert = SchemaRetrySpikeAlert(threshold_percent=20.0, get_rate=lambda: 5.0)
    assert await alert.check() is None


async def test_review_timeout_payload_severity_matches_spec() -> None:
    # MED-40 regression: payload severity must equal the SPEC severity.
    alert = ReviewTimeoutEscalationAlert(max_escalations_per_day=5, get_count_fn=lambda: 10)
    res = await alert.check()
    assert res is not None
    assert res["severity"] == ReviewTimeoutEscalationAlert.SPEC.severity == "warning"


async def test_ledger_hash_mismatch_triggers_critical() -> None:
    alert = LedgerHashMismatchAlert(verify_chain_fn=lambda _case: (False, 7))
    res = await alert.check()
    assert res is not None
    assert res["severity"] == "critical"
    assert res["broken_case"] == 7


async def test_ledger_hash_mismatch_silent_when_valid() -> None:
    alert = LedgerHashMismatchAlert(verify_chain_fn=lambda _case: (True, None))
    assert await alert.check() is None


async def test_branch_depth_triggers_at_max_depth() -> None:
    alert = BranchDepthAlert(max_depth=3, max_branches=10, get_depth_fn=lambda: (3, 0))
    assert await alert.check() is not None


async def test_nats_lag_silent_below_threshold() -> None:
    alert = NATSConsumerLagAlert(threshold=1000, get_lag_fn=lambda: 10)
    assert await alert.check() is None


def test_builtin_alerts_includes_ledger_hash_mismatch() -> None:
    # MED-41 regression: the critical ledger integrity alert must ship by default.
    alerts = get_builtin_alerts()
    names = {type(a).__name__ for a in alerts}
    assert "LedgerHashMismatchAlert" in names
    assert names == {
        "SchemaRetrySpikeAlert",
        "BranchDepthAlert",
        "ReviewTimeoutEscalationAlert",
        "NATSConsumerLagAlert",
        "LedgerHashMismatchAlert",
    }
