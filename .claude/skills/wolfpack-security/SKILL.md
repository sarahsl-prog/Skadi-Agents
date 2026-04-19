---
name: wolfpack-security
description: Security audit skill for WolfPack SOC agent system. Use when implementing agent tools, RAG pipelines (Haystack), telemetry adapters, LangGraph nodes that read external data, or before any Phase release. Triggers on: "review security", "audit this", "check for prompt injection", "is this safe", implementing Tracker/Flanker/Closer tools, writing TelemetrySource adapters, PII handling code, break-glass controls, hash-chain ledger code. Also triggers on Phase release gates (end of Phase 3, 5, 8).
---

# WolfPack Security Audit

## Threat Model Summary

WolfPack agents ingest attacker-controlled data (alerts, logs, email bodies, IOCs). The attack surface is structural:
- **Prompt injection**: Logs and threat intel contain adversary-crafted text that may attempt to override agent instructions.
- **Tool scope escape**: A successful injection could try to invoke tools the agent shouldn't have.
- **Secret exfiltration via RAG**: Retrieved documents could be crafted to leak credentials from context.
- **Audit trail tampering**: If the ledger can be written or updated, tamper-evidence is lost.
- **PII leakage**: Analyst context assembly may inadvertently surface raw identifiers to the model.

## Audit Checklist

### 1. Prompt Injection Defense

For every agent that ingests external content:

- [ ] Retrieved content is wrapped: `<retrieved_context>\n{content}\n</retrieved_context>`
- [ ] System prompt restates the agent's role **after** the context block
- [ ] HTML tags, `<script>`, markdown links, and base64 blobs are stripped on ingestion into Haystack
- [ ] No user-controlled string is interpolated into f-string system prompts
- [ ] Instruction-injection patterns are tested: content containing "Ignore previous instructions" must not change agent behavior

### 2. Tool Allowlists

Verify that each Pydantic AI `Agent(tools=[...])` call includes only the tools listed:

| Agent | Permitted tools |
|-------|----------------|
| Alpha Dispatcher | `normalize_seed`, `open_case`, `publish_task` |
| Tracker | `query_telemetry`, `lookup_threat_intel`, `emit_hypothesis` |
| Flanker | `pivot_entity`, `query_dns`, `query_network`, `create_branch` |
| Closer | `read_case_state`, `pull_evidence`, `submit_verdict` |
| Scribe | *(no tools — direct ledger writes via service interface, no LLM)* |

Flag any agent that receives a superset of these tools.

### 3. PII Pseudonymization

- [ ] `PiiProcessor` runs between `TelemetrySource.query()` output and agent context assembly
- [ ] Identifiers (IPs, usernames, hostnames, emails) are hashed with per-case salt from `pii_salts`
- [ ] Free-text fields (email bodies, log messages) pass through NER stripping before model ingestion
- [ ] `show_raw()` break-glass endpoint: (a) requires analyst auth, (b) writes to `breakglass_audit`, (c) is scoped to the current session only — not persisted
- [ ] Per-case salt is stored in `pii_salts` table, not in env vars or application memory

### 4. Secret Handling

- [ ] All credentials are `SecretStr` in Settings — `.get_secret_value()` called only at the network boundary, never logged
- [ ] No `api_key`, `token`, or `password` value appears in any prompt string
- [ ] Tool adapters hold the credential; agents receive a reference handle (e.g., adapter name)
- [ ] `.env` is in `.gitignore`; `.env.example` contains placeholder values only (verify with gitleaks output)
- [ ] Gitleaks pre-commit hook is active and passing

### 5. Hash-Chain Ledger Integrity

- [ ] `evidence_ledger` table: no `UPDATE` or `DELETE` grants for the `wolfpack_app` role
- [ ] `prev_hash` and `content_hash` are computed by a Postgres trigger on `INSERT` — not by application code
- [ ] `verify_chain(case_id)` function exists and is tested with a tamper scenario
- [ ] Crypto-shredding path: DEK row deletion leaves ledger rows intact (data decrypts to null); verify chain still valid after shred

### 6. Deployment-Mode Gating

- [ ] `ON_PREM_AIRGAPPED` validation runs in `@model_validator(mode="after")` on `Settings`
- [ ] `is_loopback_or_private()` rejects `https://api.ollama.com`, any public IP, and any `https://` host
- [ ] `is_loopback_or_private()` accepts `http://localhost`, `http://127.0.0.1`, `http://10.*`, `http://192.168.*`, `http://172.16-31.*`
- [ ] Config load raises `ValueError` (not runtime failure) for hosted endpoints in airgapped mode

### 7. V1 Read-Only Enforcement

- [ ] No agent tool can write to external systems (firewall rules, identity providers, ticketing) in V1
- [ ] Any tool that could write externally is explicitly excluded from all V1 agent tool lists
- [ ] Comment in the tool definition: `# V1: read-only. External write capability reserved for V1.5 Blocker.`

## Severity Levels

| Level | Definition | Action |
|-------|-----------|--------|
| Critical | Prompt injection path with tool scope escape | Block release, fix immediately |
| High | Secret exposure in prompts, PII leak without break-glass | Block release |
| Medium | Missing input validation at adapter boundary | Fix before next Phase |
| Low | Defense-in-depth gap (e.g., no instruction repetition) | Log and schedule |

## Output Format

Return a prioritized finding list:

```
[CRITICAL] file.py:42 — LLM system prompt interpolates raw log content via f-string.
  Fix: Wrap content in <retrieved_context> delimiter and move outside f-string.

[HIGH] adapters/crowdstrike.py:88 — API key logged at DEBUG level.
  Fix: Use SecretStr; call .get_secret_value() only at the httpx call site.
```

No vague findings. Every item: severity, file:line, description, specific fix.
