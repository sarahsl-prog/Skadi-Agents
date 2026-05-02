"""Tracker agent — the first real intelligence node in the hunt graph.

Tracker ingests a :class:`CaseState`, queries threat-intel RAG and
Tier-1 telemetry adapters, and produces a ranked list of hypotheses
with calibrated confidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from wolfpack.adapters.base import TimeWindow
from wolfpack.adapters.tools import AdapterDeps
from wolfpack.llm.factory import get_model
from wolfpack.observability.agents import traced_agent_run
from wolfpack.rag.tools import RAGDeps, case_history_tool, threat_intel_tool
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.hypothesis import Hypothesis

# ------------------------------------------------------------------ #
# Models
# ------------------------------------------------------------------ #


class TrackerInput(BaseModel):
    """What the Tracker knows at invocation time."""

    case_id: str = Field(..., description="Owning case identifier.")
    entities: list[Entity] = Field(..., description="Entities to investigate.")
    time_window: TimeWindow = Field(
        default_factory=lambda: TimeWindow(
            start=datetime.now(UTC) - timedelta(hours=24),
            end=datetime.now(UTC),
        ),
        description="Look-back window for telemetry queries.",
    )
    seed_description: str = Field(
        default="", description="Free-text seed from the analyst."
    )


from wolfpack.schemas.agents.tracker import TrackerOutput


# ------------------------------------------------------------------ #
# Dependencies
# ------------------------------------------------------------------ #


class TrackerDeps:
    """Runtime dependencies injected into the Tracker agent."""

    def __init__(
        self,
        rag: RAGDeps | None = None,
        adapters: AdapterDeps | None = None,
        model_name: str = "ollama/llama3.2",
    ) -> None:
        self.rag = rag
        self.adapters = adapters
        self.model_name = model_name


# ------------------------------------------------------------------ #
# Tool allowlist
# ------------------------------------------------------------------ #

TRACKER_TOOL_ALLOWLIST = frozenset(
    {
        "threat_intel_tool",
        "case_history_tool",
        "syslog_query",
        "windows_eventlog_query",
        "crowdstrike_query",
        "okta_query",
        "firewall_query",
    }
)


def _validate_tools(tools: list[Any]) -> None:
    """Raise RuntimeError if any tool name is outside the Tracker allowlist."""
    for tool in tools:
        name = getattr(tool, "__name__", str(tool))
        if name not in TRACKER_TOOL_ALLOWLIST:
            raise RuntimeError(
                f"Tool '{name}' is not in the Tracker allowlist. "
                f"Allowed: {sorted(TRACKER_TOOL_ALLOWLIST)}"
            )


# ------------------------------------------------------------------ #
# Agent definition
# ------------------------------------------------------------------ #

_SYSTEM_PROMPT = """You are the Tracker agent in a SOC multi-agent system.

Your job is to investigate the entities provided by the analyst, query
threat intelligence and telemetry sources, and produce 1-3 concise
hypotheses with calibrated confidence.

Rules:
1. Always query threat_intel_tool for ATT&CK / CVE context.
2. Query relevant telemetry adapters (syslog, firewall, EDR, etc.).
3. Summarize findings as hypotheses with clear reasoning.
4. Calibrate confidence using the evidence_count and source_diversity.
   - Low evidence or single source → COINCIDENCE (1) or WEAK (2)
   - Multiple corroborating sources → PLAUSIBLE (3) or STRONG (4)
   - Direct observation + intel match → HIGH_FIDELITY (5)
5. Return your output as structured JSON matching TrackerOutput.
"""


def _build_tracker_agent(
    cfg: Any | None = None,
    model: Any | None = None,
) -> Agent[Any, TrackerOutput]:
    """Build the Tracker Pydantic AI agent with tools and system prompt."""
    if model is None:
        from wolfpack.config.settings import LLMConfig

        if cfg is None:
            cfg = LLMConfig(
                provider="ollama", model="llama3.2", base_url="http://localhost:11434"
            )
        model = get_model(cfg)

    rag_tools: list[Any] = [
        threat_intel_tool,
        case_history_tool,
    ]
    adapter_tools: list[Any] = []
    _validate_tools(rag_tools)

    agent = Agent(
        model=model,
        output_type=TrackerOutput,
        system_prompt=_SYSTEM_PROMPT,
        tools=rag_tools + adapter_tools,
    )
    return agent


# ------------------------------------------------------------------ #
# Public entry point (graph node)
# ------------------------------------------------------------------ #


async def run_tracker(
    state: CaseState,
    deps: TrackerDeps | None = None,
    model: Any | None = None,
) -> dict[str, Any]:
    """Async graph node — runs the Tracker agent against *state*.

    Returns a dict that LangGraph merges into :class:`CaseState`:
    - ``hypotheses``
    - ``evidence_refs``
    - ``tracker_confidence``
    - ``status = "shadowing"``
    """
    if deps is None:
        deps = TrackerDeps()

    # Build input from case seed
    seed = state.seed
    entities = seed.raw_payload.get("entities", []) if isinstance(seed.raw_payload, dict) else []
    if not entities and state.branches:
        # Fallback: use entities from the root branch
        entities = [
            e.model_dump() for b in state.branches for e in b.entities
        ]

    time_window = TimeWindow(
        start=datetime.now(UTC) - timedelta(hours=24),
        end=datetime.now(UTC),
    )

    tracker_input = TrackerInput(
        case_id=state.case_id,
        entities=[Entity.model_validate(e) if isinstance(e, dict) else e for e in entities],
        time_window=time_window,
        seed_description=str(seed.raw_payload),
    )

    agent = _build_tracker_agent(model=model)
    result = await traced_agent_run(
        "tracker",
        agent,
        f"Investigate case {tracker_input.case_id}. Entities: {tracker_input.entities}",
        deps=deps,
    )

    output = result.output

    return {
        "hypotheses": [h.model_dump() for h in output.hypotheses],
        "evidence_refs": [e.model_dump() for e in output.evidence_refs],
        "tracker_confidence": output.tracker_confidence,
        "status": "shadowing",
        "reasoning": output.reasoning,
    }
