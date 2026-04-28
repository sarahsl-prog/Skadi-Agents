"""LangGraph graph state derived from Pydantic models.

Modern LangGraph supports passing Pydantic ``BaseModel`` instances
directly as graph state, which avoids hand-maintained duplication
between domain models and graph ``TypedDict`` definitions.

This module re-exports the canonical graph state type so that the
orchestrator layer has a single import target.
"""

from wolfpack.schemas.case_state import CaseState

GraphState = CaseState

__all__ = ["GraphState"]
