"""Unit tests for the review timeout watchdog."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from wolfpack.orchestrator.watchdog import ReviewWatchdog


class TestReviewWatchdog:
    """Core watchdog operations with mocked callbacks."""

    @pytest.fixture()
    def mock_callbacks(self) -> Any:
        cases: list[dict[str, Any]] = []
        escalated: list[str] = []

        async def get_cases() -> list[dict[str, Any]]:
            return list(cases)

        async def escalate(case_id: str) -> None:
            escalated.append(case_id)

        return (cases, escalated, get_cases, escalate)

    @pytest.mark.asyncio
    async def test_escalates_after_timeout(self, mock_callbacks: Any) -> None:
        cases, escalated, get_cases, escalate = mock_callbacks
        now = datetime.now(UTC)
        cases.append(
            {
                "case_id": "case-1",
                "review_started_at": now - timedelta(hours=25),
            }
        )

        wd = ReviewWatchdog(
            get_cases_in_review=get_cases,
            escalate_case=escalate,
            timeout_hours=24.0,
        )
        await wd.check_timeouts()
        assert escalated == ["case-1"]

    @pytest.mark.asyncio
    async def test_does_not_escalate_before_timeout(self, mock_callbacks: Any) -> None:
        cases, escalated, get_cases, escalate = mock_callbacks
        now = datetime.now(UTC)
        cases.append(
            {
                "case_id": "case-2",
                "review_started_at": now - timedelta(hours=23),
            }
        )

        wd = ReviewWatchdog(
            get_cases_in_review=get_cases,
            escalate_case=escalate,
            timeout_hours=24.0,
        )
        await wd.check_timeouts()
        assert escalated == []

    @pytest.mark.asyncio
    async def test_skips_missing_started_at(self, mock_callbacks: Any) -> None:
        cases, escalated, get_cases, escalate = mock_callbacks
        cases.append({"case_id": "case-3", "review_started_at": None})

        wd = ReviewWatchdog(
            get_cases_in_review=get_cases,
            escalate_case=escalate,
            timeout_hours=24.0,
        )
        await wd.check_timeouts()
        assert escalated == []

    @pytest.mark.asyncio
    async def test_parses_iso_string_timestamp(self, mock_callbacks: Any) -> None:
        cases, escalated, get_cases, escalate = mock_callbacks
        now = datetime.now(UTC)
        cases.append(
            {
                "case_id": "case-4",
                "review_started_at": (now - timedelta(hours=25)).isoformat(),
            }
        )

        wd = ReviewWatchdog(
            get_cases_in_review=get_cases,
            escalate_case=escalate,
            timeout_hours=24.0,
        )
        await wd.check_timeouts()
        assert escalated == ["case-4"]

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, mock_callbacks: Any) -> None:
        _, _, get_cases, escalate = mock_callbacks

        wd = ReviewWatchdog(
            get_cases_in_review=get_cases,
            escalate_case=escalate,
            timeout_hours=24.0,
            poll_interval_seconds=0.1,
        )
        assert not wd.running
        await wd.start()
        assert wd.running
        await asyncio.sleep(0.05)
        await wd.stop()
        assert not wd.running

    @pytest.mark.asyncio
    async def test_multiple_cases(self, mock_callbacks: Any) -> None:
        cases, escalated, get_cases, escalate = mock_callbacks
        now = datetime.now(UTC)
        cases.extend(
            [
                {
                    "case_id": "expired-a",
                    "review_started_at": now - timedelta(hours=30),
                },
                {
                    "case_id": "fresh-b",
                    "review_started_at": now - timedelta(hours=1),
                },
                {
                    "case_id": "expired-c",
                    "review_started_at": now - timedelta(hours=48),
                },
            ]
        )

        wd = ReviewWatchdog(
            get_cases_in_review=get_cases,
            escalate_case=escalate,
            timeout_hours=24.0,
        )
        await wd.check_timeouts()
        assert sorted(escalated) == ["expired-a", "expired-c"]
