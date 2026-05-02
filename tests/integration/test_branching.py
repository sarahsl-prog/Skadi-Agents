"""Integration tests for branch creation, budget, and dedup."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from wolfpack.orchestrator.budget import BranchBudget, BudgetRemaining
from wolfpack.orchestrator.dedup import hypothesis_dedup
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.hypothesis import Hypothesis


class TestBranchBudget:
    """Branch-explosion controls."""

    @pytest.mark.anyio
    async def test_default_budget_allows_creation(self) -> None:
        budget = BranchBudget()
        assert await budget.check("case-001", branch_depth=1) is True

    @pytest.mark.anyio
    async def test_depth_limit_enforced(self) -> None:
        budget = BranchBudget()
        assert await budget.check("case-001", branch_depth=3) is True
        assert await budget.check("case-001", branch_depth=4) is False

    @pytest.mark.anyio
    async def test_branch_count_limit_enforced(self) -> None:
        budget = BranchBudget()
        budget.consume("case-001", branches=10)
        assert await budget.check("case-001", branch_depth=1) is False

    @pytest.mark.anyio
    async def test_remaining_budget(self) -> None:
        budget = BranchBudget()
        budget.consume("case-001", branches=2)
        rem = await budget.remaining("case-001")
        assert rem.branches_remaining == 8
        assert rem.depth_remaining == 3

    @pytest.mark.anyio
    async def test_budget_is_per_case(self) -> None:
        budget = BranchBudget()
        budget.consume("case-001", branches=10)
        assert await budget.check("case-001", branch_depth=1) is False
        assert await budget.check("case-002", branch_depth=1) is True


class TestHypothesisDedup:
    """Hypothesis deduplication via cosine similarity."""

    def test_distinct_hypotheses_not_merged(self) -> None:
        existing = [
            Hypothesis(
                description="Lateral movement via RDP",
                confidence=Confidence.PLAUSIBLE,
            ),
        ]
        new = Hypothesis(
            description="Data exfiltration via DNS tunneling",
            confidence=Confidence.STRONG,
        )
        result = hypothesis_dedup(existing, new, threshold=0.85)
        assert result is None

    def test_similar_hypotheses_merged(self) -> None:
        existing = [
            Hypothesis(
                description="Lateral movement via RDP from 10.0.0.1",
                confidence=Confidence.PLAUSIBLE,
            ),
        ]
        new = Hypothesis(
            description="Lateral movement via RDP from 10.0.0.1 to 10.0.0.2",
            confidence=Confidence.STRONG,
        )
        result = hypothesis_dedup(existing, new, threshold=0.85)
        assert result is not None
        assert result.confidence == Confidence.STRONG

    def test_merge_combines_evidence_refs(self) -> None:
        from wolfpack.schemas.evidence import EvidenceRef

        existing = [
            Hypothesis(
                description="Lateral movement via RDP",
                confidence=Confidence.PLAUSIBLE,
                evidence_refs=[EvidenceRef(source_type="syslog", source_id="ev-1")],
            ),
        ]
        new = Hypothesis(
            description="Lateral movement via RDP",
            confidence=Confidence.STRONG,
            evidence_refs=[EvidenceRef(source_type="dns", source_id="ev-2")],
        )
        result = hypothesis_dedup(existing, new, threshold=0.85)
        assert result is not None
        assert len(result.evidence_refs) == 2

    def test_threshold_configurable(self) -> None:
        existing = [
            Hypothesis(
                description="Lateral movement via RDP",
                confidence=Confidence.PLAUSIBLE,
            ),
        ]
        new = Hypothesis(
            description="Lateral movement via SMB",
            confidence=Confidence.STRONG,
        )
        # High threshold should not merge
        assert hypothesis_dedup(existing, new, threshold=0.99) is None
        # Low threshold might merge
        result = hypothesis_dedup(existing, new, threshold=0.1)
        assert result is not None


class TestBranchCreationIntegration:
    """End-to-end branch creation with mocked persistence."""

    @pytest.mark.asyncio
    async def test_create_branch_publishes_nats(self) -> None:
        from wolfpack.orchestrator.branches import create_branch
        from wolfpack.orchestrator.bus import NATSClient
        from wolfpack.schemas.branch import BranchSpec
        from wolfpack.schemas.persistence import CasePersistence

        mock_persistence = MagicMock(spec=CasePersistence)
        mock_persistence.create_branch = AsyncMock()

        mock_nats = MagicMock(spec=NATSClient)
        mock_nats.connected = True
        mock_nats.publish = AsyncMock()

        branch_spec = BranchSpec(
            hypothesis=Hypothesis(
                description="Test branch",
                confidence=Confidence.PLAUSIBLE,
            ),
            created_by="flanker",
        )

        result = await create_branch(
            case_id="case-001",
            parent_branch_id="parent-001",
            hypothesis=branch_spec.hypothesis,
            depth=1,
            created_by="flanker",
            persistence=mock_persistence,
            nats_client=mock_nats,
        )

        assert result.case_id == "case-001"
        assert result.parent_branch_id == "parent-001"
        assert result.spec.hypothesis.description == "Test branch"
        mock_persistence.create_branch.assert_awaited_once()
        mock_nats.publish.assert_awaited_once()
        call_args = mock_nats.publish.call_args
        assert call_args[0][0] == "hunt.branch.created"
        payload = call_args[0][1]
        assert payload["case_id"] == "case-001"
        assert payload["parent_branch_id"] == "parent-001"
        assert payload["depth"] == 1

    @pytest.mark.asyncio
    async def test_create_branch_without_nats(self) -> None:
        from wolfpack.orchestrator.branches import create_branch
        from wolfpack.schemas.branch import BranchSpec
        from wolfpack.schemas.persistence import CasePersistence

        mock_persistence = MagicMock(spec=CasePersistence)
        mock_persistence.create_branch = AsyncMock()

        branch_spec = BranchSpec(
            hypothesis=Hypothesis(
                description="Test branch",
                confidence=Confidence.PLAUSIBLE,
            ),
            created_by="flanker",
        )

        result = await create_branch(
            case_id="case-001",
            parent_branch_id=None,
            hypothesis=branch_spec.hypothesis,
            depth=0,
            created_by="alpha",
            persistence=mock_persistence,
            nats_client=None,
        )

        assert result.parent_branch_id is None
        assert result.spec.depth == 0
        mock_persistence.create_branch.assert_awaited_once()
