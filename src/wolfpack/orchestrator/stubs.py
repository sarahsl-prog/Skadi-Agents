"""Deterministic agent stubs for the LangGraph orchestration skeleton.

All stubs are pure functions with no LLM calls, no network I/O, and no
side effects.  They return ``dict`` fragments that LangGraph merges into
``CaseState``.
"""

from __future__ import annotations

import uuid
from typing import Any

from wolfpack.schemas.branch import BranchSpec
from wolfpack.schemas.case_state import BranchState, CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.hypothesis import Hypothesis


def stub_alpha(state: CaseState) -> dict[str, Any]:
    """Create the initial case scaffold from the seed.

    Returns a dict that updates ``state`` with:
    - ``status="scented"``
    - a single root branch
    """
    root_branch = BranchState(
        branch_id=str(uuid.uuid4()),
        case_id=state.case_id,
        spec=BranchSpec(
            hypothesis=Hypothesis(
                description="Stub: root hypothesis from seed",
                confidence=Confidence.PLAUSIBLE,
            ),
            created_by="alpha",
        ),
    )
    return {
        "status": "scented",
        "branches": [root_branch],
    }


def stub_tracker(state: CaseState) -> dict[str, Any]:
    """Return fixed Tracker output.

    Always returns ``Confidence.PLAUSIBLE`` (3) so the graph routes to
    the *closer* node by default.
    """
    hypothesis = Hypothesis(
        description="Stub: initial scent detected",
        confidence=Confidence.PLAUSIBLE,
    )
    _entity = Entity(type="ip", value="192.0.2.1")
    evidence = EvidenceRef(source_type="stub", source_id="tracker-001")
    return {
        "hypotheses": [hypothesis],
        "evidence_refs": [evidence],
        "tracker_confidence": Confidence.PLAUSIBLE,
        "status": "shadowing",
    }


def stub_flanker(state: CaseState) -> dict[str, Any]:
    """Return fixed Flanker output with no new branches.

    The pivot is empty so the graph continues to *closer*.
    """
    return {
        "flanker_confidence": Confidence.WEAK,
    }


def stub_closer(state: CaseState) -> dict[str, Any]:
    """Return a benign verdict packet.

    Sets ``verdict_decision`` and ``overall_confidence`` so the graph
    can transition to *review*.
    """
    return {
        "verdict_decision": "benign",
        "overall_confidence": Confidence.PLAUSIBLE,
        "status": "review",
    }


def stub_scribe(state: CaseState) -> dict[str, Any]:
    """No-op scribe stub.

    The real Scribe service (Track D) writes to the evidence ledger.
    """
    return {}


def stub_review(state: CaseState) -> dict[str, Any]:
    """Auto-approve every case.

    Returns ``review_decision="approved"`` so the graph terminates at
    ``END``.
    """
    return {
        "review_decision": "approved",
        "status": "closed",
    }
