# SentinelOps — Implementation & Architectural Roadmap

This document serves as the authoritative source of truth for current planning priorities, architectural phase boundaries, and post-v1 platform evolution for **SentinelOps**.

For overall architectural design and decision history, see `docs/DESIGN.md` and `docs/adr/`.

---

## Document Hierarchy & Governance

To maintain clarity across project documentation:

* **`ROADMAP.md`** *(This file)* — What comes next, priorities, technical rationale, and phase boundaries.
* **`docs/DESIGN.md`** — Core design principles, failure-independence models, and architectural rationale.
* **`README.md`** — High-level portfolio summary, system capabilities, and getting started guide.
* **`CHANGELOG.md`** — Historical record of design, architecture, and feature evolution.

---

## Phase 3 — Production Readiness & Extensibility

Phase 3 transitions SentinelOps from a validated incident pipeline lab into a production-ready, extensible platform with strong engineering rigor and operational intelligence.

Execution is tracked on GitHub: **[Epic #19](https://github.com/viceda-s/SentinelOps/issues/19)** and the **[SentinelOps: Phase 3](https://github.com/users/viceda-s/projects/3)** project board.

Tier 1 and Tier 2 items are decomposed into leaf task issues. Tier 3 items are deliberately held at item level under `status:planned` until each has its own design spec in `docs/specs/` — a leaf issue is only created once its implementation scope has been architecturally decided.

### Tier 1 — Engineering Rigor

Focuses on automated testing, static quality gates, and zero-friction repeatability.

* [x] **Comprehensive GitHub Actions CI Workflow** ([#23](https://github.com/viceda-s/SentinelOps/issues/23))
  * Shipped in `.github/workflows/quality-gate.yml`: `ruff` lint and format checks, `pytest` against an ephemeral PostgreSQL service container, `shellcheck` across `automation/scripts/` and container entrypoints, and configuration validation via `bootstrap.sh --validate-only` (`compose config`, `promtool check rules`, `amtool check-config`, `validate_cmdb.py`, runbook mapping).
  * Remaining gaps tracked separately: structural YAML linting ([#34](https://github.com/viceda-s/SentinelOps/issues/34)), Docker Compose *build* verification ([#35](https://github.com/viceda-s/SentinelOps/issues/35)), and a gated E2E chaos job ([#36](https://github.com/viceda-s/SentinelOps/issues/36)).
* [ ] **Automated E2E Chaos Test Harness** (`tests/integration/test_chaos_e2e.py`) — [#24](https://github.com/viceda-s/SentinelOps/issues/24)
  * Programmatic assertion of full incident lifecycles triggered via `chaos.sh`.
  * Verifies `CREATED` $\rightarrow$ `ACKNOWLEDGED` $\rightarrow$ `IN_PROGRESS` $\rightarrow$ `RESOLVED` / `ESCALATED` state transitions.
  * Validates worker claim, automated playbook execution, service recovery verification, SLA metric increments, and PDF report generation.
* [ ] **Clean-Clone Zero-Friction Verification** — [#25](https://github.com/viceda-s/SentinelOps/issues/25)
  * End-to-end verification of `./automation/scripts/bootstrap.sh` on a fresh environment strictly following `README.md`.

---

### Tier 2 — Extensibility & Core Platform Primitives

Establishes fundamental reliability primitives and modular interfaces for platform growth.

* [ ] **Reliability & Tracing Primitives** — [#26](https://github.com/viceda-s/SentinelOps/issues/26)
  * Introduce `correlation_id` across Alertmanager payloads and internal log context.
  * Introduce `execution_id` tracking individual worker playbook attempts.
  * Formally document and standardize idempotency tokens for webhook delivery and retry safety.
* [ ] **Generalized Typed Event Model** — [#27](https://github.com/viceda-s/SentinelOps/issues/27)
  * Evolve the current append-only `incident_events` audit trail into a generalized typed event model (`IncidentCreated`, `IncidentAcknowledged`, `RemediationStarted`, `RemediationCompleted`, `SLABreached`, `ReportGenerated`).
  * Enables decoupled in-process event consumption for metrics, notifications, and AI analysis.
* [ ] **Formalized REST API (`/api/v1`)** — [#28](https://github.com/viceda-s/SentinelOps/issues/28)
  * Formalize and evolve the existing webhook/Flask API (`http://localhost:5001`) into a versioned `/api/v1` interface.
  * Endpoints for incident listing, detail, timeline retrieval, operator lifecycle transitions (`acknowledge`, `resolve`, `close`), and operational metrics.
* [ ] **Remediation Plugin Registry** — [#29](https://github.com/viceda-s/SentinelOps/issues/29)
  * Refactor playbook dispatch logic in `automation/response_engine/remediation/` into a plugin registry (`registry.py`, `base.py`).
  * Supports extensible multi-step playbook execution without modifying core worker dispatch loops.
* [ ] **Configurable Remediation Bounds & Blast-Radius Controls** — [#43](https://github.com/viceda-s/SentinelOps/issues/43)
  * **Externalize existing timing constants.** `VERIFY_TIMEOUT`, `VERIFY_INTERVAL`, `RESTART_COOLDOWN`, and `MAX_RESTART_ATTEMPTS` are currently module-level constants in `remediation.py`, so shortening a verification window for a demo or a test requires a source edit. Introduce a `RemediationSettings` dataclass in `config.py` (following the existing `PrometheusSettings` / `DiagnosticsSettings` pattern) supplying fleet-wide defaults, with per-service verification timing resolved from the CMDB `verification:` block — a Postgres restart legitimately needs a longer window than nginx.
  * **Resolve settings at worker startup, not import time.** The existing `from_env()` module globals are evaluated on import, which prevents tests from adjusting timing without a module reload. Pass a resolved settings object into playbook execution instead.
  * **Add missing autonomy bounds.** The platform currently has no per-signature remediation cooldown, no rate limit, no lifetime cap on automated actions, and no operator kill-switch; maintenance-window suppression is the only existing brake. Nothing prevents a flapping alert from repeatedly re-triggering remediation.
  * Requires extending `validate_cmdb.py` to type- and bounds-check the new verification fields, adding the new keys to `.env.example`, and superseding **ADR 008**, which explicitly records these bounds as hard-coded constants (also referenced in `docs/ARCHITECTURE.md`, ADR 001, and `docs/implementation-findings.md`).

---

### Tier 3 — Operational Intelligence

Adds domain intelligence, noise reduction, and AI assistance over operational data.

* [ ] **Alert Correlation & Problem Management** — [#31](https://github.com/viceda-s/SentinelOps/issues/31)
  * Group related concurrent alert firings (e.g., downstream API failures caused by a PostgreSQL outage) into a unified **Problem** record (`PROBLEM-001`) using CMDB dependency graphs (`dependencies: [postgres]`).
* [ ] **Operational Analytics & Noise Metrics** — [#30](https://github.com/viceda-s/SentinelOps/issues/30)
  * Track auto-remediation success rate, alert-to-incident conversion, alert noise reduction, repeat incident rate, and SLA compliance metrics.
* [ ] **Incident Similarity & Historical Pattern Matching** — [#32](https://github.com/viceda-s/SentinelOps/issues/32)
  * Historical similarity matching comparing active incident symptoms against past resolved incidents and RCAs.
* [ ] **AI Knowledge Assistant (Ops RAG)** — [#33](https://github.com/viceda-s/SentinelOps/issues/33)
  * Targeted operational RAG assistant over runbooks (`docs/runbooks/`), ADRs (`docs/adr/`), historical RCAs, and incident timelines.
  * Assists operators during incident triage and pre-populates draft Root Cause Analysis (RCA) notes during `./automation/scripts/close_incident.sh`.

---

## Post-v1 Roadmap (Future Platform Expansion)

Features intentionally deferred to future iterations to maintain focus on core incident lifecycle architecture.

* **Production Deployment Hardening**
  * Authentication & Role-Based Access Control (RBAC) across monitoring, health, and report endpoints.
  * Secret management integration (e.g., Vault, AWS Secrets Manager) replacing plain `.env` files.
  * Docker API socket proxy exposing restricted daemon endpoints instead of raw socket mounting.
  * Authenticated Prometheus and Alertmanager receivers.
* **Infrastructure & Automation**
  * Cloud deployment definitions (AWS / GCP / Azure) via Terraform and Ansible.
  * Centralized log aggregation with Loki or Vector.
  * Multi-channel external notifications (Slack, PagerDuty, Microsoft Teams, custom Webhooks).

---

## Technology Trade-offs & Anti-Patterns

SentinelOps deliberately avoids unnecessary infrastructural complexity:

| Deferred Tech | Avoided Complexity | Architectural Alternative Used in SentinelOps |
| :--- | :--- | :--- |
| **Kubernetes** | Cluster management, complex YAML manifests, resource overhead | Multi-container Docker Compose estate with single-host health checks |
| **Kafka / RabbitMQ** | Broker management, topic schemas, partition rebalancing | PostgreSQL `FOR UPDATE SKIP LOCKED` worker queues |
| **Redis** | In-memory cache invalidation, split-brain state risks | PostgreSQL atomic row-level locking (`events.py`) & partial unique indexes |
| **Microservice Bloat** | Distributed tracing overhead, RPC boilerplate | Decoupled process model (Handler, Worker, Report Generator) over PostgreSQL |

These trade-offs demonstrate that system scalability comes from clean architectural boundaries and database primitives rather than excessive infrastructure.
