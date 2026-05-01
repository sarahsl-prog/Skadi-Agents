# Secret-Handling Audit Report

**Date:** 2026-05-01  
**Auditor:** OpenCode agent  
**Scope:** Full repository (`src/`, `tests/`, `docs/`, `infra/`, `.env.example`, `docker-compose.yml`, `pyproject.toml`, `.pre-commit-config.yaml`)

## 1. Executive Summary

No secrets were found in the codebase outside of test fixtures that intentionally use dummy values to verify `pydantic.SecretStr` behavior.

| Check | Result |
|---|---|
| Agent system prompts | No secrets detected |
| Tool outputs / adapter interfaces | No secrets exposed |
| OTel spans / log lines | No secrets in attributes |
| LLM config `api_key` | `SecretStr` enforced |
| `.env.example` | Placeholder-only values |
| `docker-compose.yml` | No hardcoded secrets |
| `pyproject.toml` / `justfile` | No secrets |
| Pre-commit gitleaks hook | Configured (`.gitleaks.toml` allowlist added) |

## 2. Agent Prompt Audit

Each agent system prompt was searched for keywords (`api_key`, `password`, `secret`, `postgresql`, `nats://`, `dsn`, `http`):

| Agent | Prompt Source | Keywords Checked | Status |
|---|---|---|---|
| Closer | `agents/closer.py` | `api_key`, `password`, `secret` | Pass |
| Tracker | `agents/tracker.py` | `postgresql`, `nats://`, `dsn` | Pass |
| Flanker | `agents/flanker.py` | `http`, `api_key` | Pass |
| Alpha | `agents/alpha.py` | `http`, `api_key`, `secret` | Pass |

## 3. Tool Output Audit

Adapters implement `TelemetrySource` (abstract base). No adapter exposes a `get_credentials` method or returns raw credentials in tool outputs.

| Adapter Tier | Tool Type | Returns |
|---|---|---|
| Tier 1 | Telemetry queries | `Event` / `Entity` objects (sanitised) |
| Tier 2 | DNS, proxy, CloudTrail | `Event` / `Entity` objects (sanitised) |
| RAG | Threat intel, case history | `RAGDocument` objects (sanitised) |

## 4. OTel / Logging Audit

- `AlertManager._webhook_url` is a plain string (validated to contain no `user:pass@host` credential embedding).
- No `SecretStr` values are attached as span attributes.
- `Settings` repr does not serialize `SecretStr` contents.

## 5. Configuration Audit

### `.env.example`
- Uses `changeme` for the Postgres password placeholder.
- No real API keys, no real DSNs.
- `LLM__API_KEY` is commented out.

### `docker-compose.yml`
- Services use environment-variable placeholders or defaults (`wolfpack:changeme` only in `.env.example`, not hardcoded in compose).
- No `sk-` patterns found.

### `pyproject.toml`
- No secrets or credential strings.

## 6. Secret-Scanning Tool Results

Tool: `gitleaks` (pre-commit hook v8.21.2)

- One false-positive: `tests/security/test_secret_handling.py` contains the string `sk-test-secret` as a dummy key to exercise `SecretStr`.
- Mitigation: `.gitleaks.toml` allowlist ignores `tests/security/test_secret_handling.py` and `test_*.py` files under `tests/security/`.

## 7. Recommendations

1. **Rotate CI tokens** if any are introduced in future workflows.
2. **Enable secondary CI-only scan** with `detect-secrets` baseline if the project grows to include many generated artifacts.
3. **Review `.gitleaks.toml` allowlist** as part of every release security review.
4. **Never commit `.env`** — already gitignored; verify in onboarding docs.

## 8. Sign-Off

- [x] Secret-handling audit tests pass (`tests/security/test_secret_handling.py`)
- [x] gitleaks pre-commit hook configured
- [x] `.gitleaks.toml` allowlist created
- [x] No real secrets detected in repository
