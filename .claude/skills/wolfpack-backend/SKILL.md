---
name: wolfpack-backend
description: Python implementation skill for wolfpack package modules. Use when writing or modifying any .py file under src/wolfpack/: config (settings, deployment mode), LLM factory (providers, factory, errors), observability (OTel, Logfire), smoke CLI, schemas (Pydantic domain models), orchestrator (LangGraph nodes), agents (Pydantic AI), RAG (Haystack), adapters (TelemetrySource). Also triggers on: implementing a wolfpack module, fixing a mypy error in wolfpack, adding a new agent class, wiring LangGraph nodes, Phase 0/1/2/3/4 Python implementation work.
---

# WolfPack Backend Implementation

## Phase 0 Priority Checklist

Work in this order — each item builds on the previous:

1. `config/deployment.py` — `DeploymentMode` enum + `is_loopback_or_private()`
2. `config/settings.py` — `LLMConfig`, `PostgresConfig`, `NATSConfig`, `OTelConfig`, `MLflowConfig`, `Settings` root with airgapped validator
3. `config/validators.py` — shared validator helpers
4. `llm/errors.py` — `LLMConfigError`
5. `llm/providers.py` — `OllamaProvider`, `OpenAICompatibleProvider`
6. `llm/factory.py` — `get_model(cfg: LLMConfig) -> Model`
7. `observability/tracing.py` — OTel `TracerProvider` bootstrap
8. `observability/logfire.py` — Logfire → OTel wire
9. `smoke/hello_pack.py` — Typer CLI smoke test

## Implementation Rules

**Imports**: Use `from __future__ import annotations` at the top of every file. Import `pydantic_ai` not `pydantic-ai`.

**Settings pattern**: `BaseSettings` with `SettingsConfigDict(env_file=".env", env_nested_delimiter="__")`. Every config field has a default or `Field(description="...")`.

**Airgapped enforcement**: The `@model_validator(mode="after")` on `Settings` must check both `llm.hosted` and `is_loopback_or_private(llm.base_url)`. Fail at config load, not at first use.

**LLM factory**: `get_model()` is a pure function. It accepts `LLMConfig`, constructs the Pydantic AI model, and returns it. No env reads, no side effects.

**OTel resource attributes** (every span must carry):
- `service.name`: `wolfpack-{component}` (e.g., `wolfpack-smoke`, `wolfpack-tracker`)
- `service.namespace`: `wolfpack`
- `deployment.environment`: mirrors `deployment_mode` string value
- Phase 2+: `wolfpack.case_id`, `wolfpack.branch_id`, `wolfpack.agent_run_id` as baggage

**Smoke test**: Typer CLI. Loads `Settings`, calls `init_tracing()`, calls `configure_logfire()`, builds a model via `get_model()`, runs a trivial Pydantic AI agent (`Greeting` output model), prints trace ID + MLflow URL.

## Phase 1+ Patterns

**Schema canonical form**: Define all domain models in `schemas/` as Pydantic `BaseModel`. Derive LangGraph `TypedDict` via:
```python
from typing import get_type_hints
# or pass Pydantic model directly to LangGraph (modern API supports this)
```

**Confidence ordinal**: `Confidence(IntEnum)` with values 1–5. Written anchors as class docstring, not comments.

**Hash-chain ledger**: Append-only. Rows have `prev_hash: str`, `content_hash: str`. Computed by Postgres trigger on insert. Python code never computes these — it writes the content, Postgres handles hashing.

**TelemetrySource interface** (Phase 3):
```python
class TelemetrySource(Protocol):
    async def query(
        self, entity: Entity, time_window: TimeWindow, filters: dict[str, Any]
    ) -> list[Event]: ...
```

## Type Safety

- All functions: explicit return type annotations
- Prefer `Literal["ollama", "openai_compatible"]` over `str` for discriminated fields
- `SecretStr` for all credentials — never `str`
- No `Any` except at true system boundaries (raw JSON from external APIs)

## Output Format

Produce complete, importable Python files. Files must:
- Pass `mypy --strict`
- Pass `ruff check` and `ruff format`
- Have no placeholder `pass` statements (except empty `__init__.py`)
- Have no TODO comments unless explicitly requested
