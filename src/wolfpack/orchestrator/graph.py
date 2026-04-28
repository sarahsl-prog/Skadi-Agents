"""LangGraph hunt orchestration graph.

The graph defines the canonical SOC hunt flow:

    START → alpha_dispatcher → tracker → [conditional] → flanker or closer
    flanker → closer
    closer → review → [conditional] → END or alpha_dispatcher

Scribe is interleaved after every main node so that every transition is
recorded on the evidence ledger.

``build_hunt_graph(use_stubs=True)`` returns a compiled graph that can be
invoked with a ``CaseState`` dict.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence


def _route_after_tracker(state: CaseState) -> str:
    """Route Tracker output based on confidence.

    Confidence < 3 (``COINCIDENCE`` or ``WEAK``) sends the case to Flanker
    for re-check.  Everything else proceeds to Closer.
    """
    if state.tracker_confidence is None:
        return "closer"
    if state.tracker_confidence < Confidence.PLAUSIBLE:
        return "flanker"
    return "closer"


def _route_after_review(state: CaseState) -> str:
    """Route Review output based on analyst decision.

    ``continue`` loops back to Alpha for follow-up tasking.  All other
    decisions (``approved``, ``escalate``, ``close_benign``) terminate the
    graph at ``END``.
    """
    if state.review_decision == "continue":
        return "alpha_dispatcher"
    return END


def build_hunt_graph(
    *,
    use_stubs: bool = True,
    alpha: Callable[[CaseState], dict[str, Any]] | None = None,
    tracker: Callable[[CaseState], dict[str, Any]] | None = None,
    flanker: Callable[[CaseState], dict[str, Any]] | None = None,
    closer: Callable[[CaseState], dict[str, Any]] | None = None,
    review: Callable[[CaseState], dict[str, Any]] | None = None,
    scribe: Callable[[CaseState], dict[str, Any]] | None = None,
) -> Any:
    """Compile the hunt graph.

    When ``use_stubs`` is ``True`` (the default) every agent slot is
    filled with its deterministic stub from :mod:`wolfpack.orchestrator.stubs`.
    Real agent implementations can be injected via the keyword arguments.

    The graph can be invoked with a ``CaseState`` dict:

    .. code-block:: python

        graph = build_hunt_graph()
        result = graph.invoke({
            "case_id": str(uuid.uuid4()),
            "seed": seed,
        })
    """
    if use_stubs:
        from wolfpack.orchestrator.stubs import (
            stub_alpha,
            stub_closer,
            stub_flanker,
            stub_review,
            stub_scribe,
            stub_tracker,
        )

        if alpha is None:
            alpha = stub_alpha
        if tracker is None:
            tracker = stub_tracker
        if flanker is None:
            flanker = stub_flanker
        if closer is None:
            closer = stub_closer
        if review is None:
            review = stub_review
        if scribe is None:
            scribe = stub_scribe

    builder = StateGraph(CaseState)

    # Main agent nodes
    builder.add_node("alpha_dispatcher", alpha)  # type: ignore[call-overload]
    builder.add_node("tracker", tracker)  # type: ignore[call-overload]
    builder.add_node("flanker", flanker)  # type: ignore[call-overload]
    builder.add_node("closer", closer)  # type: ignore[call-overload]
    builder.add_node("review", review)  # type: ignore[call-overload]

    # Scribe nodes - one after each main node so the graph topology is
    # deterministic and every transition is journaled.
    builder.add_node("scribe_after_alpha", scribe)  # type: ignore[call-overload]
    builder.add_node("scribe_after_tracker", scribe)  # type: ignore[call-overload]
    builder.add_node("scribe_after_flanker", scribe)  # type: ignore[call-overload]
    builder.add_node("scribe_after_closer", scribe)  # type: ignore[call-overload]

    # Canonical hunt flow
    builder.add_edge(START, "alpha_dispatcher")
    builder.add_edge("alpha_dispatcher", "scribe_after_alpha")
    builder.add_edge("scribe_after_alpha", "tracker")
    builder.add_edge("tracker", "scribe_after_tracker")
    builder.add_conditional_edges(
        "scribe_after_tracker",
        _route_after_tracker,
        {
            "flanker": "flanker",
            "closer": "closer",
        },
    )
    builder.add_edge("flanker", "scribe_after_flanker")
    builder.add_edge("scribe_after_flanker", "closer")
    builder.add_edge("closer", "scribe_after_closer")
    builder.add_edge("scribe_after_closer", "review")
    builder.add_conditional_edges(
        "review",
        _route_after_review,
        {
            "alpha_dispatcher": "alpha_dispatcher",
            END: END,
        },
    )

    return builder.compile()
