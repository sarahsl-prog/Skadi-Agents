# Phase 0 — Implementation Plan

**Goal:** a cloneable repo where `uv sync && pre-commit install && docker compose up` produces a running local stack, a smoke-test LLM call is traced end-to-end into MLflow, and CI enforces lint + typecheck + tests. No business logic yet — this phase is pure foundation.

**Duration target:** 1 working week (~7 engineer-days).

**Out of scope for Phase 0:** domain Pydantic models, Postgres schema, LangGraph nodes, Haystack pipelines, telemetry adapters. Those are Phase 1 onward.

## 1. Prerequisites

Before the phase starts:

- [ ] Repo is on GitHub (done — PR #1 scaffolding landed).
- [ ] Pre-commit + CI workflow are wired (done).
- [ ] A developer machine with Docker Desktop / colima and a GPU available for one Ollama smoke-test run (or a staging box with GPU access).
- [ ] Confirmed GitHub Actions is enabled on the repo.

## 2. Target Directory Layout

Recommend a `src/` layout (better test isolation than flat packages):

```
WolfPack-Agents/
├── .github/
│   └── workflows/
│       ├── pre-commit.yml       (already exists)
│       └── ci.yml               (new: mypy + pytest + build)
├── .pre-commit-config.yaml      (extend with mypy + pytest hooks)
├── pyproject.toml               (uv-managed, single source of tooling config)
├── uv.lock
├── justfile                     (common commands)
├── docker-compose.yml
├── docker-compose.override.yml.example
├── .env.example
├── README.md
├── LICENSE
├── docs/
│   ├── PROJECT_PLAN.md
│   └── PHASE_0_PLAN.md          (this file)
├── infra/
│   ├── postgres/
│   │   └── init.sql             (create pgvector extension, base roles)
│   ├── nats/
│   │   └── nats-server.conf     (JetStream enabled)
│   ├── otel/
│   │   └── otel-collector-config.yaml
│   ├── mlflow/
│   │   └── Dockerfile           (pinned MLflow + deps)
│   ├── ollama/
│   │   └── entrypoint.sh        (pulls default model on first boot)
│   └── sizing.md                (GPU sizing guide)
├── src/
│   └── wolfpack/
│       ├── __init__.py
│       ├── config/
│       │   ├── __init__.py
│       │   ├── settings.py      (pydantic-settings root)
│       │   ├── deployment.py    (DeploymentMode, guards)
│       │   └── validators.py
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── providers.py     (OllamaProvider, OpenAICompatibleProvider)
│       │   ├── factory.py       (get_model(config) -> pydantic_ai.Model)
│       │   └── errors.py
│       ├── observability/
│       │   ├── __init__.py
│       │   ├── tracing.py       (OTel bootstrap, resource attrs)
│       │   └── logfire.py       (wire Pydantic AI / Logfire into OTel)
│       ├── schemas/             (empty __init__ — Phase 1 fills)
│       ├── orchestrator/        (empty __init__ — Phase 2 fills)
│       ├── agents/              (empty __init__ — Phase 3+ fills)
│       ├── rag/                 (empty __init__ — Phase 3 fills)
│       ├── adapters/            (empty __init__ — Phase 3+ fills)
│       └── smoke/
│           ├── __init__.py
│           └── hello_pack.py    (one-shot traced LLM call)
└── tests/
    ├── unit/
    │   ├── test_config.py
    │   ├── test_deployment_guards.py
    │   └── test_llm_factory.py
    ├── integration/
    │   └── test_stack_up.py     (testcontainers-backed)
    └── conftest.py
```

## 3. Toolchain Choices

| Decision | Choice | Rationale |
|---|---|---|
| Package manager | **uv** | Materially faster than poetry; lockfile format is fine for on-prem; Astral maintains it alongside Ruff. |
| Python version | **3.11** | Matches pre-commit config; broad library compatibility; defer 3.12 until LangGraph/Haystack track it cleanly. |
| Task runner | **justfile** | Lighter than Make, no tabs-vs-spaces foot-guns, readable. |
| Test framework | **pytest + pytest-asyncio** | Required for async agent code; `pytest-cov` for coverage. |
| Integration tests | **testcontainers** | Spin Postgres/NATS/Ollama in CI without docker-compose state leaking across tests. |
| Type checker | **mypy (strict)** | Stricter than pyright-basic; better Pydantic plugin support for our heavy Pydantic use. |

## 4. Task Breakdown

Rough day-by-day cut — parallelizable where noted.

### Day 1 — Project scaffolding

- [ ] `uv init --package src/wolfpack`; populate `pyproject.toml` with runtime + dev deps:
  - Runtime: `pydantic>=2.7`, `pydantic-settings`, `pydantic-ai`, `langgraph`, `haystack-ai`, `httpx`, `nats-py`, `asyncpg`, `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, `opentelemetry-instrumentation-asyncpg`, `opentelemetry-instrumentation-httpx`, `logfire`, `mlflow`, `typer`.
  - Dev: `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`, `pre-commit`, `testcontainers[postgres,nats]`.
- [ ] Create empty `src/wolfpack/` package tree as laid out above.
- [ ] Configure Ruff (in `pyproject.toml`): select `E, F, I, B, UP, N, S, RUF`; ignore `S101` in tests.
- [ ] Configure mypy: `strict = true`, `plugins = ["pydantic.mypy"]`, `files = ["src", "tests"]`.
- [ ] Create `justfile` with `install`, `fmt`, `lint`, `typecheck`, `test`, `up`, `down`, `smoke`.
- [ ] Extend `.pre-commit-config.yaml` with `mypy` (local hook, uses project env) and a fast `pytest -q tests/unit` hook (optional, can be CI-only).

### Day 2 — Config module

- [ ] Implement `wolfpack.config.deployment`:
  - `DeploymentMode` enum (`DEV`, `ON_PREM_CONNECTED`, `ON_PREM_AIRGAPPED`).
  - `is_loopback_or_private(url: str) -> bool` helper.
- [ ] Implement `wolfpack.config.settings`:
  - `LLMConfig` (provider literal, base_url, model, api_key, hosted flag).
  - `PostgresConfig`, `NATSConfig`, `OTelConfig`, `MLflowConfig`.
  - `Settings` root, loaded from env + `.env`.
  - Root `model_validator` enforcing: in `ON_PREM_AIRGAPPED`, any config with `hosted=True` or a non-private `base_url` raises at load time.
- [ ] `.env.example` with every field documented.
- [ ] `tests/unit/test_config.py` — load valid configs per mode, assert airgapped refuses Ollama Cloud (`https://ollama.com`) and accepts `http://localhost:11434`.

### Day 3 — LLM abstraction

- [ ] Implement `wolfpack.llm.providers`:
  - `OllamaProvider` wrapping `pydantic_ai.models.ollama.OllamaModel` (same class serves local + cloud; discriminated by URL).
  - `OpenAICompatibleProvider` wrapping `pydantic_ai.models.openai.OpenAIModel` with a custom `base_url`.
- [ ] `wolfpack.llm.factory.get_model(config: LLMConfig) -> pydantic_ai.Model` — pure factory; never reads env directly.
- [ ] `wolfpack.llm.errors.LLMConfigError` raised for unsupported provider/model combos.
- [ ] `tests/unit/test_llm_factory.py` — parametric tests for each provider; network calls mocked via `httpx_mock` or `respx`.

### Day 4 — Docker Compose + infra

- [ ] `docker-compose.yml` services:
  - `postgres` → `pgvector/pgvector:pg16`; mount `infra/postgres/init.sql`; healthcheck `pg_isready`.
  - `nats` → `nats:2.10-alpine` with `-js -c /etc/nats/nats-server.conf`.
  - `otel-collector` → `otel/opentelemetry-collector-contrib:latest`; config mounted from `infra/otel/`.
  - `mlflow` → custom image from `infra/mlflow/Dockerfile` (tracking server + artifact store on local volume). Tagged with compose profile `full`; omitted by the default `minimal` profile used in CI.
  - `ollama` → `ollama/ollama:latest`; entrypoint pulls `llama3.2:1b` for CI-friendly smoke tests (swap to 70B per deployment).
- [ ] `docker-compose.override.yml.example` for GPU passthrough, custom model mounts.
- [ ] `infra/postgres/init.sql`: `CREATE EXTENSION IF NOT EXISTS vector;` plus a `wolfpack` role.
- [ ] `infra/nats/nats-server.conf`: JetStream enabled, `store_dir` mounted to a volume.
- [ ] `infra/otel/otel-collector-config.yaml`: OTLP receiver (gRPC + HTTP), processors (batch, memory_limiter), exporters (MLflow OTLP, `debug` for dev).
- [ ] Healthchecks and `depends_on: { condition: service_healthy }` ordering so the smoke test's `just up` doesn't race.

### Day 5 — Observability + smoke test

- [ ] `wolfpack.observability.tracing.init_tracing(settings)`:
  - Create OTel `TracerProvider` with resource attrs (`service.name=wolfpack`, `service.namespace`, `deployment.environment`).
  - OTLP exporter pointed at the collector from settings.
  - Configure trace propagation (W3C Trace Context).
- [ ] `wolfpack.observability.logfire.configure_logfire(settings)` — wire Logfire → OTel so Pydantic AI spans feed the collector.
- [ ] `wolfpack.smoke.hello_pack`:
  - Typer CLI (`just smoke`).
  - Loads settings, initializes tracing, builds a model via `get_model`, runs a trivial Pydantic AI agent (input: "who are you?" → a `Greeting` Pydantic model).
  - On completion, prints the trace ID and the MLflow URL the user can visit.
- [ ] `infra/sizing.md` — GPU sizing guide:
  - Reference: 1× H100/H200 80GB, Llama 3.3 70B FP8/BF16, ~60 tok/s agent throughput target.
  - Lightweight: 2× 48GB (L40S/A6000), Q4_K_M, clearly labeled as non-baseline.
  - CI/dev: `llama3.2:1b` on CPU (for the Day-4 smoke path).

### Day 6 — CI hardening

- [ ] `.github/workflows/ci.yml`:
  - Jobs: `lint` (already covered by pre-commit), `typecheck` (mypy), `test-unit` (pytest), `test-integration` (testcontainers; allowed to be slower + cached), `build` (`docker compose --profile minimal build`).
  - Integration tests use the `minimal` compose profile (no MLflow) per the Phase 0 decision.
  - Python matrix pinned to 3.11 (no matrix yet; keep it simple).
  - Use `astral-sh/setup-uv@v3` for fast dep install.
- [ ] Branch protection for `main` after PR #1 merges (not a code change — record as a follow-up checklist item for the owner).

### Day 7 — Polish + handoff

- [ ] Address findings from Days 1–6.
- [ ] README.md "Getting Started" section: clone → uv sync → pre-commit install → just up → just smoke.
- [ ] Phase 0 retro note appended to `docs/PROJECT_PLAN.md` under Phase 0 (actual effort, surprises, deviations).
- [ ] Open a Phase 1 tracking issue.

## 5. Key Design Details

### 5.1 Config model shape (illustrative)

```python
# src/wolfpack/config/settings.py
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from wolfpack.config.deployment import DeploymentMode, is_loopback_or_private

class LLMConfig(BaseModel):
    provider: Literal["ollama", "openai_compatible"]
    base_url: str
    model: str
    api_key: SecretStr | None = None
    hosted: bool = False  # e.g., Ollama Cloud → True
    request_timeout_s: float = 60.0

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")
    deployment_mode: DeploymentMode
    llm: LLMConfig
    postgres: PostgresConfig
    nats: NATSConfig
    otel: OTelConfig
    mlflow: MLflowConfig

    @model_validator(mode="after")
    def enforce_airgapped(self) -> "Settings":
        if self.deployment_mode is DeploymentMode.ON_PREM_AIRGAPPED:
            if self.llm.hosted:
                raise ValueError("hosted LLM providers forbidden in airgapped mode")
            if not is_loopback_or_private(self.llm.base_url):
                raise ValueError("LLM base_url must be loopback/private in airgapped mode")
        return self
```

The airgapped check is central — it's the mechanism that makes "pluggable LLM" safe to ship.

### 5.2 LLM factory shape (illustrative)

```python
# src/wolfpack/llm/factory.py
from pydantic_ai.models import Model
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import OpenAIModel

def get_model(cfg: LLMConfig) -> Model:
    match cfg.provider:
        case "ollama":
            return OllamaModel(cfg.model, base_url=cfg.base_url, api_key=cfg.api_key)
        case "openai_compatible":
            return OpenAIModel(cfg.model, base_url=cfg.base_url, api_key=cfg.api_key)
    raise LLMConfigError(f"unknown provider {cfg.provider}")
```

Kept deliberately thin — Pydantic AI already owns retry, tool-calling, and schema enforcement. Our layer is config validation, deployment-mode gating, and a place to hang future policy (budget enforcement, tool allowlists).

### 5.3 OTel resource attributes

Every span should carry:

- `service.name` — `wolfpack-<component>` (orchestrator, agents, rag, smoke).
- `service.namespace` — `wolfpack`.
- `deployment.environment` — mirrors `deployment_mode`.
- `wolfpack.case_id`, `wolfpack.branch_id`, `wolfpack.agent_run_id` — set as baggage later (Phase 2+), but the resource attrs must be consistent now.

## 6. Definition of Done

Phase 0 is done when **all** of these pass on a clean clone:

1. `uv sync` completes with no errors.
2. `pre-commit run --all-files` is green.
3. `just up` brings Postgres (with pgvector), NATS JetStream, OTel Collector, MLflow, and Ollama to healthy status.
4. `just smoke` runs a Pydantic AI agent via the factory, prints a trace ID, and the run is visible in MLflow at the URL printed.
5. `just test` runs unit tests green; `just test-integration` runs green in < 5 min on a 4-core machine.
6. CI (`pre-commit` + `ci`) is green on PR.
7. `docs/PHASE_0_PLAN.md` has a retro note with actual effort.
8. `.env.example`, `README.md` getting-started, and `infra/sizing.md` are readable by a new contributor without extra context.

Zero Phase-1 code lands here — package dirs for `schemas/`, `orchestrator/`, `agents/`, `rag/`, `adapters/` exist with only `__init__.py`.

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pydantic AI's `OllamaModel` / `OpenAIModel` API changes | Medium | Low | The factory layer isolates the blast radius; factory tests pin the expected surface. |
| OTel → MLflow bridge is immature | Medium | Medium | Start with OTel Collector's `debug` exporter as a fallback so dev unblocks; document the MLflow path as "best-effort V1" and keep Jaeger-slot config stub. |
| pgvector extension init race with app connects | Low | Low | Postgres `healthcheck` waits on `pg_isready`; init.sql runs before healthcheck passes. |
| Ollama container needs GPU for the real default model | High | Low | CI + local smoke use `llama3.2:1b`. Document the switch to 70B in `sizing.md`; real-model smoke is a staging-box task, not a laptop task. |
| `testcontainers` flaky in CI | Medium | Medium | Gate integration tests behind a `CI=true` or `RUN_INTEGRATION=1` env var; run nightly if PR latency becomes an issue. |
| Gitleaks false positives on example configs | Medium | Low | Commit a `.gitleaks.toml` allowlisting specific `.env.example` patterns if flagged. |

## 8. Phase 0 → Phase 1 Handoff Checklist

Before Phase 1 starts:

- [ ] Clean clone passes §6 definition-of-done items 1–6.
- [ ] A short "here's where things live" Loom or README walkthrough so Phase-1 contributors don't re-discover conventions.
- [ ] Issue filed with the four Phase-1 workstreams (schemas, Postgres migrations, hash-chain, crypto-shredding skeleton) referencing this doc's §5.
- [ ] The five remaining operational items from `PROJECT_PLAN.md` §7 are either resolved or explicitly deferred-past-Phase-1 (KMS choice is the only one that actually blocks Phase 1; the rest can slip to Phase 3+).

## 9. Phase 0 Decisions (resolved)

- **MLflow in CI: optional.** CI runs with the OTel Collector's `debug` exporter only — saves ~200 MB of container weight and several seconds per run. Local `just up` still brings MLflow by default; CI uses a compose profile (`--profile minimal`) that omits it.
- **Ollama model for CI/dev smoke: `llama3.2:1b`.** Fits on a laptop CPU, < 1 GB. Production deployments swap to Llama 3.3 70B Instruct per `infra/sizing.md`.
- **Project layout: `pyproject.toml` with PEP 621 `[project]` table** (uv-managed). No Poetry-style `[tool.poetry]` block.
