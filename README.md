# SentinelOps

SentinelOps is an enterprise-inspired monitoring and incident response platform built with Docker, Prometheus, Alertmanager, Grafana, Python, Flask, and PostgreSQL.

Most monitoring projects stop once an alert has been generated. SentinelOps focuses on everything that happens afterwards: transforming alerts into incidents, enriching them with operational context, attempting automated remediation, verifying recovery, and recording a complete audit trail.

The project was built to explore how production incident response systems coordinate detection, enrichment, remediation, verification, and auditing—not simply how monitoring systems generate alerts.

---

# Current Status

**Phase 1 is complete and fully verified against real infrastructure.**

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
* Six production-style alert rules

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

Recovery verification supports:

* HTTP health endpoints
* Docker `HEALTHCHECK`
* Container running-state verification

## Operational Tooling

* `bootstrap.sh`
* `teardown.sh`
* `chaos.sh`
* `validate_cmdb.py`

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

| Service      | URL                   |
| ------------ | --------------------- |
| Grafana      | http://localhost:3001 |
| Prometheus   | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |
| API          | http://localhost:5001 |

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
│   ├── response_engine/     # Incident response engine
│   └── scripts/             # Bootstrap, teardown, chaos and validation tools
├── cmdb/                    # Service configuration
├── diagnostics/             # Collected diagnostics
├── docker/                  # Container definitions and configuration
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
* Local secrets stored in `.env`, which is excluded from version control.
* Local-only chaos tooling designed to operate exclusively on this project's Docker Compose stack.

These trade-offs are appropriate for a learning environment but would be replaced in production with least-privilege credentials, authenticated monitoring endpoints, and a restricted interface to the container runtime.

---

# Future Work

Phase 1 establishes the complete autonomous incident response loop. Future phases extend the platform with additional operational capabilities rather than changing its core architecture.

### Incident Management

* Maintenance windows
* SLA tracking
* Incident reporting

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
