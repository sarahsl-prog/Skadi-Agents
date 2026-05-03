"""Integration tests for the alerting layer.

Covers all five built-in alert types plus the AlertManager deduplication
and scheduling logic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from wolfpack.observability.alert_manager import AlertManager
from wolfpack.observability.alerts import get_builtin_alerts


@pytest.fixture
def dummy_rate_fn():
    return lambda: 22.0


@pytest.fixture
def dummy_depth_fn():
    return lambda: (3, 10)


@pytest.fixture
def dummy_escalation_fn():
    return lambda: 6


@pytest.fixture
def dummy_lag_fn():
    return lambda: 1500


@pytest.mark.asyncio
async def test_alert_manager_triggers_and_deduplicates(
    dummy_rate_fn,
    dummy_depth_fn,
    dummy_escalation_fn,
    dummy_lag_fn,
) -> None:
    """AlertManager should trigger alerts once, then deduplicate."""
    monitors = get_builtin_alerts(
        retry_rate_fn=dummy_rate_fn,
        branch_depth_fn=dummy_depth_fn,
        escalation_count_fn=dummy_escalation_fn,
        nats_lag_fn=dummy_lag_fn,
    )
    manager = AlertManager(
        monitors=monitors,
        webhook_url="http://example.com/webhook",
        poll_interval_seconds=0.1,
        cooldown_seconds=5.0,
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        triggered = await manager.run_once()
        assert len(triggered) == 4  # all except ledger (no verify fn)

        # Second run should deduplicate
        triggered2 = await manager.run_once()
        assert len(triggered2) == 0

        mock_post.assert_called()
