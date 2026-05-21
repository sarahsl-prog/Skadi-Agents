# Architecture and Data-Flow Documentation

## 1. System Overview

WolfPack is a multi-agent "pack-hunt" SOC assistant. Seeds (IOCs, alerts, anomalies, hunt queries) are triaged and expanded by a team of specialized AI agents that coordinate through a shared case state and an immutable evidence ledger.

Two non-negotiable properties:
- **Audit trail** — every agent action, tool call, retrieved document, and state transition is logged to a hash-chained ledger.
- **Traceability** — the reasoning path from seed → hypothesis → verdict is reconstructable end-to-end via the ledger and OpenTelemetry traces.

## 2. Three Concentric Rings

| Ring | Framework | Responsibility |
|---|---|---|
| **Orchestration** | LangGraph | Case state machine (`New → Scented → Shadowing → Decision → Review → Closed/Continue`), node transitions, branching, event-bus integration |
| **Agent implementation** | Pydantic AI | Type-safe `Agent[InputModel, OutputModel]` per role, tool invocation, retries on schema failure, Logfire → OTel emission |
| **Context / RAG** | Haystack | Threat-intel pipeline (ATT&CK, CVEs, IOC feeds) and case-history pipeline, exposed as tools |

## 3. Agent Roster (V1)

| Agent | Role | Key Tools | Output |
|---|---|---|---|
| **Alpha Dispatcher** | Normalizes seed, creates `CaseState`, routes tasks | Case creation, NATS publish | `CaseState`, initial task messages |
| **Tracker** | Finds initial credible scent; queries telemetry + threat intel | `threat_intel_tool`, `case_history_tool`, Tier-1 queries | `new_hypotheses`, `updated_entities`, `evidence_refs`, `tracker_confidence` |
| **Flanker** | Lateral pivots across hosts/users/DNS/email; elevates side signals | All Tracker tools + branch creation | `branches_to_create`, additional hypotheses |
| **Closer** | Assembles verdict packet for analyst review | Read-only tools, intel synthesis | `verdict`, `confidence`, `next_best_action` |
| **Scribe** | Non-LLM logger; transforms events into ledger / timeline entries | Ledger write, timeline append | Immutable `evidence_ledger` rows |
| **Review** | Human-in-the-loop node; analyst verdict review | Break-glass (if needed) | `approved`, `escalated`, `closed_benign`, `continue_hunt` |

## 4. Canonical Hunt Flow

```
Seed → Alpha (create case, start ledger)
         ↓
      Tracker (enrich, write hypothesis + evidence)
         ↓
      Flanker (pivot, create branches if needed)
         ↓
      Closer (assemble verdict)
         ↓
      Review (analyst decides)
         ↓
   ┌─→ Approved → Learning Queue → Case Memory
   ├─→ Escalated → Alert / Ticket
   ├─→ Closed Benign → Archive
   └─→ Continue Hunt → Back to Alpha
```

Scribe writes to the ledger in parallel throughout the flow.

## 5. Data Storage

### Postgres Tables (Key)

| Table | Purpose | Key Columns |
|---|---|---|
| `cases` | Case metadata | `id`, `seed`, `status`, `version`, `created_at`, `updated_at` |
| `branches` | Branch sub-states | `id`, `case_id`, `parent_branch_id`, `depth`, `status` |
| `evidence_ledger` | Immutable audit log | `id`, `case_id`, `branch_id`, `entry_type`, `content`, `agent_run_id`, `content_hash`, `prev_hash` |
| `hypotheses` | Tracker / Flanker outputs | `id`, `case_id`, `branch_id`, `text`, `confidence`, `source` |
| `pii_salts` | Per-case salt for pseudonymization | `id`, `case_id`, `salt` |
| `pii_mappings` | Token-to-original mapping (encrypted) | `id`, `case_id`, `token`, `original_value`, `identifier_type` |
| `breakglass_audit` | Audit of raw-PII access | `id`, `case_id`, `analyst_id`, `field_accessed`, `timestamp`, `justification` |
| `crypto_shred_keys` | Per-case DEK (wrapped by KEK) | `case_id`, `wrapped_dek`, `kek_id`, `created_at` |
| `learning_queue` | Approved cases awaiting ingestion | `case_id`, `approved_at`, `ingested_at`, `retry_count`, `last_error` |

### pgvector

RAG embeddings are stored in a `pgvector` column inside Postgres (reuses the existing database). Haystack pipelines manage index creation and retrieval.

## 6. Event Bus

**NATS JetStream** subjects:

| Subject | Payload | Consumers |
|---|---|---|
| `hunt.task.alpha` | Case creation / seed dispatch | Alpha Dispatcher |
| `hunt.finding.tracker` | Tracker hypotheses + evidence | Alpha (arbitration), Closer |
| `hunt.finding.flanker` | Flanker branches + pivots | Alpha (arbitration), Closer |
| `hunt.status.verdict` | Verdict assembly complete | Review node |
| `hunt.status.review` | Analyst decision posted | Alpha, Learning Queue |
| `hunt.branch.created` | New branch notifications | Scribe, Analyst Console |
| `wolfpack.alerts` | Operational / security alerts | AlertManager, webhook |

Consumer groups ensure exactly-one processing per case branch.

## 7. Observability

### OTel Span Hierarchy

```
Span: wolfpack.case (case_id)
  ├─ Span: wolfpack.node.alpha
  │     ├─ Span: wolfpack.agent.llm (model_name, provider)
  │     └─ Event: tool_call (name, input_hash, output_hash)
  ├─ Span: wolfpack.node.tracker
  │     ├─ Span: wolfpack.rag.threat_intel (query_hash, result_count)
  │     └─ Span: wolfpack.adapter.syslog (latency)
  ├─ Span: wolfpack.node.flanker
  │     ├─ Span: wolfpack.rag.case_history
  │     └─ Event: branch_created (branch_id, depth)
  ├─ Span: wolfpack.node.closer
  └─ Span: wolfpack.node.scribe
        └─ Event: ledger_write (seq, content_hash)
```

### Baggage Propagation

`case_id`, `branch_id`, `agent_run_id` are carried as OTel baggage across all spans and NATS messages.

### Sampling

- **Security events** (ledger writes, break-glass, tool-allowlist violations): always-on (100 %)
- **LangGraph node transitions**: always-on
- **RAG / adapter tool calls**: 10 % probabilistic (configurable)

### Dashboards

- **MLflow** (`full` profile): per-agent latency, tool call counts, retry rates, eval scores, per-branch token spend
- **Jaeger** (`tracing` profile): distributed trace view
- **NATS monitoring** (`:8222`): stream depth, consumer lag

## 8. Security Model

### PII Pseudonymization Flow

1. Telemetry arrives containing identifiers (IPs, usernames, emails).
2. NER strips free-text identifiers before context assembly.
3. Deterministic pseudonymization replaces structured identifiers with a per-case salt + hash; the per-case salt lives in `pii_salts`.
4. Token→original mappings are stored in `pii_mappings` with `original_value` encrypted (AES-256-GCM) under a per-case key, so a DB read alone does not expose raw PII.
5. Analyst can request break-glass rehydration (logged to `breakglass_audit`).

### Break-Glass Flow

1. Analyst clicks "Show raw" in the Analyst Console.
2. System looks up the per-case salt in `pii_salts` and the encrypted mapping in `pii_mappings`, then decrypts the original value.
3. Raw value is rehydrated and displayed **once**.
4. Invocation is written to `breakglass_audit` with `analyst_id`, `field_accessed`, `timestamp`, `justification`.

### Crypto-Shredding Flow

1. Per-case DEK is generated on case creation.
2. DEK is wrapped by the deployment KEK (stored in local KMS / HSM).
3. Wrapped DEK is stored in `crypto_shred_keys`.
4. On erasure request, the `crypto_shred_keys` row is deleted.
5. PII data becomes unrecoverable (DEK is gone); case metadata remains readable.
6. Ledger hash chain is verified intact after shredding.

### Hash-Chained Ledger

Each `evidence_ledger` row stores:
- `seq` (monotonic per case, assigned by the insert trigger)
- `content` (the event payload, JSONB)
- `prev_hash` (SHA-256 of the previous row’s content hash)
- `content_hash` (SHA-256 of this row’s content)

Tampering any row breaks the chain. Integrity is checked by the SQL function `wolfpack.verify_chain(case_id)` and the Python helper `wolfpack.schemas.ledger.verify_chain()`.
