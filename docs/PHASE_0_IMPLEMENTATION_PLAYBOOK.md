# Phase 0 Implementation Playbook

This document turns [`PHASE_0_PLAN.md`](./PHASE_0_PLAN.md) into an execution-ready implementation plan. It keeps the original scope and definition of done, but adds sequencing, concrete deliverables, dependency order, and checkpoints based on the repo's current state on April 18, 2026.

## 1. Current Baseline

The repository already has:

- `README.md`
- `LICENSE`
- `.pre-commit-config.yaml`
- `.github/workflows/pre-commit.yml`
- `.github/workflows/blank.yml`
- planning documents and diagrams under `docs/`

The repository does not yet have the Phase 0 foundation:

- Python package scaffold under `src/`
- `pyproject.toml`, `uv.lock`, `justfile`, `.env.example`
- Docker Compose stack and `infra/` assets
- config, LLM, observability, or smoke-test modules
- unit or integration tests
- a real CI workflow for typecheck, tests, and build

That means Phase 0 should be executed as a foundation-first setup effort, not as an incremental refinement of existing application code.

## 2. Phase Objective

Deliver a clean clone experience where a contributor can run:

```bash
uv sync
pre-commit install
docker compose up
just smoke
```

and get:

- a healthy local infra stack
- a traced smoke-test LLM request
- observability wired through OpenTelemetry
- CI enforcing lint, typecheck, tests, and image build

No Phase 1 business logic should land during this work.

## 3. Execution Strategy

Use four implementation tracks, but land them in dependency order:

1. Repository and Python scaffold
2. Runtime config and LLM abstraction
3. Local infrastructure and observability wiring
4. CI, docs, and handoff

The critical path is:

1. establish the package/tooling scaffold
2. add validated settings models
3. add the model factory
4. bring up local services
5. wire tracing
6. prove the smoke path
7. harden CI and docs

## 4. Work Breakdown Structure

### Track A: Repository Scaffold and Tooling

Purpose: create the base Python project and developer workflow.

Status: completed on 2026-04-18.

#### A1. Create package and dependency manifest

Status: completed.

Tasks:

- Create `pyproject.toml` using PEP 621 with `uv` as the package manager.
- Set Python requirement to `>=3.11,<3.12`.
- Add runtime dependencies from the Phase 0 plan.
- Add dev dependencies from the Phase 0 plan.
- Run `uv lock` to generate `uv.lock`.

Deliverables:

- `pyproject.toml`
- `uv.lock`

Acceptance checks:

- `uv sync` completes successfully on a clean clone.
- `python -c "import wolfpack"` works inside the `uv` environment after scaffolding.

Validation notes:

- Completed `pyproject.toml` with PEP 621 metadata, runtime dependencies, dev dependency group, Ruff, mypy, and pytest configuration.
- Generated `uv.lock`.
- Verified `uv sync --all-extras --dev`.
- Verified `uv run python -c "import wolfpack; print(wolfpack.__doc__)"`.

#### A2. Create source tree and placeholder packages

Status: completed.

Tasks:

- Create `src/wolfpack/` package tree exactly as described in the phase brief.
- Add `__init__.py` files in each package.
- Keep `schemas/`, `orchestrator/`, `agents/`, `rag/`, and `adapters/` empty except for package markers.

Deliverables:

- `src/wolfpack/...` package layout

Acceptance checks:

- imports succeed for all Phase 0 modules
- no Phase 1 logic exists in placeholder packages

Validation notes:

- Added the full `src/wolfpack/` Track A package tree.
- Added only docstring placeholders to future-phase packages such as `schemas/`, `orchestrator/`, `agents/`, `rag/`, and `adapters/`.
- Added minimal `tests/` scaffolding so the new unit-test hook has a stable target.

#### A3. Configure repo tooling

Status: completed.

Tasks:

- Add Ruff configuration to `pyproject.toml`.
- Add strict `mypy` configuration to `pyproject.toml`.
- Create `justfile` with the Phase 0 command surface:
  - `install`
  - `fmt`
  - `lint`
  - `typecheck`
  - `test`
  - `test-integration`
  - `up`
  - `down`
  - `smoke`
- Extend `.pre-commit-config.yaml` with local hooks for `mypy` and unit tests once the environment is ready.

Deliverables:

- updated `.pre-commit-config.yaml`
- `justfile`
- tool configuration in `pyproject.toml`

Acceptance checks:

- `pre-commit run --all-files` passes
- `just lint`, `just typecheck`, and `just test` exist and run

Validation notes:

- Added `justfile` targets for `install`, `fmt`, `lint`, `typecheck`, `test`, `test-integration`, `up`, `down`, and `smoke`.
- Extended `.pre-commit-config.yaml` with local `mypy` and unit-test hooks.
- Verified `uv run ruff check .`.
- Verified `uv run mypy src tests`.
- Verified `uv run pytest -q tests/unit`.
- Verified `uv run pre-commit run --all-files`.
- `just` is not installed in the current sandboxed shell, so command execution was validated through the underlying `uv run ...` commands that the `justfile` wraps.

### Track B: Configuration and Deployment Guards

Purpose: establish the safety model for pluggable providers, especially airgapped deployments.

#### B1. Implement deployment mode and URL guard helpers

Tasks:

- Create `src/wolfpack/config/deployment.py`.
- Implement `DeploymentMode` with:
  - `DEV`
  - `ON_PREM_CONNECTED`
  - `ON_PREM_AIRGAPPED`
- Implement `is_loopback_or_private(url: str) -> bool`.
- Cover IPv4, localhost, and RFC1918/private ranges.

Deliverables:

- `src/wolfpack/config/deployment.py`

Acceptance checks:

- helper returns `True` for `localhost`, `127.0.0.1`, and private subnet URLs
- helper returns `False` for public internet hosts

#### B2. Implement settings models

Tasks:

- Create `src/wolfpack/config/settings.py`.
- Add nested models for:
  - `LLMConfig`
  - `PostgresConfig`
  - `NATSConfig`
  - `OTelConfig`
  - `MLflowConfig`
- Create root `Settings` with `pydantic-settings`.
- Use `.env` loading with nested env delimiter support.
- Add a root validator enforcing the airgapped restrictions.

Deliverables:

- `src/wolfpack/config/settings.py`
- `src/wolfpack/config/validators.py` if helper validators are split out

Acceptance checks:

- valid configs load in all deployment modes
- airgapped mode rejects `hosted=True`
- airgapped mode rejects non-private `base_url`

#### B3. Add env contract and tests

Tasks:

- Create `.env.example` documenting every required variable.
- Add `tests/unit/test_config.py`.
- Add `tests/unit/test_deployment_guards.py`.

Deliverables:

- `.env.example`
- config unit tests

Acceptance checks:

- unit tests cover pass and fail cases
- `.env.example` is sufficient to bootstrap a local `.env`

### Track C: LLM Abstraction Layer

Purpose: give the rest of the system a stable factory interface while keeping provider-specific details isolated.

#### C1. Implement provider wrappers

Tasks:

- Create `src/wolfpack/llm/providers.py`.
- Implement `OllamaProvider`.
- Implement `OpenAICompatibleProvider`.
- Keep wrappers intentionally thin.

Deliverables:

- `src/wolfpack/llm/providers.py`

Acceptance checks:

- wrappers instantiate the expected Pydantic AI model classes
- constructors accept explicit config only

#### C2. Implement factory and error surface

Tasks:

- Create `src/wolfpack/llm/factory.py`.
- Implement `get_model(config: LLMConfig)`.
- Create `src/wolfpack/llm/errors.py`.
- Raise `LLMConfigError` for unsupported or invalid combinations.

Deliverables:

- `src/wolfpack/llm/factory.py`
- `src/wolfpack/llm/errors.py`

Acceptance checks:

- factory never reads environment variables directly
- provider selection is fully driven by `LLMConfig`

#### C3. Add unit tests for the factory

Tasks:

- Add `tests/unit/test_llm_factory.py`.
- Use `respx` or `httpx_mock` for mocking if needed.
- Keep tests network-free.

Deliverables:

- LLM factory unit tests

Acceptance checks:

- supported providers return expected model types
- unsupported providers raise `LLMConfigError`

### Track D: Docker Compose and Infrastructure

Purpose: create the local runtime stack that the smoke test and future phases depend on.

#### D1. Create compose file and service definitions

Tasks:

- Add `docker-compose.yml`.
- Define services for:
  - `postgres`
  - `nats`
  - `otel-collector`
  - `mlflow`
  - `ollama`
- Use profiles so `mlflow` is omitted in the minimal CI path if desired by the implementation.

Deliverables:

- `docker-compose.yml`

Acceptance checks:

- `docker compose config` validates
- services have healthchecks where expected

#### D2. Add infra assets

Tasks:

- Create `infra/postgres/init.sql`.
- Create `infra/nats/nats-server.conf`.
- Create `infra/otel/otel-collector-config.yaml`.
- Create `infra/mlflow/Dockerfile`.
- Create `infra/ollama/entrypoint.sh`.
- Create `infra/sizing.md`.
- Add `docker-compose.override.yml.example` for GPU and local overrides.

Deliverables:

- full `infra/` tree from the phase brief
- `docker-compose.override.yml.example`

Acceptance checks:

- Postgres initializes `vector`
- NATS JetStream is enabled
- OTel Collector accepts OTLP over HTTP and gRPC
- Ollama entrypoint can pull the dev smoke model

#### D3. Prove startup order and local health

Tasks:

- Add `depends_on` with health conditions where supported.
- Validate that `just up` reaches healthy state without manual retries.
- Make sure the default local path includes MLflow and the CI profile omits it if chosen.

Deliverables:

- working compose startup
- stable startup ordering

Acceptance checks:

- `docker compose up -d` reaches healthy status
- the smoke command does not race infra readiness

### Track E: Observability and Smoke Path

Purpose: prove that a traced LLM call works end to end.

#### E1. Implement tracing bootstrap

Tasks:

- Create `src/wolfpack/observability/tracing.py`.
- Add OTel `TracerProvider` initialization.
- Set resource attributes for:
  - `service.name`
  - `service.namespace`
  - `deployment.environment`
- Configure OTLP exporter from settings.
- Set trace context propagation.

Deliverables:

- `src/wolfpack/observability/tracing.py`

Acceptance checks:

- tracing initializes without duplicate provider errors
- spans are exportable to the collector

#### E2. Implement Logfire wiring

Tasks:

- Create `src/wolfpack/observability/logfire.py`.
- Wire Pydantic AI and Logfire into the OTel path described in the phase brief.
- Keep a fallback path documented if MLflow integration is partially immature.

Deliverables:

- `src/wolfpack/observability/logfire.py`

Acceptance checks:

- smoke execution produces visible spans in the configured backend

#### E3. Implement smoke command

Tasks:

- Create `src/wolfpack/smoke/hello_pack.py`.
- Add a Typer CLI entry point.
- Load settings, initialize tracing, build the model, and run the trivial Pydantic AI request.
- Print trace metadata and the destination URL for inspection.

Deliverables:

- `src/wolfpack/smoke/hello_pack.py`
- optional console-script entry in `pyproject.toml`

Acceptance checks:

- `just smoke` runs locally against the compose stack
- command prints a trace ID
- the run is inspectable through the configured observability path

### Track F: Test Suite and CI Hardening

Purpose: enforce the Phase 0 guarantees automatically.

#### F1. Add test layout and fixtures

Tasks:

- Create `tests/conftest.py`.
- Create `tests/unit/`.
- Create `tests/integration/`.
- Add shared fixtures for settings and service endpoints.

Deliverables:

- test package structure

Acceptance checks:

- `pytest` discovers tests from both unit and integration trees

#### F2. Add integration test coverage

Tasks:

- Create `tests/integration/test_stack_up.py`.
- Use `testcontainers` for isolated service validation.
- Keep integration tests scoped to infrastructure health and smoke-path readiness.

Deliverables:

- integration test module

Acceptance checks:

- integration tests pass in under the target time budget
- tests do not depend on a manually started compose stack

#### F3. Replace placeholder CI with a real workflow

Tasks:

- Remove or replace `.github/workflows/blank.yml`.
- Add `.github/workflows/ci.yml`.
- Include jobs for:
  - `typecheck`
  - `test-unit`
  - `test-integration`
  - `build`
- Keep `pre-commit.yml` as the lint and hygiene gate unless consolidated intentionally.
- Use `astral-sh/setup-uv@v3`.

Deliverables:

- `.github/workflows/ci.yml`
- cleaned-up workflow set under `.github/workflows/`

Acceptance checks:

- CI runs on push and PR
- workflow names and responsibilities are clear
- no duplicate placeholder CI workflow remains

### Track G: Documentation and Handoff

Purpose: leave the repo ready for Phase 1 contributors.

#### G1. Refresh onboarding docs

Tasks:

- Update `README.md` with the full getting-started path.
- Document prerequisites for Docker and GPU-backed Ollama smoke runs.
- Reference `.env.example`, `justfile`, and the compose profiles.

Deliverables:

- updated `README.md`

Acceptance checks:

- a new contributor can follow the steps without tribal knowledge

#### G2. Record effort and next-phase handoff

Tasks:

- Append a retro note to `docs/PROJECT_PLAN.md`.
- Record actual duration, deviations, and unresolved risks.
- Create the Phase 1 tracking issue after completion.

Deliverables:

- updated `docs/PROJECT_PLAN.md`
- Phase 1 issue link or note

Acceptance checks:

- repo contains a visible handoff note for the next phase

## 5. Recommended Delivery Sequence

Land the work in this order to keep the repo green and reduce rework:

1. Create `pyproject.toml`, `uv.lock`, and the `src/` package tree.
2. Add Ruff, mypy, pytest, and `justfile`.
3. Add `config/` models and their unit tests.
4. Add `llm/` factory and its unit tests.
5. Add `infra/` assets and `docker-compose.yml`.
6. Add observability bootstrap and smoke CLI.
7. Add integration tests.
8. Replace `blank.yml` with `ci.yml`.
9. Update README and project-plan retro note.

This order makes each later step build on a validated base.

## 6. Parallelization Plan

Some work can happen in parallel once the base scaffold exists.

### Safe parallel lanes after Track A

- Lane 1: `config/` models plus unit tests
- Lane 2: `infra/` files and compose stack
- Lane 3: CI workflow drafting

### Safe parallel lanes after Track B and Track D are stable

- Lane 1: LLM factory implementation
- Lane 2: observability bootstrap
- Lane 3: README and `.env.example` refinement

### Work that should stay on the critical path

- `pyproject.toml` and environment setup
- settings model shape
- smoke-path wiring
- final CI validation

## 7. Milestones and Exit Criteria

### Milestone 1: Scaffold Ready

Exit criteria:

- package tree exists
- `uv sync` works
- repo tooling is configured

### Milestone 2: Config and Provider Abstractions Ready

Exit criteria:

- settings validation works
- airgapped guard is tested
- LLM factory tests pass

### Milestone 3: Local Stack Ready

Exit criteria:

- compose services build and start cleanly
- healthchecks are stable
- infra config files are committed

### Milestone 4: Smoke Path Proven

Exit criteria:

- smoke CLI runs successfully
- trace data is emitted and inspectable

### Milestone 5: CI and Handoff Complete

Exit criteria:

- CI is green
- README is updated
- retro note is recorded
- Phase 1 handoff item exists

## 8. Command-Level Validation Checklist

Run these commands as the implementation advances:

```bash
uv sync
pre-commit run --all-files
just lint
just typecheck
just test
docker compose config
just up
just smoke
just test-integration
docker compose --profile minimal build
```

All of these should succeed before Phase 0 is marked complete.

## 9. Risks to Watch During Execution

### Observability bridge risk

The Phase 0 brief already flags that the OTel to MLflow bridge may be immature. Treat the OTel Collector `debug` exporter as the fallback proof point during implementation, and make the MLflow path an explicit validation task rather than an assumption.

### Dependency compatibility risk

`pydantic-ai`, `langgraph`, `haystack-ai`, and `mlflow` may have version interactions. Pin carefully in `pyproject.toml`, and do not wait until CI to discover import or typing conflicts.

### Docker startup risk

The smoke test depends on Postgres, NATS, OTel, Ollama, and optionally MLflow. Put healthchecks in place early so that failures show up as service readiness problems instead of opaque smoke-test failures.

### Workflow drift risk

The repo currently has `blank.yml`, which is only a placeholder. Replace it rather than leaving two "CI" workflows with overlapping triggers.

## 10. Definition of Done Mapping

The implementation is complete only when each Phase 0 success condition maps to a concrete artifact:

| Definition of done item | Proof artifact |
|---|---|
| `uv sync` succeeds | `pyproject.toml`, `uv.lock`, passing install |
| `pre-commit` is green | configured hooks and successful run |
| `just up` brings healthy stack | compose file, infra configs, healthchecks |
| `just smoke` traces end to end | smoke CLI, observability bootstrap, running stack |
| tests pass locally | unit and integration test suites |
| CI is green on PR | `.github/workflows/pre-commit.yml` and `.github/workflows/ci.yml` |
| retro note exists | updated `docs/PROJECT_PLAN.md` |
| onboarding is readable | `README.md`, `.env.example`, `infra/sizing.md` |

## 11. Suggested PR Slicing

To keep reviewable changesets, use small sequential PRs:

1. `phase0-scaffold`
2. `phase0-config-and-llm`
3. `phase0-infra-and-compose`
4. `phase0-observability-and-smoke`
5. `phase0-ci-and-docs`

If the team prefers one branch, still commit in that order so regressions are easier to isolate.

## 12. Immediate Next Action

The first implementation step should be:

1. create `pyproject.toml`
2. scaffold `src/wolfpack/`
3. add `justfile`
4. configure Ruff, mypy, and pytest

That establishes the base every other Phase 0 task depends on.
