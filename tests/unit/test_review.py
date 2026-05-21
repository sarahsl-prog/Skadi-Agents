"""Unit tests for the interrupt-based review node."""

from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from wolfpack.orchestrator.review import review_node
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.seed import Seed


class TestReviewNode:
    """Review node behaviour with LangGraph Interrupt."""

    @pytest.fixture()
    def compiled_graph(self) -> Any:
        graph = StateGraph(CaseState)
        graph.add_node("review", review_node)
        graph.add_edge(START, "review")
        graph.add_edge("review", END)
        return graph.compile(checkpointer=MemorySaver())

    def test_interrupt_on_first_run(self, compiled_graph: Any) -> None:
        state = CaseState(case_id="case-1", seed=Seed(type="ioc", raw_payload={}))
        config = {"configurable": {"thread_id": "rev-1"}}
        result = compiled_graph.invoke(state, config)
        assert "__interrupt__" in result

    def test_resume_approved(self, compiled_graph: Any) -> None:
        state = CaseState(case_id="case-1", seed=Seed(type="ioc", raw_payload={}))
        config = {"configurable": {"thread_id": "rev-2"}}
        compiled_graph.invoke(state, config)
        result = compiled_graph.invoke(Command(resume="approved"), config)
        assert result["review_decision"] == "approved"
        assert result["status"] == "closed"

    def test_resume_escalate(self, compiled_graph: Any) -> None:
        state = CaseState(case_id="case-1", seed=Seed(type="ioc", raw_payload={}))
        config = {"configurable": {"thread_id": "rev-3"}}
        compiled_graph.invoke(state, config)
        result = compiled_graph.invoke(Command(resume="escalate"), config)
        assert result["review_decision"] == "escalate"
        assert result["status"] == "escalation"

    def test_resume_close_benign(self, compiled_graph: Any) -> None:
        state = CaseState(case_id="case-1", seed=Seed(type="ioc", raw_payload={}))
        config = {"configurable": {"thread_id": "rev-4"}}
        compiled_graph.invoke(state, config)
        result = compiled_graph.invoke(Command(resume="close_benign"), config)
        assert result["review_decision"] == "close_benign"
        assert result["status"] == "closed"

    def test_resume_continue(self, compiled_graph: Any) -> None:
        state = CaseState(case_id="case-1", seed=Seed(type="ioc", raw_payload={}))
        config = {"configurable": {"thread_id": "rev-5"}}
        compiled_graph.invoke(state, config)
        result = compiled_graph.invoke(Command(resume="continue"), config)
        assert result["review_decision"] == "continue"
        assert result["status"] == "scented"

    def test_unknown_decision_defaults_to_escalation(self, compiled_graph: Any) -> None:
        state = CaseState(case_id="case-1", seed=Seed(type="ioc", raw_payload={}))
        config = {"configurable": {"thread_id": "rev-6"}}
        compiled_graph.invoke(state, config)
        result = compiled_graph.invoke(Command(resume="banana"), config)
        assert result["review_decision"] == "escalate"
        assert result["status"] == "escalation"

    def test_interrupt_payload_contains_context(self, compiled_graph: Any) -> None:
        state = CaseState(
            case_id="case-ctx",
            seed=Seed(type="ioc", raw_payload={}),
            verdict_decision="MALICIOUS",
            overall_confidence=Confidence.HIGH_FIDELITY,
        )
        config = {"configurable": {"thread_id": "rev-7"}}
        result = compiled_graph.invoke(state, config)
        interrupts = result["__interrupt__"]
        assert len(interrupts) == 1
        assert interrupts[0].value["case_id"] == "case-ctx"
        assert interrupts[0].value["verdict"] == "MALICIOUS"
        assert interrupts[0].value["confidence"] == Confidence.HIGH_FIDELITY
