"""Closer agent — assembles verdict packets for analyst review.

Closer reads the full case state, all branches, hypotheses, and evidence,
then produces a structured :class:`CloserOutput` verdict packet.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from wolfpack.adapters.tools import AdapterDeps, build_adapter_tools
from wolfpack.agents.policy import PolicyEngine
from wolfpack.llm.factory import get_model
from wolfpack.observability.agents import traced_agent_run
from wolfpack.observability.rag_tools import traced_retrieve
from wolfpack.rag.tools import (
    RAGDeps,
    RAGResult,
    _build_answer,
    case_history_tool,
    threat_intel_tool,
)
from wolfpack.schemas.agents.closer import CloserInput, CloserOutput
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.verdict import BranchSummary, VerdictPacket

# ------------------------------------------------------------------ #
# Tool allowlist
# ------------------------------------------------------------------ #

CLOSER_TOOL_ALLOWLIST = frozenset(
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


# ------------------------------------------------------------------ #
# Dependencies
# ------------------------------------------------------------------ #


class CloserDeps:
    """Runtime dependencies injected into the Closer agent."""

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
# System prompt
# ------------------------------------------------------------------ #

_SYSTEM_PROMPT = """You are the Closer agent in a SOC multi-agent system.

Your job is to assemble a verdict packet from the full case state,
hypotheses, and evidence collected during the hunt.

Rules:
1. Review all case hypotheses and evidence.
2. Query threat_intel_tool and case_history_tool if you need extra context.
3. Make a final decision: MALICIOUS, BENIGN, INCONCLUSIVE, or NEEDS_MORE_INFO.
4. Set confidence based on evidence volume and corroboration.
5. Provide a concise reasoning_summary.
6. List supporting evidence_refs.
7. Return structured JSON matching CloserOutput.
"""


# ------------------------------------------------------------------ #
# Tool factory
# ------------------------------------------------------------------ #


def _build_tools(
    deps: CloserDeps | None = None,
    feature_flags: dict[str, bool] | None = None,
) -> list[Any]:
    """Build the tool list for Closer (read-only Tier-1 adapters only).

    When *deps* provides ``rag`` or ``adapters``, those are wired into
    the tools instead of creating fresh instances.
    """
    tools: list[Any] = []

    # ------------------------------------------------------------------ #
    # RAG tools — wire deps.rag when available
    # ------------------------------------------------------------------ #
    rag = deps.rag if deps else None
    if rag is not None:

        async def _threat_intel(query: str, top_k: int = 5) -> Any:
            pipeline = rag.threat_intel
            if pipeline is None:
                return RAGResult(source="threat_intel", answer="")
            docs = await traced_retrieve("threat_intel", pipeline.retrieve)(query, top_k=top_k)
            return RAGResult(
                source="threat_intel",
                documents=docs,
                answer=_build_answer(docs),
            )

        _threat_intel.__name__ = "threat_intel_tool"
        _threat_intel.__doc__ = threat_intel_tool.__doc__
        tools.append(_threat_intel)

        async def _case_history(query: str, top_k: int = 5) -> Any:
            pipeline = rag.case_history
            if pipeline is None:
                return RAGResult(source="case_history", answer="")
            docs = await traced_retrieve("case_history", pipeline.retrieve)(query, top_k=top_k)
            return RAGResult(
                source="case_history",
                documents=docs,
                answer=_build_answer(docs),
            )

        _case_history.__name__ = "case_history_tool"
        _case_history.__doc__ = case_history_tool.__doc__
        tools.append(_case_history)
    else:
        tools.extend([threat_intel_tool, case_history_tool])

    # ------------------------------------------------------------------ #
    # Adapter tools — wire deps.adapters when available
    # ------------------------------------------------------------------ #
    adapter_deps = deps.adapters if deps else None
    if adapter_deps is not None and adapter_deps.adapters:
        adapter_tools = build_adapter_tools(
            list(adapter_deps.adapters.values()),
            feature_flags=feature_flags or {},
        )
    else:
        from wolfpack.adapters import (
            CrowdStrikeAdapter,
            FirewallAdapter,
            OktaAdapter,
            SyslogAdapter,
            WindowsEventLogAdapter,
        )

        adapter_tools = build_adapter_tools(
            [
                SyslogAdapter(),
                WindowsEventLogAdapter(),
                OktaAdapter(base_url="https://example.okta.com"),
                CrowdStrikeAdapter(),
                FirewallAdapter(),
            ],
            feature_flags=feature_flags or {},
        )

    for name, fn in adapter_tools.items():
        if name in CLOSER_TOOL_ALLOWLIST:
            tools.append(fn)
    return tools


# ------------------------------------------------------------------ #
# Agent builder
# ------------------------------------------------------------------ #


def _build_closer_agent(
    cfg: Any | None = None,
    model: Any | None = None,
    deps: CloserDeps | None = None,
    feature_flags: dict[str, bool] | None = None,
) -> Agent[Any, CloserOutput]:
    """Build the Closer Pydantic AI agent."""
    if model is None:
        from wolfpack.config.settings import LLMConfig

        if cfg is None:
            cfg = LLMConfig(provider="ollama", model="llama3.2", base_url="http://localhost:11434")
        model = get_model(cfg)

    tools = _build_tools(deps=deps, feature_flags=feature_flags)

    return Agent(
        model=model,
        output_type=CloserOutput,
        system_prompt=_SYSTEM_PROMPT,
        tools=tools,
    )


# ------------------------------------------------------------------ #
# Public entry point
# ------------------------------------------------------------------ #


async def run_closer(
    state: CaseState,
    deps: CloserDeps | None = None,
    model: Any | None = None,
    feature_flags: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Async graph node — runs the Closer agent against *state*.

    Returns a dict that LangGraph merges into :class:`CaseState`:
    - ``verdict_decision``
    - ``overall_confidence``
    - ``status = "review"``
    - ``verdict_packet`` (as a dict)
    """
    if deps is None:
        deps = CloserDeps()

    hypotheses = state.hypotheses
    evidence = state.evidence_refs

    closer_input = CloserInput(
        case_id=state.case_id,
        hypotheses=hypotheses,
        evidence_refs=evidence,
    )

    agent = _build_closer_agent(model=model, deps=deps, feature_flags=feature_flags)

    hyp_reprs = []
    for h in closer_input.hypotheses or []:
        desc = str(h.description).replace("\n", " ")[:1000]
        hyp_reprs.append(desc)
    hyp_str = "; ".join(hyp_reprs) if hyp_reprs else "None"

    prompt = (
        f"Assemble a verdict for case {closer_input.case_id}.\n\n"
        f"Hypotheses: {hyp_str}\n\n"
        f"Evidence count: {len(closer_input.evidence_refs)}\n\n"
        f"Return structured JSON matching CloserOutput."
    )

    result = await traced_agent_run(
        "closer",
        agent,
        prompt,
        deps=deps,
    )
    output = result.output

    # Build branch summaries
    branch_summaries = [
        BranchSummary(
            branch_id=b.branch_id,
            depth=b.spec.depth,
            hypothesis_summary=b.spec.hypothesis.description[:200] if b.spec.hypothesis else "",
            entity_count=len(b.entities),
            evidence_count=len(b.evidence_refs),
        )
        for b in state.branches
    ]

    verdict_packet = VerdictPacket(
        decision=output.decision,
        confidence=output.confidence,
        next_best_action=output.next_best_action,
        evidence_refs=output.evidence_refs,
        reasoning_summary=output.reasoning_summary,
        branch_summaries=branch_summaries,
    )

    # Evaluate policies
    policy_engine = PolicyEngine()
    policies = await policy_engine.evaluate(verdict_packet, state)
    verdict_packet.policy_applicable = [p.id for p in policies]

    return {
        "verdict_decision": output.decision,
        "overall_confidence": output.confidence,
        "status": "review",
        "verdict_packet": verdict_packet.model_dump(),
    }
