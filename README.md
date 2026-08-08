# SentinelOps

SentinelOps is an enterprise-inspired monitoring and incident response platform built with Docker, Prometheus, Alertmanager, Grafana, Python, Flask, and PostgreSQL.

Most monitoring projects stop once an alert has been generated. SentinelOps focuses on everything that happens afterwards: transforming alerts into incidents, enriching them with operational context, attempting automated remediation, verifying recovery, and recording a complete audit trail.

The project was built to explore how production incident response systems coordinate detection, enrichment, remediation, verification, and auditing—not simply how monitoring systems generate alerts.

---

# Current Status

**Phase 1 is complete and fully verified against real infrastructure.** Phase 2 ("the operational layer") is in progress; operational visibility (issue #4) and incident reporting (issue #5) are both complete and merged.

The complete autonomous incident pipeline has been implemented and validated:

> detect → enrich → acknowledge → remediate → verify → resolve (or escalate) → audit

Phase 1 includes:

* Prometheus, Alertmanager, and Grafana
* CMDB-driven incident enrichment
* PostgreSQL-backed incident management
* Independent webhook ingestion and remediation services
* Explicit incident state machine
* Autonomous remediation playbooks
* Service-specific recovery verification
* Structured JSON logging
* Bootstrap, teardown, and chaos tooling
* CMDB validation
* Operational runbooks
* Architecture Decision Records (ADRs)

**Phase 2** extends the platform with an operational layer: SLA tracking,
self-monitoring, and `/metrics` endpoints (issue #4), plus a live health
page, PDF incident reports, and an operator workflow for closing incidents
with a manual Root Cause Analysis (RCA) (issue #5).

Future phases focus on extending the platform rather than completing the core incident response workflow.

---

# Technologies

| Category       | Technologies                      |
| -------------- | --------------------------------- |
| Monitoring     | Prometheus, Alertmanager, Grafana |
| Backend        | Python, Flask                     |
| Database       | PostgreSQL                        |
| Infrastructure | Docker, Docker Compose            |
| Automation     | Docker SDK for Python             |
| Documentation  | Markdown, ADRs                    |

---

# Architecture

SentinelOps separates monitoring from incident response.

The monitoring stack (Prometheus, Alertmanager, and Grafana) is responsible for detecting operational problems and generating alerts. The response engine takes over once an alert is received, enriching it with operational context, managing its lifecycle, attempting automated remediation, and recording a complete audit trail.

The architecture is intentionally divided into three independent layers:

* **Monitored Estate** — the services being observed and managed.
* **Observability** — Prometheus, Alertmanager, and Grafana, responsible only for collecting metrics, evaluating alert rules, and presenting operational data.
* **Response Engine** — webhook ingestion and remediation services that transform alerts into incidents and coordinate automated recovery.

Within the response engine, webhook ingestion and remediation are implemented as separate services communicating exclusively through PostgreSQL. This decouples alert acknowledgement from remediation, allowing Alertmanager webhooks to be acknowledged immediately while longer-running recovery operations continue independently.

The complete system architecture, incident lifecycle, and component interaction are documented in:

* `docs/ARCHITECTURE.md`
* `docs/DESIGN.md`
* `docs/adr/`

---

# Core Design Principles

Several architectural principles guide the implementation:

* **Alert-driven incident management** — alerts become durable incidents rather than transient webhook requests.
* **CMDB-driven remediation** — operational policy is defined in configuration, not hard-coded into the response engine.
* **Explicit incident state machine** — every lifecycle transition is validated and recorded.
* **Autonomous but bounded remediation** — automated recovery is attempted within clearly defined verification and retry limits before escalation.

These principles are documented in the project's Architecture Decision Records
(ADRs).

---

# Features

## Monitoring

* Prometheus metrics collection
* Alertmanager alert routing
* Grafana dashboards
* Seven production-style alert rules, including `ResponseEngineDown` for the response engine's own self-monitoring

## Response Engine

* Alert ingestion and CMDB enrichment
* Fingerprint-based incident deduplication
* PostgreSQL-backed incident store
* Concurrent worker coordination using `FOR UPDATE SKIP LOCKED`
* Explicit incident state machine
* Structured audit trail
* Structured JSON logging

## Automated Remediation

Implemented Phase 1 playbooks:

* `restart_service`
* `collect_diagnostics`
* `disk_cleanup`

Recovery verification supports:

* HTTP health endpoints
* Docker `HEALTHCHECK`
* Container running-state verification

## Operational Tooling

* `bootstrap.sh` — Validates environment and starts the Docker Compose stack with post-start health checks.
* `teardown.sh` — Stops the platform cleanly; `--purge` flag removes persistent data.
* `backup.sh` — Archives Grafana dashboards and PostgreSQL database to `backups/sentinelops-<timestamp>.tar.gz`; retains the newest `BACKUP_RETENTION` archives (default: 7). Configurable via `BACKUP_DIR` and `BACKUP_RETENTION` environment variables. Restore with: `docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < postgres.sql`
* `healthcheck.sh` — One-shot status check of every component (containers, HTTP endpoints, database). Exits 0 if all pass, 1 if anything is down.
* `chaos.sh` — Chaos testing for exercising the incident response pipeline.
  - `stop <service>` — Stop a Compose service.
  - `fill` — Allocate a bounded file to trigger `DiskPressure` alert.
  - `reset` — Remove the disk filler.
* `validate_cmdb.py` — Validates the CMDB configuration against alert rules and remediation playbooks.

## Operational Visibility (Phase 2)

* Prometheus `/metrics` endpoints on the worker and webhook handler
* Live SLA breach detection (`sentinelops_sla_breaches_total`), evaluated continuously against each incident's CMDB-defined `response_minutes`/`resolution_minutes`, not just at state transitions
* Self-monitoring: `ResponseEngineDown` alert rule and a worker heartbeat gauge, detecting a hung poll loop even when the process is still technically running
* MTTR/MTTA histograms (`sentinelops_incident_resolution_seconds`, `sentinelops_incident_response_seconds`), observed directly in the state machine's `transition()`
* Second Grafana dashboard ("SentinelOps — Response Engine"): MTTR, MTTA, queue depth, worker heartbeat age, open incidents by status, remediation success rate, SLA breaches over time — all calculated from real recorded incidents, not seeded data

## Incident Reporting

* Dedicated `report-generator` service
* Static health page served by nginx
* Automatic PDF incident reports generated when incidents are closed
* Operator-driven incident closure through `close_incident.sh`
* Unified incident timeline combining lifecycle events and remediation history
* Conditional diagnostic evidence when `collect_diagnostics` was executed
* Manual Root Cause Analysis (RCA) included in every completed report

---

# Documentation

The repository is intentionally split into focused documents. The README provides an overview of the project, while the documents below describe the architecture, design rationale, operational procedures, and engineering decisions in greater detail.

| Document                          | Purpose                                                                                            |
| --------------------------------- | -------------------------------------------------------------------------------------------------- |
| `README.md`                       | Project overview and getting started                                                               |
| `docs/ARCHITECTURE.md`            | System architecture, components, and incident lifecycle                                            |
| `docs/DESIGN.md`                  | Original design, implementation roadmap, and project scope                                         |
| `docs/adr/`                       | Architecture Decision Records documenting major design decisions                                   |
| `docs/runbooks/`                  | Operational procedures for implemented remediation playbooks                                       |
| `docs/implementation-findings.md` | Engineering discoveries, implementation trade-offs, and lessons learned while building the project |

`docs/DESIGN.md` was reconciled to v1.1 after Phase 1 shipped, folding in discoveries recorded in `docs/implementation-findings.md`; see `CHANGELOG.md` for a summary.

---

# Quick Start

## Requirements

* Docker
* Docker Compose

## Clone the repository

```bash
git clone <repository-url>
cd SentinelOps
```

## Configure the environment

Create a local configuration file from the provided template:

```bash
cp .env.example .env
```

Adjust any values if required for your environment.

The environment file also contains dedicated PostgreSQL credentials for the response engine and report generator. Optional tuning parameters such as the health page refresh interval and PDF scan interval have sensible built-in defaults and normally do not need to be configured.

## Validate the environment

Before starting the platform, verify that all prerequisites and configuration are valid:

```bash
./automation/scripts/bootstrap.sh --validate-only
```

This performs validation without creating or modifying any containers.

## Start SentinelOps

```bash
./automation/scripts/bootstrap.sh
```

The bootstrap script validates the environment, starts the Docker Compose stack, and performs post-start validation checks.

Once the platform is running, the primary interfaces are:

| Service          | URL                             |
| ---------------- | -------------------------------- |
| Grafana          | http://localhost:3001            |
| Prometheus       | http://localhost:9090            |
| Alertmanager     | http://localhost:9093            |
| API              | http://localhost:5001            |
| Health page      | http://localhost:8081/health/    |
| Incident reports | http://localhost:8081/reports/   |

## Closing an incident

Resolved incidents remain open for operator review until a Root Cause
Analysis has been written.

Launch the guided workflow with:

```bash
./automation/scripts/close_incident.sh INCIDENT_REFERENCE
```

The script opens your configured editor with an RCA template. After saving,
the incident transitions to `CLOSED`. The `report-generator` service picks up
newly closed incidents automatically and publishes a PDF report under
`/reports/` shortly after.

## Shut down the environment

To stop the platform cleanly:

```bash
./automation/scripts/teardown.sh
```

To stop the platform and remove persistent data:

```bash
./automation/scripts/teardown.sh --purge
```

---

# Chaos Testing

SentinelOps includes a lightweight chaos tool for exercising the autonomous incident response pipeline.

For example, stopping the API service:

```bash
./automation/scripts/chaos.sh stop api
```

Exercises the complete autonomous incident pipeline:

* Alert generation
* Alertmanager webhook delivery
* Incident creation and enrichment
* Worker claim
* Automated remediation
* Recovery verification
* Resolution or escalation

The chaos tool operates only on services defined in the project's Docker Compose configuration and is intended exclusively for local development and testing.

---

# Repository Structure

```text
SentinelOps/
├── automation/
│   ├── response_engine/     # Webhook handler, worker, remediation logic
│   ├── report_generator/    # Health page, PDF renderer, templates
│   └── scripts/             # Operational tooling
├── cmdb/                    # Service configuration
├── diagnostics/             # Collected diagnostics
├── docker/                  # Container definitions and configuration
│   ├── api/
│   ├── report-generator/
│   ├── webhook-handler/
│   ├── worker/
│   ├── nginx/
│   ├── postgres/
│   ├── prometheus/
│   ├── grafana/
│   └── alertmanager/
├── docs/
│   ├── adr/                 # Architecture Decision Records
│   ├── runbooks/            # Operational runbooks
│   ├── ARCHITECTURE.md
│   ├── DESIGN.md
│   └── implementation-findings.md
├── LICENSE
├── README.md
└── docker-compose.yml
```

---

# Security Considerations

SentinelOps is intentionally designed as a local engineering lab rather than a production deployment.

The remediation worker is granted access to the Docker Engine through `/var/run/docker.sock` so it can inspect containers, restart services, and collect diagnostics. The webhook handler has no Docker Engine access. This separation reduces the privileges exposed to externally reachable components while allowing the worker to perform autonomous remediation.

Additional Phase 1 simplifications include:

* A shared Grafana administrator account configured through `GRAFANA_ADMIN_PASSWORD`.
* Prometheus and Alertmanager exposed without authentication.
* The Alertmanager webhook receiver (/alerts) is intentionally unauthenticated in Phase 1 because all services communicate over the project's private Docker network and the endpoint is not exposed on a host port. In a production deployment, this endpoint should be authenticated or otherwise restricted, as it creates incident records and can trigger automated container restarts.
* Local secrets stored in `.env`, which is excluded from version control.
* Local-only chaos tooling designed to operate exclusively on this project's Docker Compose stack.

Phase 2 adds two more unauthenticated nginx routes, `/health/` and `/reports/`. `/reports/` is the more sensitive of the two: incident reports include collected diagnostics (container logs and stats) and the operator-written Root Cause Analysis, and references are sequential (`INC-2026-001.pdf`, `INC-2026-002.pdf`, ...) and therefore easy to enumerate. As with the rest of Phase 1's unauthenticated surface, this is an accepted lab-only trade-off, not an oversight — a production deployment would put both routes behind authentication.

The response engine and report generator connect to PostgreSQL as dedicated least-privilege roles (`response_engine`, `report_generator`) rather than the shared superuser credential; see `docker/postgres/init/007_create_roles.sh` for the exact grants.

These trade-offs are appropriate for a learning environment but would be replaced in production with least-privilege credentials, authenticated monitoring endpoints, and a restricted interface to the container runtime.

---

# Future Work

Phase 1 establishes the complete autonomous incident response loop. Future phases extend the platform with additional operational capabilities rather than changing its core architecture. Phase 2 operational visibility (SLA tracking, self-monitoring, `/metrics`) and incident reporting (health page, PDF reports, RCA workflow) are complete — see Features above.

### Incident Management

* Maintenance windows

### Automation

* Additional remediation playbooks
* Notification integrations
* Automated testing

### Platform

* ShellCheck integration
* CI/CD improvements
* Cloud deployment

The complete implementation roadmap is documented in `docs/DESIGN.md`.

---

# License

This project is licensed under the MIT License.
