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

### Tier 1 — Engineering Rigor

Focuses on automated testing, static quality gates, and zero-friction repeatability.

* [ ] **Comprehensive GitHub Actions CI Workflow**
  * Automated linting with `ruff` and unit testing with `pytest`.
  * Bash static analysis with `shellcheck` across all `automation/scripts/` and container entrypoints.
  * Structural YAML linting (`yamllint`).
  * Prometheus rule syntax checking with `promtool check rules`.
  * Alertmanager config validation with `amtool check-config`.
  * CMDB configuration schema validation (`validate_cmdb.py`).
  * Docker Compose build verification.
* [ ] **Automated E2E Chaos Test Harness** (`tests/integration/test_chaos_e2e.py`)
  * Programmatic assertion of full incident lifecycles triggered via `chaos.sh`.
  * Verifies `CREATED` $\rightarrow$ `ACKNOWLEDGED` $\rightarrow$ `IN_PROGRESS` $\rightarrow$ `RESOLVED` / `ESCALATED` state transitions.
  * Validates worker claim, automated playbook execution, service recovery verification, SLA metric increments, and PDF report generation.
* [ ] **Clean-Clone Zero-Friction Verification**
  * End-to-end verification of `./automation/scripts/bootstrap.sh` on a fresh environment strictly following `README.md`.

---

### Tier 2 — Extensibility & Core Platform Primitives

Establishes fundamental reliability primitives and modular interfaces for platform growth.

* [ ] **Reliability & Tracing Primitives**
  * Introduce `correlation_id` across Alertmanager payloads and internal log context.
  * Introduce `execution_id` tracking individual worker playbook attempts.
  * Formally document and standardize idempotency tokens for webhook delivery and retry safety.
* [ ] **Generalized Typed Event Model**
  * Evolve the current append-only `incident_events` audit trail into a generalized typed event model (`IncidentCreated`, `IncidentAcknowledged`, `RemediationStarted`, `RemediationCompleted`, `SLABreached`, `ReportGenerated`).
  * Enables decoupled in-process event consumption for metrics, notifications, and AI analysis.
* [ ] **Formalized REST API (`/api/v1`)**
  * Formalize and evolve the existing webhook/Flask API (`http://localhost:5001`) into a versioned `/api/v1` interface.
  * Endpoints for incident listing, detail, timeline retrieval, operator lifecycle transitions (`acknowledge`, `resolve`, `close`), and operational metrics.
* [ ] **Remediation Plugin Registry**
  * Refactor playbook dispatch logic in `automation/response_engine/remediation/` into a plugin registry (`registry.py`, `base.py`).
  * Supports extensible multi-step playbook execution without modifying core worker dispatch loops.

---

### Tier 3 — Operational Intelligence

Adds domain intelligence, noise reduction, and AI assistance over operational data.

* [ ] **Alert Correlation & Problem Management**
  * Group related concurrent alert firings (e.g., downstream API failures caused by a PostgreSQL outage) into a unified **Problem** record (`PROBLEM-001`) using CMDB dependency graphs (`dependencies: [postgres]`).
* [ ] **Operational Analytics & Noise Metrics**
  * Track auto-remediation success rate, alert-to-incident conversion, alert noise reduction, repeat incident rate, and SLA compliance metrics.
* [ ] **Incident Similarity & Historical Pattern Matching**
  * Historical similarity matching comparing active incident symptoms against past resolved incidents and RCAs.
* [ ] **AI Knowledge Assistant (Ops RAG)**
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
