"""Confidence ordinal for WolfPack agents."""

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
    def _missing_(cls, value: object) -> "Confidence | None":
        if isinstance(value, int) and 1 <= value <= 5:
            return cls(value)
        return None
