# Skadi-Agents (WolfPack) — Claude Code Harness

## Harness

**Goal:** Coordinate specialist agents to build the WolfPack SOC multi-agent system phase-by-phase.

**Trigger:** For any implementation task in this project (Python modules, infra, tests, security, CI), use the `wolfpack-orchestrator` skill. Simple questions can be answered directly.

**Specialists:**
- `wolfpack-backend` — `src/wolfpack/` Python modules (config, LLM, agents, schemas, RAG)
- `wolfpack-devops` — Docker Compose, infra configs, justfile, GitHub Actions
- `wolfpack-security` — prompt injection, tool allowlists, PII, audit trail
- `wolfpack-tester` — pytest, testcontainers, mypy, eval golden set

**Change History:**
| Date | Change | Target | Reason |
|------|--------|--------|--------|
| 2026-04-18 | Initial harness | All | Phase 0 development start |
