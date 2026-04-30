"""Review node with LangGraph Interrupt for analyst-in-the-loop.

The review node pauses graph execution until an analyst resumes it with a
decision.  On first invocation it raises :class:`langgraph.types.Interrupt`;
on resume ``interrupt()`` returns the decision string supplied by the caller.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from wolfpack.schemas.case_state import CaseState


def review_node(state: CaseState) -> dict[str, Any]:
    """Pause for analyst review and apply their decision.

    The interrupt payload carries enough context for an analyst console to
    display the case summary.  Valid decisions returned on resume are:
    ``approved``, ``escalate``, ``close_benign``, ``continue``.
    Any unrecognised decision is treated as ``escalate`` for safety.
    """
    decision = interrupt(
        {
            "case_id": state.case_id,
            "verdict": state.verdict_decision,
            "confidence": state.overall_confidence,
            "message": "Awaiting analyst review",
        }
    )

    updates: dict[str, Any] = {"review_decision": decision}
    if decision in ("approved", "close_benign"):
        updates["status"] = "closed"
    elif decision == "escalate":
        updates["status"] = "escalation"
    elif decision == "continue":
        updates["status"] = "scented"
    else:
        # Unknown decision defaults to escalation for safety.
        updates["review_decision"] = "escalate"
        updates["status"] = "escalation"

    return updates
