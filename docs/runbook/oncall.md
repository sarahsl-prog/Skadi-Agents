# On-Call Runbook

## 1. Alert Catalog

All alerts are emitted by `AlertManager` and surfaced in the Analyst Console notification feed. If `WEBHOOK_CONFIG__URL` is configured, alerts are also POSTed as JSON.

| Alert | Severity | Trigger | Response |
|---|---|---|---|
| **Schema-retry spike** | `warning` | Pydantic AI schema-retry rate exceeds 5 % in a 5-minute window | Check model temperature / context length; review recent seed formats for malformed inputs |
| **Ledger-hash mismatch** | `critical` | `verify_chain()` returns `false` for any case | Immediately isolate the case; run `verify_chain()` per branch; inspect `evidence_ledger` for tampered rows; escalate to security team |
| **Branch-depth exceeded** | `warning` | Flanker depth exceeds `BRANCH_BUDGET__MAX_DEPTH` | Review seed for adversarial branch-explosion patterns; adjust depth limit if false positive |
| **Review timeout** | `critical` | Analyst review SLA exceeded (default 24 h) | Check analyst workload; review timeout configuration; trigger escalation webhook |
| **NATS consumer lag** | `warning` | JetStream consumer lag > 1000 messages for > 2 min | Scale consumers; check app logs for stalled handlers; verify NATS server health |
| **Tool-allowlist violation** | `critical` | Agent attempted to call a tool outside its allowlist | Review agent logs; inspect seed for injection payloads; block seed source if malicious |

## 2. Common Incidents

### Agent Producing Incorrect Verdicts

1. Open MLflow dashboard → filter by `case_id` → inspect Tracker and Flanker confidence scores.
2. If Tracker confidence < 3 repeatedly, check telemetry adapter connectivity and RAG retrieval quality.
3. Review the learning queue (`docs/learning_eval_results.md`) — stale approved cases degrade retrieval.
4. Escalate to model team if confidence calibration is systematically off.

### Ledger Hash Mismatch

1. Run `SELECT * FROM wolfpack.verify_chain(<case_id>);`
2. If `false`, identify the first failing row (`SELECT * FROM evidence_ledger WHERE case_id = <id> ORDER BY sequence`).
3. Compare `prev_hash` with `SHA-256` of the previous row’s JSON.
4. If tampering is confirmed, preserve the database, open a security incident, and do **not** auto-repair.
5. If the mismatch is from a known bug (e.g., missing `agent_run_id` in older rows), document and apply a compensating migration with sign-off.

### Review Timeout Escalation

1. Check the Analyst Console for pending cases older than `REVIEW_TIMEOUT_HOURS`.
2. Verify the webhook URL is responding (`curl -X POST $WEBHOOK_CONFIG__URL`).
3. If the timeout is too aggressive for current staffing, temporarily raise `REVIEW_TIMEOUT_HOURS` (requires restart).
4. Do **not** bypass review — the case must stay in `Review` until an analyst acts.

### NATS Consumer Lag

1. Check NATS monitoring: http://localhost:8222/jsz
2. Verify consumer group health: `nats consumer info <stream> <consumer>`
3. If one consumer is stalled, restart the app pod/container.
4. If lag is systemic, scale the consumer replica count.

### Crypto-Shredding Failure

1. Check KMS / KEK availability: the KEK must be accessible to unwrap the DEK.
2. If shredding a case fails mid-flight, the DEK row may still exist — retry the erasure request.
3. Verify `crypto_shred_keys` row was deleted and `verify_chain()` still passes.
4. If KEK rotation is in progress, confirm new KEK can unwrap legacy DEKs before rotation completes.

## 3. Escalation Paths

| Situation | First Responder | Escalate To | Timeframe |
|---|---|---|---|
| Ledger tampering suspected | On-call engineer | Security lead + CISO | Immediate |
| Tool-allowlist violation | On-call engineer | Security lead + incident response | Immediate |
| Model producing systematic bias | On-call engineer | ML / data science lead | Within 4 h |
| Infrastructure outage (Postgres/NATS) | On-call engineer | Platform / SRE lead | Within 30 min |
| Review timeout storm (>10 cases) | On-call engineer | SOC manager | Within 1 h |

## 4. Rollback Procedures

### Application Rollback

```bash
# Revert to previous Docker image or Git commit
git checkout <previous-tag>
docker compose up -d --build
```

### Database Rollback

1. Stop the application.
2. Restore from the latest `pg_dump`:
   ```bash
   pg_restore -d wolfpack wolfpack_<date>.dump
   ```
3. Re-run `alembic upgrade head` to apply any schema patches since the dump.
4. Restart the application.

### NATS Stream Rollback

```bash
nats stream restore wolfpack_cases /backup/nats
```

### MLflow Artifacts

Restore the `mlflow_artifacts` Docker volume from backup or S3 snapshot.

## 5. Break-Glass Emergency Access

If an analyst needs raw PII outside normal console flows:

1. Every break-glass invocation is logged to `breakglass_audit`.
2. Query the table for recent invocations:
   ```sql
   SELECT * FROM breakglass_audit WHERE timestamp > now() - interval '1 hour';
   ```
3. Unauthorized break-glass usage is a critical alert; escalate immediately.

## 6. Post-Incident Checklist

- [ ] Incident timestamp and root cause documented
- [ ] Evidence preserved (ledger dumps, span exports, NATS logs)
- [ ] `verify_chain()` run on all affected cases
- [ ] Fix deployed or config change applied
- [ ] Regression test added if applicable
- [ ] Post-mortem scheduled within 48 h for `critical` incidents
