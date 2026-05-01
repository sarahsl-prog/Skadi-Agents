"""Unit tests for the policy engine."""

import pytest

from wolfpack.agents.policy import PolicyEngine
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.seed import Seed
from wolfpack.schemas.verdict import VerdictPacket


@pytest.mark.anyio
async def test_high_confidence_malicious_triggers_policy() -> None:
    """High-confidence MALICIOUS verdict triggers critical guardrail."""
    engine = PolicyEngine()
    verdict = VerdictPacket(decision="MALICIOUS", confidence=Confidence.STRONG)
    case = CaseState(case_id="test-1", seed=Seed(type="ioc"))
    guards = await engine.evaluate(verdict, case)
    assert any(g.id == "high_confidence_malicious" for g in guards)
    assert any(g.severity == "critical" for g in guards)


@pytest.mark.anyio
async def test_low_confidence_inconclusive_triggers_warning() -> None:
    """Low-confidence INCONCLUSIVE triggers warning guardrail."""
    engine = PolicyEngine()
    verdict = VerdictPacket(decision="INCONCLUSIVE", confidence=Confidence.WEAK)
    case = CaseState(case_id="test-1", seed=Seed(type="ioc"))
    guards = await engine.evaluate(verdict, case)
    assert any(g.id == "low_confidence_inconclusive" for g in guards)


@pytest.mark.anyio
async def test_high_confidence_benign_info() -> None:
    """High-confidence BENIGN triggers info guardrail."""
    engine = PolicyEngine()
    verdict = VerdictPacket(decision="BENIGN", confidence=Confidence.STRONG)
    case = CaseState(case_id="test-1", seed=Seed(type="ioc"))
    guards = await engine.evaluate(verdict, case)
    assert any(g.id == "high_confidence_benign_auto_close" for g in guards)
    assert any(g.severity == "info" for g in guards)


@pytest.mark.anyio
async def test_no_policy_triggered_for_neutral() -> None:
    """A verdict that matches no policy returns empty guards."""
    engine = PolicyEngine()
    verdict = VerdictPacket(decision="BENIGN", confidence=Confidence.WEAK)
    case = CaseState(case_id="test-1", seed=Seed(type="ioc"))
    guards = await engine.evaluate(verdict, case)
    assert not guards
