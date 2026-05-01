"""Pydantic AI tools for RAG retrieval.

Each tool returns a :class:`RAGResult` with sanitised content to prevent
prompt-injection via retrieved documents.
"""

from __future__ import annotations

import html
import re

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from wolfpack.observability.rag_tools import traced_retrieve
from wolfpack.rag.base import RAGDocument
from wolfpack.rag.case_history import CaseHistoryPipeline
from wolfpack.rag.threat_intel import ThreatIntelPipeline


class RAGResult(BaseModel):
    """Sanitised result from a RAG query."""

    source: str = Field(..., description="Pipeline name: threat_intel or case_history.")
    documents: list[RAGDocument] = Field(default_factory=list)
    answer: str = Field(
        default="",
        description="Concatenated, sanitised document contents with explicit delimiters.",
    )


def _strip_markdown_links(text: str) -> str:
    """Remove markdown hyperlink syntax ``[text](url)``."""
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)


def _strip_html_tags(text: str) -> str:
    """Strip HTML tags and decode entities."""
    text = re.sub(r"<[^>]*>", "", text)
    return html.unescape(text)


def _strip_javascript(text: str) -> str:
    """Remove ``<script>`` blocks and ``javascript:`` pseudo-URLs."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"javascript:", "", text, flags=re.IGNORECASE)
    return text


def _instruction_repetition_defense(text: str) -> str:
    """Escape phrases that look like nested instructions.

    Wraps patterns such as ``ignore previous instructions`` or
    ``system prompt:`` in back-ticks so the LLM treats them as
    literals rather than directives.
    """
    patterns = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"system\s+prompt\s*:",
        r"you\s+are\s+now\s+",
        r"disregard\s+(all\s+)?prior\s+context",
    ]
    for pat in patterns:
        text = re.sub(pat, lambda m: f"`{m.group(0)}`", text, flags=re.IGNORECASE)
    return text


def _sanitize(text: str) -> str:
    """Sanitise a single document chunk for safe LLM consumption."""
    text = _strip_javascript(text)
    text = _strip_html_tags(text)
    text = _strip_markdown_links(text)
    text = _instruction_repetition_defense(text)
    # Collapse excessive whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_answer(docs: list[RAGDocument]) -> str:
    """Concatenate documents with explicit delimiters."""
    parts: list[str] = []
    for i, doc in enumerate(docs, start=1):
        parts.append(f"--- DOCUMENT {i} (id={doc.id}) ---")
        parts.append(_sanitize(doc.content))
        if doc.metadata:
            parts.append(f"metadata: {doc.metadata}")
        parts.append("")
    return "\n".join(parts)


class RAGDeps:
    """Dependencies injected into RAG tools."""

    def __init__(
        self,
        threat_intel: ThreatIntelPipeline | None = None,
        case_history: CaseHistoryPipeline | None = None,
    ) -> None:
        self.threat_intel = threat_intel
        self.case_history = case_history


async def threat_intel_tool(
    ctx: RunContext[RAGDeps],
    query: str,
    top_k: int = 5,
) -> RAGResult:
    """Query the threat-intel RAG pipeline.

    Returns sanitised ATT&CK descriptions, CVE summaries, and IOC
    records relevant to *query*.
    """
    pipeline = ctx.deps.threat_intel
    if pipeline is None:
        return RAGResult(source="threat_intel", answer="")
    docs = await traced_retrieve("threat_intel", pipeline.retrieve)(query, top_k=top_k)
    return RAGResult(
        source="threat_intel",
        documents=docs,
        answer=_build_answer(docs),
    )


async def case_history_tool(
    ctx: RunContext[RAGDeps],
    query: str,
    top_k: int = 5,
) -> RAGResult:
    """Query the case-history RAG pipeline.

    Returns sanitised summaries of past closed cases relevant to
    *query*.
    """
    pipeline = ctx.deps.case_history
    if pipeline is None:
        return RAGResult(source="case_history", answer="")
    docs = await traced_retrieve("case_history", pipeline.retrieve)(query, top_k=top_k)
    return RAGResult(
        source="case_history",
        documents=docs,
        answer=_build_answer(docs),
    )
