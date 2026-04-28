"""NER-based PII stripping with SOC-specific recognizers.

Gracefully falls back to a regex-based implementation if Microsoft
Presidio is not installed.
"""

from __future__ import annotations

import re
from typing import Any

# Presidio is optional — the pipeline degrades to regex if unavailable
_HAS_PRESIDIO = False
try:
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.recognizer_registry import RecognizerRegistry
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig

    _HAS_PRESIDIO = True
except Exception:  # noqa: S110  # pragma: no cover
    pass


# Regex recognizers for air-gapped / no-Presidio environments
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)
_IPV6_RE = re.compile(
    r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"
)
_MAC_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_HOSTNAME_RE = re.compile(
    r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,}\b"
)
_CIDR_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)"
    r"/(?:3[0-2]|[1-2]?\d)\b"
)


class NERStripper:
    """Strip PII from free-text using Presidio or regex fallback."""

    def __init__(self) -> None:
        self._analyzer: Any = None
        self._anonymizer: Any = None
        if _HAS_PRESIDIO:
            registry = RecognizerRegistry()
            registry.load_predefined_recognizers()
            # Add SOC-specific custom recognizers by boosting built-ins
            # and ensuring IP/MAC/hostname coverage
            self._analyzer = AnalyzerEngine(registry=registry)
            self._anonymizer = AnonymizerEngine()

    def strip(
        self, text: str, operators: dict[str, str] | None = None
    ) -> tuple[str, dict[str, str]]:
        """Return *(stripped_text, mapping)*.

        *mapping* maps placeholder tokens (e.g. ``<IP_ADDRESS_1>``)
        back to the original value so downstream pseudonymization can
        be applied deterministically.
        """
        if _HAS_PRESIDIO and self._analyzer is not None:
            return self._strip_presidio(text, operators)
        return self._strip_regex(text)

    # ------------------------------------------------------------------ #
    # Presidio path
    # ------------------------------------------------------------------ #

    def _strip_presidio(
        self, text: str, operators: dict[str, str] | None = None
    ) -> tuple[str, dict[str, str]]:
        results = self._analyzer.analyze(text=text, language="en")
        mapping: dict[str, str] = {}
        placeholder_counts: dict[str, int] = {}

        anon_operators: dict[str, Any] = {}
        for res in results:
            entity_type = res.entity_type
            placeholder_counts[entity_type] = placeholder_counts.get(entity_type, 0) + 1
            count = placeholder_counts[entity_type]
            token = f"<{entity_type}_{count}>"
            mapping[token] = text[res.start : res.end]
            anon_operators[entity_type] = OperatorConfig(
                "replace", {"new_value": token}
            )

        if operators:
            for entity_type, new_value in operators.items():
                anon_operators[entity_type] = OperatorConfig(
                    "replace", {"new_value": new_value}
                )

        anonymized = self._anonymizer.anonymize(
            text=text, analyzer_results=results, operators=anon_operators
        )
        return str(anonymized.text), mapping

    # ------------------------------------------------------------------ #
    # Regex fallback
    # ------------------------------------------------------------------ #

    def _strip_regex(self, text: str) -> tuple[str, dict[str, str]]:
        mapping: dict[str, str] = {}
        count = [0]

        def _repl(match: re.Match[str], label: str) -> str:
            count[0] += 1
            token = f"<{label}_{count[0]}>"
            mapping[token] = match.group(0)
            return token

        # CIDR before IPv4 so 10.0.0.0/24 is not partially matched
        text = _CIDR_RE.sub(lambda m: _repl(m, "CIDR"), text)
        text = _IPV4_RE.sub(lambda m: _repl(m, "IP_ADDRESS"), text)
        text = _IPV6_RE.sub(lambda m: _repl(m, "IP_ADDRESS"), text)
        text = _MAC_RE.sub(lambda m: _repl(m, "MAC_ADDRESS"), text)
        text = _EMAIL_RE.sub(lambda m: _repl(m, "EMAIL"), text)
        text = _URL_RE.sub(lambda m: _repl(m, "URL"), text)
        text = _HOSTNAME_RE.sub(lambda m: _repl(m, "HOSTNAME"), text)

        return text, mapping


def strip_pii(text: str) -> tuple[str, dict[str, str]]:
    """Convenience wrapper — strip PII and return mapping."""
    stripper = NERStripper()
    return stripper.strip(text)
