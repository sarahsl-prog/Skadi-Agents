# Phase 0 Audit Remediation Plan

**Date:** 2026-04-26  
**Scope:** Fix all items in `CODEBASE_AUDIT_REPORT.md` before Phase 1 kickoff  
**Definition of Done:** All tests pass, mypy is clean, docs are fresh, no audit findings remain open.

---

## 1. Work Breakdown

The plan is organized into **5 tracks** that can run in parallel once the base scaffold is validated. Dependencies are explicit so work can be parallelized safely.

| Track | Focus | Files | Parallelizable After |
|---|---|---|---|
| A | Docs & Config fixes | `README.md`, `docker-compose.yml`, `pyproject.toml`, `validators.py` | Immediate |
| B | Security & URL guards | `deployment.py`, `test_deployment_guards.py` | Immediate |
| C | Config model validation | `settings.py`, `test_config.py` | After Track B |
| D | Integration & smoke tests | `test_stack_up.py`, new smoke CLI test | After Track A |
| E | Infra hardening | `docker-compose.yml`, OTel tag | Immediate |

---

## 2. Detailed Tracks

### Track A: Documentation & Configuration Fixes

#### A1. Fix stale `--profile minimal` references

**Files:** `README.md`, `docker-compose.yml`, `docs/PHASE_0_IMPLEMENTATION_PLAYBOOK.md`

**Changes:**

1. **`docker-compose.yml:3`** — Update the header comment:
   ```yaml
   # Usage:  docker compose up -d        (default services: postgres, nats, otel-collector, ollama)
   #         docker compose --profile full up -d  (default + MLflow)
   ```

2. **`README.md:60-63`** — Remove the `--profile minimal` section or update to describe the actual default behavior:
   ```markdown
   # Minimal stack (Postgres, NATS, OTel Collector, Ollama)
   docker compose up -d

   # Full stack (add MLflow tracking server)
   docker compose --profile full up -d
   ```

3. **`docs/PHASE_0_IMPLEMENTATION_PLAYBOOK.md:620`** — Remove or correct the `--profile minimal build` reference in the validation checklist.

**Acceptance Criteria:**
- `grep -r "profile minimal" --include="*.md" --include="*.yml" --include="*.yaml" .` returns zero matches.
- Documentation accurately describes the `default` and `full` profiles.

---

#### A2. Consolidate duplicate `dev` dependencies in `pyproject.toml`

**File:** `pyproject.toml`

**Current State:**
```toml
[project.optional-dependencies]
dev = [ ... ]          # lines 37-47

[dependency-groups]
dev = [ ... ]          # lines 75-85 (identical)
```

**Changes:**
- Remove the entire `[project.optional-dependencies]` block.
- Keep only `[dependency-groups] dev`, which is the modern `uv`-preferred approach.
- Verify that `uv sync --all-extras --dev` still works (note: `--all-extras` will no longer have a `dev` extra; update the README if necessary).

**Acceptance Criteria:**
- `pyproject.toml` contains exactly one declaration of the dev dependency list.
- `uv sync` completes successfully.
- `uv run pytest -q tests/unit` still passes.
- `uv run ruff check .` still passes.
- `uv run mypy src tests` still passes.

**Note:** If the project relies on `pip install -e ".[dev]"` anywhere (CI, docs), that path will break. Verify the CI workflow uses `uv sync --all-extras --dev` or equivalent.

---

#### A3. Add explanatory comment to `validators.py`

**File:** `src/wolfpack/config/validators.py`

**Changes:**
```python
"""Custom config validators."""

# Placeholder for Phase 1 custom validators (e.g., DSN format, URL schemes,
# hash-chain integrity checks).  This module will be populated as the schema
# and ledger contracts from Phase 1 land.
```

**Acceptance Criteria:**
- File contains a clear explanation of why it is empty and when it will be used.

---

### Track B: Security & URL Guard Hardening

#### B1. Add IPv6 loopback (`::1`) support to `is_loopback_or_private()`

**File:** `src/wolfpack/config/deployment.py`

**Changes:**

Add `::1` detection immediately after the `localhost` check:

```python
def is_loopback_or_private(url: str) -> bool:
    """Return True if the URL's host is a loopback or RFC-1918 private address.

    Non-IP hostnames (other than 'localhost') are conservatively treated as public.
    IPv6 loopback (::1) is also accepted.
    This is called at config load time to enforce airgapped deployment restrictions.
    """
    host = urlparse(url).hostname or ""
    if not host:
        return False
    if host == "localhost":
        return True
    if host == "::1":
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_loopback or addr.is_private
    except ValueError:
        # Non-IP hostname that isn't 'localhost' — treat as public
        return False
```

**Acceptance Criteria:**
- `is_loopback_or_private("http://[::1]:11434")` returns `True`.
- `is_loopback_or_private("http://[::1]")` returns `True`.
- Existing tests continue to pass.

---

#### B2. Add IPv6 loopback test cases to `test_deployment_guards.py`

**File:** `tests/unit/test_deployment_guards.py`

**Changes:**

Extend the parametrized test matrix:

```python
@pytest.mark.parametrize(
    "url,expected",
    [
        # Loopback
        ("http://localhost:11434", True),
        ("http://localhost", True),
        ("http://127.0.0.1:11434", True),
        ("http://127.0.0.1", True),
        ("http://[::1]:11434", True),          # NEW
        ("http://[::1]", True),                  # NEW
        # ... rest of existing cases
    ],
)
```

**Acceptance Criteria:**
- New test cases pass.
- Full test suite passes.

---

#### B3. Add URL scheme validation (Security hardening)

**File:** `src/wolfpack/config/settings.py`

**Changes:**

Add a `@field_validator` to `LLMConfig` that rejects URLs without an allowed scheme:

```python
_ALLOWED_SCHEMES = {"http", "https"}

class LLMConfig(BaseModel):
    # ... existing fields ...

    @field_validator("base_url")
    @classmethod
    def _validate_url_scheme(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError(f"base_url must use http or https scheme, got: {parsed.scheme!r}")
        if not parsed.netloc:
            raise ValueError("base_url must have a host component")
        return v
```

> **Note:** `urlparse` must be imported at module level.

**Acceptance Criteria:**
- `LLMConfig(base_url="localhost:11434", ...)` raises `ValidationError`.
- `LLMConfig(base_url="file:///etc/passwd", ...)` raises `ValidationError`.
- `LLMConfig(base_url="http://localhost:11434", ...)` succeeds.

---

### Track C: Config Model Validation & Tests

#### C1. Add bounds validation to `LLMConfig.request_timeout_s`

**File:** `src/wolfpack/config/settings.py`

**Changes:**

```python
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

class LLMConfig(BaseModel):
    # ... existing fields ...

    @field_validator("request_timeout_s")
    @classmethod
    def _timeout_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("request_timeout_s must be positive")
        return v
```

**Acceptance Criteria:**
- `LLMConfig(request_timeout_s=-1.0, ...)` raises `ValidationError`.
- `LLMConfig(request_timeout_s=0, ...)` raises `ValidationError`.
- `LLMConfig(request_timeout_s=60.0, ...)` succeeds.

---

#### C2. Add cross-field pool size validation to `PostgresConfig`

**File:** `src/wolfpack/config/settings.py`

**Changes:**

```python
class PostgresConfig(BaseModel):
    dsn: SecretStr
    pool_min_size: int = 2
    pool_max_size: int = 10

    @model_validator(mode="after")
    def _pool_sizes_consistent(self) -> "PostgresConfig":
        if self.pool_min_size > self.pool_max_size:
            raise ValueError(
                f"pool_min_size ({self.pool_min_size}) must not exceed "
                f"pool_max_size ({self.pool_max_size})"
            )
        return self
```

**Acceptance Criteria:**
- `PostgresConfig(dsn="...", pool_min_size=10, pool_max_size=2)` raises `ValidationError`.
- `PostgresConfig(dsn="...", pool_min_size=2, pool_max_size=10)` succeeds.
- `PostgresConfig(dsn="...", pool_min_size=5, pool_max_size=5)` succeeds.

---

#### C3. Add unit tests for new validators

**File:** `tests/unit/test_config.py`

**Changes:**

Add the following test functions:

```python
# ---------------------------------------------------------------------------
# URL scheme validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_url",
    [
        "localhost:11434",      # no scheme
        "ftp://localhost:11434",  # wrong scheme
        "file:///etc/passwd",    # wrong scheme
    ],
)
def test_llm_config_rejects_invalid_url_scheme(
    monkeypatch: pytest.MonkeyPatch, bad_url: str
) -> None:
    with pytest.raises(ValidationError, match="scheme"):
        _load(monkeypatch, DEPLOYMENT_MODE="dev", LLM__BASE_URL=bad_url)


# ---------------------------------------------------------------------------
# Timeout bounds
# ---------------------------------------------------------------------------

def test_llm_config_rejects_negative_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="positive"):
        _load(monkeypatch, DEPLOYMENT_MODE="dev", LLM__REQUEST_TIMEOUT_S="-5.0")


def test_llm_config_rejects_zero_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="positive"):
        _load(monkeypatch, DEPLOYMENT_MODE="dev", LLM__REQUEST_TIMEOUT_S="0")


# ---------------------------------------------------------------------------
# Postgres pool size consistency
# ---------------------------------------------------------------------------

def test_postgres_config_rejects_inverted_pool_sizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError, match="pool_min_size"):
        _load(monkeypatch, DEPLOYMENT_MODE="dev", POSTGRES__POOL_MIN_SIZE="10", POSTGRES__POOL_MAX_SIZE="2")
```

> **Note:** The `_load` helper must accept arbitrary kwargs and forward them to `monkeypatch.setenv`. If it currently hardcodes `LLM__BASE_URL`, etc., extend it to accept arbitrary env overrides.

**Acceptance Criteria:**
- All new tests pass.
- Existing tests continue to pass.
- Total test count increases from 43 to 49+.

---

#### C4. Add test for schemeless `base_url` behavior

**File:** `tests/unit/test_deployment_guards.py`

**Changes:**

Add edge cases to the parametrized `test_is_loopback_or_private`:

```python
# Edge cases — schemeless or malformed URLs
("localhost:11434", False),   # urlparse treats entire string as path
("", False),
```

**Acceptance Criteria:**
- Test passes and documents the conservative behavior for schemeless strings.

---

### Track D: Test Coverage Expansion

#### D1. Add a unit test for the smoke CLI

**File:** `tests/unit/test_smoke_cli.py` (new)

**Changes:**

```python
"""Unit tests for the smoke CLI entry point."""

import subprocess
import sys


def test_smoke_cli_imports() -> None:
    """The smoke CLI module must be importable without side effects."""
    from wolfpack.smoke.hello_pack import app

    assert app is not None


def test_smoke_cli_help() -> None:
    """The smoke CLI must expose a --help flag."""
    result = subprocess.run(
        [sys.executable, "-m", "wolfpack.smoke.hello_pack", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "smoke" in result.stdout.lower()
```

**Acceptance Criteria:**
- `pytest tests/unit/test_smoke_cli.py -v` passes.
- No network calls are made during the test.

---

#### D2. Expand integration tests for deeper infra validation

**File:** `tests/integration/test_stack_up.py`

**Changes:**

1. **Verify pgvector extension:**

   Extend `test_postgres_starts_and_responds` to execute a query:

   ```python
   import asyncpg

   async def test_postgres_has_pgvector(postgres_container: Any) -> None:
       """Postgres container must have the pgvector extension installed."""
       import asyncpg

       dsn = postgres_container.get_connection_url().replace(
           "postgresql+psycopg2://", "postgresql://"
       )
       conn = await asyncpg.connect(dsn)
       try:
           row = await conn.fetchval(
               "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
           )
           assert row is True
       finally:
           await conn.close()
   ```

2. **Verify NATS JetStream:**

   Extend `test_nats_starts_and_exposes_port` to create a JetStream stream:

   ```python
   import nats

   async def test_nats_has_jetstream(nats_container: Any) -> None:
       """NATS container must have JetStream enabled."""
       host = nats_container.get_container_host_ip()
       port = nats_container.get_exposed_port(4222)
       nc = await nats.connect(f"nats://{host}:{port}")
       try:
           js = nc.jetstream()
           await js.add_stream(name="TEST_STREAM", subjects=["test.>"])
           info = await js.stream_info("TEST_STREAM")
           assert info is not None
       finally:
           await nc.close()
   ```

   > **Note:** These require `asyncpg` and `nats-py` to be available in the test environment. Both are already in `pyproject.toml` dependencies. Mark them with `@pytest.mark.asyncio`.

**Acceptance Criteria:**
- Integration tests pass when Docker is available.
- They are skipped when `SKIP_INTEGRATION=1`.

---

### Track E: Infrastructure Hardening

#### E1. Pin OTel Collector image tag

**File:** `docker-compose.yml`

**Changes:**

Replace `latest` with a pinned version:

```yaml
otel-collector:
  image: otel/opentelemetry-collector-contrib:0.123.0
  # or whatever is the current stable release at implementation time
```

**Acceptance Criteria:**
- `docker compose config` validates without errors.
- The chosen tag exists on Docker Hub.
- Update `infra/sizing.md` or `.env.example` with a note about the pinned version.

---

#### E2. Document NATS auth model for production

**File:** `infra/nats/nats-server.conf`

**Changes:**

Add a comment at the top:

```yaml
# Production deployments MUST override this file via docker-compose.override.yml
# or a mounted secret to enable authentication and TLS.  The default below is
# intentionally open for local development only.
```

**Acceptance Criteria:**
- The security posture of the default NATS config is explicit.

---

## 3. Delivery Sequence

Run in this order to keep the repo green at every step:

| Step | Track | Task | Validation |
|---|---|---|---|
| 1 | A | A1 — Fix docs references | `grep -r "profile minimal" .` is empty |
| 2 | A | A2 — Consolidate `pyproject.toml` deps | `uv sync` succeeds; tests pass |
| 3 | A | A3 — Comment `validators.py` | `ruff check .` passes |
| 4 | B | B1 — IPv6 loopback support | New tests pass |
| 5 | B | B2 — IPv6 tests | Full suite passes |
| 6 | B | B3 — URL scheme validation | New tests pass |
| 7 | C | C1 — Timeout bounds | New tests pass |
| 8 | C | C2 — Pool size validation | New tests pass |
| 9 | C | C3 — Unit tests for validators | Total tests >= 49 |
| 10 | C | C4 — Schemeless edge case | Full suite passes |
| 11 | D | D1 — Smoke CLI unit test | New test passes |
| 12 | D | D2 — Expanded integration tests | `pytest tests/integration` passes |
| 13 | E | E1 — Pin OTel tag | `docker compose config` validates |
| 14 | E | E2 — NATS auth comment | Manual review |
| 15 | All | Final validation | `just lint`, `just typecheck`, `just test`, `just test-integration` all pass |

---

## 4. Parallelization Plan

### Safe parallel lanes after Step 3 (Track A complete)

- **Lane 1:** Track B (security/URL guards) + Track C (validators + tests)
- **Lane 2:** Track D (test expansion)
- **Lane 3:** Track E (infra hardening)

### Work that must stay on the critical path

- `pyproject.toml` consolidation (Step 2) — all other tracks depend on a clean dependency tree.
- URL scheme validator (B3) — cross-cuts into `Settings` and must land before new tests.
- Final validation (Step 15) — must be the last action.

---

## 5. Acceptance Criteria for the Plan

The entire remediation is complete when:

1. **`just lint` passes** — ruff reports zero issues.
2. **`just typecheck` passes** — mypy strict reports zero issues across 25+ source files.
3. **`just test` passes** — all unit tests pass (target: 49+).
4. **`just test-integration` passes** — integration tests pass when Docker is available.
5. **`grep -r "profile minimal" --include="*.md" --include="*.yml" --include="*.yaml" .` returns empty**.
6. **`is_loopback_or_private("http://[::1]:11434")` returns `True`**.
7. **`pyproject.toml` contains exactly one `dev` dependency declaration**.
8. **All new validators have matching unit tests**.
9. **OTel Collector image is pinned to a specific version**.
10. **`CODEBASE_AUDIT_REPORT.md` is updated** — mark resolved items, or create a follow-up issue.

---

## 6. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `pydantic.HttpUrl` change breaks downstream callers | Low | Medium | Use `@field_validator` instead of changing field types; keeps `str` API stable. |
| Integration tests timeout with JetStream stream creation | Medium | Low | Increase test timeout; use small stream limits; skip gracefully if container is slow. |
| Removing `[project.optional-dependencies] dev` breaks external install paths | Low | Medium | Verify CI uses `uv sync`; document the change in README. |
| OTel pin needs periodic bumps | High | Low | Add a note in `infra/sizing.md` about the upgrade cadence. |

---

## 7. Suggested PR Slicing

To keep reviewable changesets:

1. `audit-fix/docs-and-config` — A1, A2, A3
2. `audit-fix/url-guards` — B1, B2, B3
3. `audit-fix/model-validators` — C1, C2, C3, C4
4. `audit-fix/test-coverage` — D1, D2
5. `audit-fix/infra-hardening` — E1, E2

Each PR must pass `just lint`, `just typecheck`, and `just test` before merge.

---

*End of remediation plan.*
