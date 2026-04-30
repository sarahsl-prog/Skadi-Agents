# Confidence Anchors

WolfPack agents assign a **confidence ordinal** (1-5) to every hypothesis.
This document provides concrete examples for each level and explains how
the :func:`wolfpack.schemas.confidence.calibrate` helper adjusts raw
confidence based on evidence volume and corroboration.

## Scale

| Level | Name | Anchor | Example |
|-------|------|--------|---------|
| 1 | COINCIDENCE | Signal matches but no causal link | An IP from a threat feed appears in firewall logs, but only as outbound DNS |
| 2 | WEAK | Possible connection, thin evidence | A single EDR alert for suspicious PowerShell on a host with no other indicators |
| 3 | PLAUSIBLE | Multiple indicators align | Firewall blocks + EDR alert + Okta anomalous login from same user within 1 hour |
| 4 | STRONG | Corroborating evidence from independent sources | Firewall blocks on port 4444, EDR detects Cobalt Strike beacon, threat intel confirms IP is C2 |
| 5 | HIGH_FIDELITY | Direct observation or high-confidence telemetry match | Live memory analysis confirms malware injection; MITRE ATT&CK technique ID matches with 95% rule fidelity |

## Calibration

The :func:`calibrate` helper upgrades (never downgrades) raw confidence:

- **Evidence count boost:**
  - >= 5 distinct evidence items → +2
  - >= 3 distinct evidence items → +1

- **Corroboration boost:**
  - `independent` (3+ independent telemetry sources) → +2
  - `multiple` (2+ sources) → +1
  - `single` → 0
  - `none` → -1

The result is clamped to [1, 5].

### Example

```python
from wolfpack.schemas.confidence import Confidence, calibrate

# Raw confidence from single EDR alert
raw = Confidence.WEAK  # 2

# After gathering firewall + Okta + threat intel
calibrated = calibrate(raw, evidence_count=4, corroboration_level="independent")
# 2 + 1 (count) + 2 (independent) = 5 → HIGH_FIDELITY
```

## Analyst Agreement Proxy

In the evaluation harness, "analyst agreement" is approximated by
**confidence error** — the absolute difference between the Tracker's
assigned confidence and the golden-set's expert-assessed confidence.
An error of 0 means perfect agreement; errors > 1 suggest the agent is
over- or under-confident relative to human analysts.
