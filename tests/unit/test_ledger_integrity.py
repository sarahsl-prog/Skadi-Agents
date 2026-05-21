"""Unit tests for ledger hash-chain integrity (no DB required)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from wolfpack.schemas.ledger import (
    LedgerIntegrityError,
    insert_ledger_entry,
    replay_ledger,
    verify_chain,
)


class TestVerifyChain:
    async def test_verify_chain_valid(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"is_valid": True, "broken_at": None}

        is_valid, broken_at = await verify_chain(conn, "case-1")
        assert is_valid is True
        assert broken_at is None
        conn.fetchrow.assert_awaited_once_with(
            "SELECT is_valid, broken_at FROM wolfpack.verify_chain($1)",
            "case-1",
        )

    async def test_verify_chain_tampered(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"is_valid": False, "broken_at": 7}

        is_valid, broken_at = await verify_chain(conn, "case-1")
        assert is_valid is False
        assert broken_at == 7

    async def test_verify_chain_empty_case(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None

        is_valid, broken_at = await verify_chain(conn, "case-1")
        assert is_valid is True
        assert broken_at is None


class TestReplayLedger:
    async def test_replay_ledger_valid_chain(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"is_valid": True, "broken_at": None}
        conn.fetch.return_value = [
            {
                "content": json.dumps(
                    {
                        "source_type": "test",
                        "source_id": "ev-1",
                        "timestamp": "2026-04-27T12:00:00Z",
                        "content_hash": "abcd",
                        "metadata": {"seq": 0},
                    }
                )
            },
            {
                "content": json.dumps(
                    {
                        "source_type": "test",
                        "source_id": "ev-2",
                        "timestamp": "2026-04-27T12:01:00Z",
                        "content_hash": "efgh",
                        "metadata": {"seq": 1},
                    }
                )
            },
        ]

        refs = await replay_ledger(conn, "case-1")
        assert len(refs) == 2
        assert refs[0].source_id == "ev-1"
        assert refs[1].source_id == "ev-2"
        assert [r.metadata["seq"] for r in refs] == [0, 1]

    async def test_replay_ledger_raises_on_tamper(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"is_valid": False, "broken_at": 3}

        with pytest.raises(LedgerIntegrityError) as exc_info:
            await replay_ledger(conn, "case-1")
        assert "case-1" in str(exc_info.value)
        assert "3" in str(exc_info.value)


class TestInsertLedgerEntry:
    async def test_insert_ledger_entry(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"id": 42}

        entry_id = await insert_ledger_entry(
            conn,
            case_id="case-1",
            entry_type="evidence",
            content={"key": "value"},
            branch_id="branch-1",
            agent_run_id="run-1",
        )
        assert entry_id == 42
        conn.fetchrow.assert_awaited_once()
        call_args = conn.fetchrow.call_args[0]
        assert "INSERT INTO wolfpack.evidence_ledger" in call_args[0]

    async def test_insert_ledger_entry_no_return(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None

        with pytest.raises(RuntimeError):
            await insert_ledger_entry(
                conn,
                case_id="case-1",
                entry_type="evidence",
                content={"key": "value"},
            )
