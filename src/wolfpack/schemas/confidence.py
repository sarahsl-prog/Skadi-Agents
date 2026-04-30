"""Confidence ordinal for WolfPack agents."""

from __future__ import annotations

from enum import IntEnum


class Confidence(IntEnum):
    """Ordinal confidence scale with written anchors.

    Anchors:
        1 — Coincidence: the signal matches but no causal link is apparent.
        2 — Weak: a possible connection, but evidence is thin or single-source.
        3 — Plausible: multiple indicators align; the hypothesis is reasonable.
        4 — Strong: corroborating evidence from independent sources.
        5 — High-fidelity: direct observation or high-confidence telemetry match.
    """

    COINCIDENCE = 1
    WEAK = 2
    PLAUSIBLE = 3
    STRONG = 4
    HIGH_FIDELITY = 5

    @classmethod
    def _missing_(cls, value: object) -> Confidence | None:
        if isinstance(value, int) and 1 <= value <= 5:
            return cls(value)
        return None


def calibrate(
    confidence: Confidence,
    evidence_count: int,
    corroboration_level: str,
) -> Confidence:
    """Adjust a raw confidence based on evidence volume and corroboration.

    Args:
        confidence: Initial agent-assessed confidence.
        evidence_count: Number of distinct evidence items gathered.
        corroboration_level: One of ``none``, ``single``, ``multiple``,
            ``independent``.

    Returns:
        A possibly upgraded (never downgraded) confidence.
    """
    level = corroboration_level.lower()

    # Evidence count boost
    if evidence_count >= 5:
        count_boost = 2
    elif evidence_count >= 3:
        count_boost = 1
    else:
        count_boost = 0

    # Corroboration boost
    if level == "independent":
        corr_boost = 2
    elif level == "multiple":
        corr_boost = 1
    elif level == "single":
        corr_boost = 0
    else:
        corr_boost = -1

    new_value = int(confidence) + count_boost + corr_boost
    new_value = max(1, min(5, new_value))
    return Confidence(new_value)
