---
name: wolfpack-orchestrator
description: Main orchestrator for WolfPack/Skadi SOC agent system development. Use for ANY implementation task in this project: wolfpack Python modules, LangGraph orchestration, Pydantic AI agents (Alpha Dispatcher/Tracker/Flanker/Closer/Scribe), Docker infra, NATS/Postgres/OTel/MLflow/Ollama config, pytest tests, mypy, testcontainers, security review, CI/CD. Triggers on: implementing a phase, adding a module, writing tests, reviewing security, updating infra, configuring services, fixing bugs in wolfpack code. Also triggers on: "implement phase N", "add the X agent", "wire up Y", "set up Z service", re-runs, updates, and follow-up work.
---

# WolfPack Orchestrator

Routes work across specialist agents: **backend** (Python/wolfpack modules), **devops** (infra/CI), **security** (audit), and **tester** (pytest/mypy).

## Phase 0: Context Check

Before routing any task, determine execution mode:

1. Check `_workspace/` — if it exists and the user asks for partial changes, **partial re-run** (call only the relevant specialist).
2. Check `_workspace/` + new user input → **new run** (rename `_workspace/` to `_workspace_prev/`).
3. No `_workspace/` → **initial run**.

## Phase Map

| Phase | Status | Content |
|-------|--------|---------|
| 0 | **Current** | Toolchain, config, LLM factory, Docker, observability, smoke test, CI |
| 1 | Planned | Pydantic schemas, Postgres schema, hash-chain, crypto-shredding |
| 2 | Planned | LangGraph orchestration skeleton, NATS consumers |
| 3 | Planned | Tracker + Haystack RAG + Tier-1 telemetry adapters |
| 4 | Planned | Flanker + branching + Tier-2 adapters |
| 5 | Planned | Closer + Analyst Review UI |
| 6 | Planned | OTel hardening, MLflow dashboards |
| 7 | Planned | Learning loop |
| 8 | Planned | V1 release hardening |

## Routing Matrix

| Task type | Specialists | Mode |
|-----------|-------------|------|
| Single Python module | `wolfpack-backend` | Subagent |
| Module + its tests | `wolfpack-backend`, `wolfpack-tester` | Subagent (parallel) |
| Infra only | `wolfpack-devops` | Subagent |
| Security audit | `wolfpack-security` | Subagent |
| Full phase implementation | All relevant specialists | Agent team |
| Agent tool or RAG pipeline | `wolfpack-backend` + `wolfpack-security` | Subagent (sequential: backend → security) |

## Execution Mode: Subagent (default)

For most tasks, spawn specialists directly:

```
Agent(
    subagent_type="general-purpose",
    model="opus",
    prompt="[agent-name agent definition content] + [task details]"
)
```

Run backend + tester in parallel when both are needed for the same module.

## Execution Mode: Agent Team (phase-level work)

For full phase implementations spanning 3+ files across concerns:

1. `TeamCreate` with the relevant specialists
2. `TaskCreate` with dependencies (backend tasks before tester tasks)
3. Specialists coordinate via `SendMessage`
4. Collect results, write `_workspace/` summary

## Workspace Conventions

- Intermediate outputs: `_workspace/{phase}_{specialist}_{artifact}.md`
- Final outputs: written directly to the project tree
- Never delete `_workspace/` — it's the audit trail for the session

## Data Flow

```
User request
    → Context check (_workspace/)
    → Routing decision
    → Specialist agent(s)
        → Backend: src/wolfpack/ Python files
        → DevOps: docker-compose.yml, infra/, .github/, justfile
        → Security: findings report → back to backend for fixes
        → Tester: tests/ files
    → Integration check (do outputs connect?)
    → Report to user
```

## Error Handling

- If a specialist fails, report what was completed and what remains. Don't retry silently.
- Security findings: Critical/High block the task. Medium/Low are reported but don't block.
- If backend + tester outputs conflict (e.g., test imports wrong module path), fix before reporting complete.

## Test Scenarios

**Normal flow**: "Implement the config module for Phase 0" → backend writes `config/settings.py`, `config/deployment.py`, `config/validators.py` → tester writes `tests/unit/test_config.py` → report complete.

**Error flow**: "Set up the Docker stack" → devops writes `docker-compose.yml` → healthcheck is missing → devops fixes before reporting.
