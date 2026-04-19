---
name: wolfpack-tester
description: Test engineering skill for wolfpack package. Use when writing pytest tests, fixing test failures, improving coverage, configuring pytest-asyncio, setting up testcontainers fixtures, validating mypy strict compliance, or building the eval golden set. Triggers on: "write tests for X", "add a test", "fix this test failure", "increase coverage", test_*.py files, conftest.py changes, Phase 0 Day 1/2/3/6 test work, integration test setup, eval harness (Phase 3+). Also triggers on: mypy errors, type annotation gaps, test parametrization requests.
---

# WolfPack Test Engineering

## Test Pyramid

```
Unit tests (tests/unit/)        — fast, no I/O, mocked network
Integration tests (tests/integration/) — testcontainers, opt-in
Eval tests (tests/evals/)       — Phase 3+, golden set, MLflow-tracked
```

## pytest Configuration (pyproject.toml)

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--strict-markers -q"

[tool.coverage.run]
source = ["src"]
omit = ["tests/*", "src/wolfpack/smoke/*"]
```

Never use `@pytest.mark.asyncio` on individual tests — `asyncio_mode = "auto"` handles all async tests.

## Unit Test Patterns

### Config Tests (Phase 0)

```python
import pytest
from pydantic import ValidationError
from wolfpack.config.settings import Settings
from wolfpack.config.deployment import DeploymentMode

@pytest.mark.parametrize("url,should_raise", [
    ("https://api.ollama.com", True),      # hosted — forbidden
    ("http://localhost:11434", False),      # loopback — allowed
    ("http://192.168.1.100:11434", False),  # private — allowed
])
def test_airgapped_llm_url(url, should_raise, base_airgapped_env):
    env = {**base_airgapped_env, "LLM__BASE_URL": url}
    if should_raise:
        with pytest.raises(ValidationError):
            Settings(**env)
    else:
        Settings(**env)  # must not raise
```

### LLM Factory Tests (Phase 0)

Mock network at the `httpx` level using `respx`. Never mock Pydantic AI internals.

```python
import respx
from wolfpack.llm.factory import get_model
from wolfpack.llm.errors import LLMConfigError

def test_unknown_provider_raises():
    cfg = LLMConfig(provider="unknown", ...)  # type: ignore[arg-type]
    with pytest.raises(LLMConfigError):
        get_model(cfg)
```

### Async Agent Tests (Phase 3+)

```python
async def test_tracker_emits_hypothesis(mock_telemetry_source, mock_threat_intel):
    result = await tracker_agent.run(input_model)
    assert result.data.tracker_confidence >= Confidence.PLAUSIBLE
    assert len(result.data.new_hypotheses) > 0
```

## testcontainers Fixtures (Integration)

```python
# tests/integration/conftest.py
import pytest
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        # Apply init.sql
        import asyncpg, asyncio
        async def setup():
            conn = await asyncpg.connect(pg.get_connection_url())
            with open("infra/postgres/init.sql") as f:
                await conn.execute(f.read())
            await conn.close()
        asyncio.get_event_loop().run_until_complete(setup())
        yield pg.get_connection_url()
```

Gate integration tests: `pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="needs RUN_INTEGRATION=1")` on the integration `conftest.py` module.

## mypy Compliance Rules

- Every function: explicit return type annotation
- No bare `Any` except at JSON deserialization boundaries (annotate with `# type: ignore[misc]` + comment)
- `reveal_type()` is for debugging only — never commit it
- Run: `mypy --strict src/ tests/`

## Hash-Chain Tamper Test (Phase 1+)

```python
async def test_verify_chain_detects_tamper(postgres_url):
    # Insert 3 ledger entries
    # Directly UPDATE row 2's content_hash (simulate tamper)
    # Assert verify_chain(case_id) returns False
```

## Eval Golden Set (Phase 3+)

Location: `tests/evals/golden/*.json`

Schema:
```json
{
  "seed": { "type": "ioc", "value": "185.220.101.45" },
  "expected_entities": [...],
  "min_confidence": 3,
  "expected_verdict": "malicious"
}
```

Run evals and log to MLflow:
```python
with mlflow.start_run(run_name="tracker_eval"):
    mlflow.log_metric("hypothesis_precision", ...)
    mlflow.log_metric("confidence_p50", ...)
```

## Output Format

Produce complete test files — independently runnable with `pytest tests/unit/test_<module>.py`. Requirements:
- All async tests work with `asyncio_mode = "auto"`
- All parametrize cases cover both happy path and error path
- No `pass`, no TODOs, no commented-out assertions
- Files pass `mypy --strict`
