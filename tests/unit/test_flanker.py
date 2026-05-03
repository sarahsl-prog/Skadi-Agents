"""Unit tests for the Flanker agent."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import Agent

from wolfpack.agents.flanker import (
    FLANKER_TOOL_ALLOWLIST,
    FlankerDeps,
    _build_flanker_agent,
    _validate_tools,
    run_flanker,
)
from wolfpack.schemas.agents.flanker import FlankerInput, FlankerOutput
from wolfpack.schemas.branch import BranchSpec
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.hypothesis import Hypothesis
from wolfpack.schemas.seed import Seed


class TestFlankerToolAllowlist:
    """Tool allowlist enforcement."""

    def test_allowlist_contains_expected_tools(self) -> None:
        expected = {
            "threat_intel_tool",
            "case_history_tool",
            "syslog_query",
            "windows_eventlog_query",
            "crowdstrike_query",
            "okta_query",
            "firewall_query",
            "dns_query",
            "zeek_suricata_query",
            "proxy_query",
            "cloudtrail_query",
        }
        assert expected.issubset(FLANKER_TOOL_ALLOWLIST)

    def test_validate_tools_passes_for_allowed(self) -> None:
        def dummy_tool() -> None:
            pass

        dummy_tool.__name__ = "threat_intel_tool"
        _validate_tools([dummy_tool])  # should not raise

    def test_validate_tools_blocks_unauthorized(self) -> None:
        def bad_tool() -> None:
            pass

        bad_tool.__name__ = "malicious_tool"
        with pytest.raises(RuntimeError, match="not in the Flanker allowlist"):
            _validate_tools([bad_tool])


class TestBuildFlankerAgent:
    """Agent construction with feature flags."""

    def test_agent_builds_without_error(self) -> None:
        agent = _build_flanker_agent()
        assert agent is not None
        assert agent.output_type is FlankerOutput

    def test_agent_builds_with_feature_flags(self) -> None:
        flags = {
            "adapter_dns": True,
            "adapter_proxy": True,
        }
        agent = _build_flanker_agent(feature_flags=flags)
        assert agent is not None


class TestRunFlanker:
    """Graph-node entry point."""

    @pytest.fixture()
    def case_state(self) -> CaseState:
        return CaseState(
            case_id=str(uuid.uuid4()),
            seed=Seed(type="ioc", raw_payload={"value": "10.0.0.1"}),
            re_check_count=0,
        )

    @pytest.mark.asyncio
    async def test_run_flanker_increments_re_check_count(self, case_state: CaseState) -> None:
        mock_output = FlankerOutput(
            flanker_confidence=Confidence.PLAUSIBLE,
            significant_findings=False,
        )
        mock_result = MagicMock()
        mock_result.output = mock_output

        with patch.object(
            Agent, "run", new_callable=AsyncMock, return_value=mock_result
        ) as mock_run:
            deps = FlankerDeps()
            result = await run_flanker(case_state, deps=deps)

        assert result["re_check_count"] == 1
        assert result["significant_findings"] is False
        assert result["flanker_confidence"] == Confidence.PLAUSIBLE
        mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_flanker_with_significant_findings(self, case_state: CaseState) -> None:
        mock_output = FlankerOutput(
            flanker_confidence=Confidence.STRONG,
            significant_findings=True,
            updated_entities=[Entity(type="ip", value="10.0.0.2")],
            new_hypotheses=[
                Hypothesis(
                    description="Lateral movement detected",
                    confidence=Confidence.STRONG,
                )
            ],
            branches_to_create=[
                BranchSpec(
                    hypothesis=Hypothesis(
                        description="Lateral movement branch",
                        confidence=Confidence.STRONG,
                    ),
                    created_by="flanker",
                )
            ],
        )
        mock_result = MagicMock()
        mock_result.output = mock_output

        with patch.object(Agent, "run", new_callable=AsyncMock, return_value=mock_result):
            deps = FlankerDeps()
            result = await run_flanker(case_state, deps=deps)

        assert result["significant_findings"] is True
        assert len(result["updated_entities"]) == 1
        assert len(result["new_hypotheses"]) == 1
        assert len(result["branches_to_create"]) == 1

    @pytest.mark.asyncio
    async def test_run_flanker_deduplicates_entities(self, case_state: CaseState) -> None:
        case_state.branches = []
        mock_output = FlankerOutput(
            flanker_confidence=Confidence.WEAK,
            significant_findings=False,
        )
        mock_result = MagicMock()
        mock_result.output = mock_output

        with patch.object(Agent, "run", new_callable=AsyncMock, return_value=mock_result):
            deps = FlankerDeps()
            result = await run_flanker(case_state, deps=deps)

        assert result["re_check_count"] == 1

    def test_flanker_input_model(self) -> None:
        inp = FlankerInput(
            case_id="case-001",
            branch_id="branch-001",
            entities=[Entity(type="ip", value="10.0.0.1")],
        )
        assert inp.case_id == "case-001"

    def test_flanker_output_model(self) -> None:
        out = FlankerOutput(
            flanker_confidence=Confidence.PLAUSIBLE,
            significant_findings=True,
        )
        assert out.significant_findings is True

    def test_flanker_output_defaults(self) -> None:
        out = FlankerOutput(flanker_confidence=Confidence.WEAK)
        assert out.significant_findings is False
        assert out.updated_entities == []
        assert out.new_hypotheses == []
        assert out.evidence_refs == []
        assert out.branches_to_create == []
