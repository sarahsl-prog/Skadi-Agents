"""Hypothesis deduplication for the hunt orchestrator.

Uses cosine similarity on simple word-frequency vectors to detect
near-duplicate hypotheses and merge them.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from wolfpack.schemas.hypothesis import Hypothesis


def _tokenize(text: str) -> list[str]:
    """Lower-case, alphanumeric tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _vectorize(tokens: list[str]) -> Counter[str]:
    return Counter(tokens)


def _cosine_similarity(a: Counter[str], b: Counter[str]) -> float:
    """Cosine similarity of two token-frequency counters."""
    if not a or not b:
        return 0.0
    dot = sum(a[token] * b[token] for token in a if token in b)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _merge_hypotheses(existing: Hypothesis, new: Hypothesis) -> Hypothesis:
    """Merge *new* into *existing*, upgrading confidence and combining refs."""
    # Keep the longer, more detailed description
    description = existing.description
    if len(new.description) > len(description):
        description = new.description

    # Use the higher confidence
    confidence = existing.confidence
    if new.confidence > confidence:
        confidence = new.confidence

    # Deduplicate evidence refs by source_id
    seen = {ref.source_id for ref in existing.evidence_refs}
    combined_refs = list(existing.evidence_refs)
    for ref in new.evidence_refs:
        if ref.source_id not in seen:
            combined_refs.append(ref)
            seen.add(ref.source_id)

    return Hypothesis(
        description=description,
        confidence=confidence,
        evidence_refs=combined_refs,
        status=existing.status,
        branch_id=existing.branch_id,
    )


def hypothesis_dedup(
    existing: list[Hypothesis],
    new: Hypothesis,
    threshold: float = 0.85,
) -> Hypothesis | None:
    """Check whether *new* is a duplicate of any hypothesis in *existing*.

    Args:
        existing: Previously created hypotheses.
        new: Candidate hypothesis.
        threshold: Cosine-similarity threshold above which hypotheses are merged.

    Returns:
        The merged :class:`Hypothesis` if a duplicate was found,
        otherwise ``None`` (the caller should treat *new* as distinct).
    """
    new_vec = _vectorize(_tokenize(new.description))
    for old in existing:
        old_vec = _vectorize(_tokenize(old.description))
        sim = _cosine_similarity(new_vec, old_vec)
        if sim >= threshold:
            return _merge_hypotheses(old, new)
    return None
