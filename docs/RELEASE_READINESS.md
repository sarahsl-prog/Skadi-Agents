# V1 Release Readiness Checklist

**Date:** 2026-05-01  
**Release:** WolfPack V1

## Engineering

- [x] All unit tests pass (`uv run pytest tests/unit`)
- [x] All integration tests pass (`uv run pytest tests/integration`)
- [x] All security tests pass (`uv run pytest tests/security`)
- [x] Crypto-shredding dry-run passes (`tests/security/test_crypto_shredding.py`)
- [x] Break-glass audit review complete (`tests/security/test_breakglass_audit.py`)
- [x] Secret-handling audit clean (`tests/security/test_secret_handling.py`)
- [x] Threat model reviewed (`docs/security/threat_model.md`)
- [x] Lint passes (`ruff check src tests`)
- [x] Type-check passes (`mypy src`)

## Security

- [x] Prompt-injection red-team tests (RAG + tools)
- [x] Tool-allowlist enforcement tests
- [x] Secret audit report (`docs/security/secret_audit.md`)
- [x] `.gitleaks.toml` allowlist configured
- [x] `.env.example` contains only placeholders
- [x] No hardcoded secrets in `docker-compose.yml` or `infra/`
- [x] Final security review summary (`docs/security/security_review.md`)

## Operations

- [x] Deployment runbook (`docs/runbook/deployment.md`)
- [x] On-call runbook (`docs/runbook/oncall.md`)
- [x] Architecture documentation (`docs/runbook/architecture.md`)
- [x] Configuration reference (`docs/runbook/configuration.md`)
- [x] All Phase 6 alerts operational (schema-retry, ledger-hash, branch depth, review timeout, NATS lag, tool-allowlist)
- [x] `verify_chain()` SQL function present

## Observability

- [x] OTel instrumentation across LangGraph nodes, Pydantic AI agents, Haystack RAG
- [x] Baggage propagation (`case_id`, `branch_id`, `agent_run_id`)
- [x] Alert manager with webhook support
- [ ] MLflow dashboards validated with live data — **deferred to post-deployment**
- [ ] Jaeger exporter enabled and validated — **deferred to post-deployment**

## Documentation

- [x] `README.md` updated with V1 feature set
- [x] `docs/PROJECT_PLAN.md` updated with Phase 8 retro
- [x] Cross-references between runbooks, security docs, and plan are correct
- [x] `.env.example` is up to date with all `Settings` fields

## Performance

- [x] Performance baseline document created (`docs/performance_baseline.md`)
- [ ] Live benchmark executed on reference hardware — **deferred to post-deployment**

## Deferred Items (V1.5 or later)

| Item | Reason | Target |
|---|---|---|
| V1.5 trigger metrics | Best defined after real eval data | V1.5 planning |
| Blocker agent | Explicitly deferred in plan | V1.5 |
| Post-Hunt Analyst | Explicitly deferred in plan | V1.5 |
| Token / tool budget per branch | Requires provider instrumentation not yet wired | V2 |
| Jaeger exporter default-on | Low priority; MLflow is primary | V1.5 |
| Live performance benchmark | Requires reference GPU hardware not available in CI | Post-deployment |

## Sign-Off

- [x] Security review complete
- [x] Release readiness checklist complete
- [ ] **Project owner final sign-off** — pending

**Decision:** Ready to tag `v1.0.0` after project owner review.
