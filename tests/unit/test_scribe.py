"""Unit tests for the Scribe service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from wolfpack.agents.scribe import ScribeInterface
from wolfpack.schemas.agents.scribe import ScribeInput, ScribeOutput


class TestScribeInterface:
    """Scribe operations with mocked persistence."""

    @pytest.fixture()
    def mock_pool(self) -> MagicMock:
        pool = MagicMock()
        conn = AsyncMock()
        pool.acquire = AsyncMock(return_value=conn)
        pool.release = AsyncMock()
        return pool

    @pytest.mark.asyncio
    async def test_write_ledger_entry(self, mock_pool: MagicMock) -> None:
        scribe = ScribeInterface(mock_pool)
        entry_id = await scribe.write_ledger_entry(
            case_id="case-1",
            entry_type="agent_action",
            content={"agent": "tracker", "action": "scent"},
            agent_run_id="run-1",
        )
        assert entry_id >= 1
        mock_pool.acquire.assert_awaited_once()
        mock_pool.release.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_write_timeline_event(self, mock_pool: MagicMock) -> None:
        scribe = ScribeInterface(mock_pool)
        entry_id = await scribe.write_timeline_event(
            case_id="case-1",
            event_type="state_transition",
            description="Case moved to review",
        )
        assert entry_id >= 1

    @pytest.mark.asyncio
    async def test_process(self, mock_pool: MagicMock) -> None:
        scribe = ScribeInterface(mock_pool)
        input = ScribeInput(
            case_id="case-1",
            event_type="agent_action",
            payload={"agent": "tracker"},
            agent_run_id="run-1",
        )
        output = await scribe.process(input)
        assert isinstance(output, ScribeOutput)
        assert output.ledger_entry_id
        assert "agent_action" in output.summary
