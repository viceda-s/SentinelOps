# SentinelOps

An enterprise-inspired monitoring and incident response lab: Prometheus, Grafana, Docker, Python, and PostgreSQL, wired together to practise the full incident lifecycle — detect, triage, enrich, remediate, verify, document, audit — not just the monitoring part of it.

**Status: Phase 1 in progress.** The monitored estate and part of the observability stack are built and verified end-to-end. The response engine (webhook handler, remediation worker, incident storage) hasn't been built yet. See [Current status](#current-status) below for exactly what works today versus what's still ahead. Design reasoning for the whole project lives in [`docs/DESIGN.md`](docs/DESIGN.md).

## Overview

Most monitoring labs stop at "the alert fired." SentinelOps is built to show what happens after that: how an alert becomes an incident, who owns it, what gets fixed automatically, what has to go to a human, and what record is left behind. Prometheus and Grafana are components here, not the subject — the subject is incident management.

The full design rationale, including what was deliberately left out and why, is in [`docs/DESIGN.md`](docs/DESIGN.md).

## Architecture

Three groups of services:

- **Monitored estate** — `nginx`, `api`, `postgres`, `node-exporter`, `cAdvisor`. The thing being watched.
- **Observability** — Prometheus, Alertmanager, Grafana. Detection and routing.
- **Response engine** *(not yet built)* — webhook handler, remediation worker, report generator, backed by Postgres. Turns alerts into incidents, tries to fix them, and records what happened.

See `docs/DESIGN.md`'s architecture diagram and "How a fault becomes a resolved incident" section for the full flow and the reasoning behind splitting the webhook handler from the remediation worker.

## Current status

**Built and verified:**

- The full monitored estate is up, wired, and tested end-to-end: `api` genuinely depends on Postgres (health check queries the database, not just the process), `nginx` reverse-proxies to `api`, and all services expose real metrics.
- Prometheus is scraping `api`, `node-exporter`, and `cAdvisor`.
- Alertmanager is running and confirmed reachable from Prometheus (`/api/v1/alertmanagers` shows it as active).
- 6 of 9 alert rules from the design are written and confirmed loaded: `ServiceDown`, `HighCPU`, `HighMemory`, `DiskPressure`, `HighErrorRate`, `HighLatency`.
- `DiskPressure` excludes Docker Desktop's internal pseudo-filesystems (`erofs`, `overlay`, `squashfs`, `tmpfs`) and mount points (`/oldroot`, `/run*`), so it no longer false-positives on the VM's own internals.

**Known gap:**

- `HighErrorRate`'s ratio only reflects errors caught inside route handlers (`OperationalError`); an unhandled exception that gunicorn turns into a 500 doesn't currently increment either the error or request counter, since request accounting happens inline in each route rather than in Flask middleware. Fixing this means moving metric recording to `after_request`/`teardown_request` so every request is counted regardless of how it ends — not yet done.

**Not yet built:**

- The remaining 3 alert rules: `ContainerRestartLoop` needs a restart-counting approach cAdvisor doesn't expose directly; `ResponseEngineDown` and `RemediationFailureRateHigh` depend on a response engine that doesn't exist yet.
- Grafana (not wired into `docker-compose.yml` yet).
- The entire response engine: data model, webhook handler, state machine, remediation worker, playbooks.
- CMDB (`cmdb/services.yaml` doesn't exist yet), `bootstrap.sh`, `teardown.sh`, `chaos.sh`.
- Runbooks, ARCHITECTURE.md, and ADRs.

## Quick Start

This covers what actually runs today — the monitored estate and the observability stack built so far. There's no incident lifecycle to demonstrate yet, since the response engine doesn't exist.

### Prerequisites

- Docker and Docker Compose
- `curl` (or a browser) to poke at the running services

### Run it

```bash
git clone <this-repo>
cd SentinelOps
cp .env.example .env
# edit .env and set a real POSTGRES_PASSWORD
docker compose up -d
```

### Check it's working

```bash
curl http://localhost:5001/health    # api -> postgres round trip
curl http://localhost:5001/items     # seeded placeholder data
curl http://localhost:8081/health    # same thing, through nginx
```

Prometheus UI: `http://localhost:9090` (check `/targets` — `api`, `node-exporter`, `cadvisor` should all show `UP`).

Alertmanager UI: `http://localhost:9093`.

### Tear down

```bash
docker compose down
```

## Repository Structure

```
SentinelOps/
├── README.md
├── docs/
│   └── DESIGN.md
├── docker-compose.yml
├── .env.example
├── docker/
│   ├── api/              Flask app, Dockerfile, requirements
│   ├── nginx/            reverse proxy config
│   ├── postgres/init/    schema + seed data, runs on first boot
│   ├── prometheus/       scrape config, alert rules
│   └── alertmanager/     routing config
└── requirements-dev.txt
```

The full target layout — `automation/`, `cmdb/`, `docs/adr/`, `docs/runbooks/`, `reports/`, `tests/` — is in `docs/DESIGN.md`'s repository layout section. Those directories don't exist yet; they'll appear as the corresponding pieces get built.

## Incident Lifecycle

Not demonstrable yet — this section will describe the detect → triage → enrich → remediate → verify → document → audit flow once the response engine exists. Until then, see `docs/DESIGN.md`'s "How a fault becomes a resolved incident" section for the intended behavior.

## Runbooks

Not written yet. `docs/DESIGN.md` describes the intended format (symptom, detection, automated response, manual verification, escalation) and Phase 1's plan for two runbooks.

## Security Considerations

The response engine will need access to the Docker Engine API to restart unhealthy services. Once built, the Docker socket will be mounted directly into the engine container, which effectively gives it administrative control over the host.

This is a deliberate trade-off for a self-contained lab environment, not something to do in production. There, the right approach is:

- a Docker socket proxy exposing only the endpoints actually needed
- a scoped automation agent with the minimum privileges required
- orchestrator-native mechanisms rather than direct daemon access
- least privilege applied to every automation credential

Other lab-only compromises, some already in place: no authentication on Grafana or the health page, credentials supplied through `.env`. `.env` is gitignored, `.env.example` is committed with placeholder values, and `git status` gets checked before every push.

`chaos.sh` (not yet built) is an operator tool for fault injection and should never exist on a production host.

## Design Decisions

Full reasoning, including decisions made and alternatives considered, lives in `docs/DESIGN.md`. Formal ADRs (001, 003, 004, 005, 008 for Phase 1) will live in `docs/adr/` once written. Highlights so far:

- **PostgreSQL, not SQLite** — the handler, worker, and report generator will all read and write concurrently.
- **`api`'s health check queries Postgres**, rather than just confirming the process is alive — so a database outage produces a genuine, honest failure signal instead of a false "healthy."
- **`postgres:16-alpine`, not the Debian-based image** — same functionality, meaningfully smaller image, no loss of anything this project uses.

## Future Work

See `docs/DESIGN.md`'s Phases and "Later" sections for the full roadmap: Phase 2 (maintenance windows, SLA tracking, PDF reports, `disk_cleanup`), Phase 3 (tests, shellcheck, a clean-machine run-through), and beyond (notifications, cloud deployment, Loki, alert correlation).

## License

This project is licensed under the [MIT License](LICENSE) — see the `LICENSE` file at the repository root for the full text.
