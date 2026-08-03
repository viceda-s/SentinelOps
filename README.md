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
- Grafana is wired into `docker-compose.yml`, with the Prometheus datasource and dashboards both provisioned from files in the repo rather than clicked together by hand (`editable: false` / `allowUiUpdates: false`, so nothing drifts between what's committed and what's running).
- The Phase 1 dashboard has all 8 panels: service availability (`up`), API request rate, API error rate, API latency (p95), CPU, memory, disk usage, and an Active alerts list (firing/pending/error states from Alertmanager). Built in the UI, exported with "Save to File" to keep real datasource references, and confirmed to reload correctly from disk after a container restart.
- The response engine's data model — `incidents`, `incident_events`, `remediation_attempts` — is written and verified against a fresh Postgres volume. `incidents` has a partial unique index on `fingerprint` so only one active incident can exist per alert condition at a time, without blocking a genuinely new incident once the old one reaches a terminal state (`CLOSED` or `SUPPRESSED_MAINTENANCE`). `incident_events` and `remediation_attempts` both use a composite unique constraint (`incident_id` + a per-incident sequence/attempt number) and a `RESTRICT`-on-delete foreign key back to `incidents`, so history can never be silently orphaned or deleted out from under an incident.
- The state machine (`automation/response_engine/state_machine.py`) is written and verified: a single `transition(conn, incident, to_status, actor, message)` function checks every status change against the allowed-transitions table from the design, updates `incidents` (including the right timestamp column for `ACKNOWLEDGED`/`RESOLVED`/`CLOSED`), and appends the corresponding `incident_events` row, all inside a transaction the caller controls. Invalid transitions raise and are logged rather than silently failing. Tested end-to-end through a full `NEW → ACKNOWLEDGED → IN_PROGRESS → RESOLVED → CLOSED` run plus a rejected out-of-band transition.
- `cmdb/services.yaml` has entries for all 5 estate services (`nginx`, `api`, `postgres`, `node-exporter`, `cadvisor`), keyed to match their Prometheus `job` labels, with ownership, criticality, SLA targets, and a `playbooks` mapping scoped to what's actually operationally sensible for each — `api` gets the full set of failure-mode playbooks, the two metrics exporters get only `ServiceDown`, since restarting them doesn't make sense as a response to alerts about the things *they* observe. Passes `automation/scripts/validate_cmdb.py` except for the (expected, unresolved) missing runbook file — see below.

**Known gap:**

- `HighErrorRate`'s ratio only reflects errors caught inside route handlers (`OperationalError`); an unhandled exception that gunicorn turns into a 500 doesn't currently increment either the error or request counter, since request accounting happens inline in each route rather than in Flask middleware. Fixing this means moving metric recording to `after_request`/`teardown_request` so every request is counted regardless of how it ends — not yet done.

**Not yet built:**

- The remaining 3 alert rules: `ContainerRestartLoop`, `ResponseEngineDown`, `RemediationFailureRateHigh`. The latter two depend on a response engine that doesn't exist yet. `ContainerRestartLoop` is blocked on an environment limitation: cAdvisor can't reach the Docker daemon here (`docker.sock` is a dangling symlink inside the container on Docker Desktop for Mac), so every cAdvisor metric — not just restart counts — carries only an anonymous cgroup `id`, with no container name or image label to key an alert on. Writing the rule against raw cgroup ids would make it both unreadable and impossible to map back to the `service` labels the rest of the design relies on, so it's deliberately left unwritten rather than worked around. Options for later: mount a working Docker socket into cAdvisor, add a small purpose-built exporter that reports restart counts by container name, or revisit this if the project ever moves to Kubernetes, where restart counts are a native, well-labeled metric.
- The rest of the response engine: webhook handler, remediation worker, playbooks. (The data model, state machine, and CMDB are built — see above.)
- Runbooks: `cmdb/services.yaml` references `docs/runbooks/service-down.md` for every service, but that file doesn't exist yet, so `validate_cmdb.py` currently — correctly — fails on it. Left unresolved on purpose rather than pointed at a placeholder, consistent with this project's fail-loudly-over-silently approach; will be fixed when the runbooks get written.
- `bootstrap.sh`, `teardown.sh`, `chaos.sh`.
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
# edit .env and set real values for POSTGRES_PASSWORD and GRAFANA_ADMIN_PASSWORD
# to generate a strong random password for either, run:
#   openssl rand -base64 24
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

Grafana UI: `http://localhost:3001` (log in with `admin` and the `GRAFANA_ADMIN_PASSWORD` from your `.env`). The Prometheus datasource and the "SentinelOps: Phase 1" dashboard are both provisioned automatically on first boot.

**If you change `POSTGRES_PASSWORD` in `.env` after the stack has already run once:** Postgres only applies that value when it initializes an empty data directory, so an existing `postgres_data` volume keeps the *old* password even after `.env` changes — `api` will then fail to authenticate with `password authentication failed`. Fix by recreating the volume (`docker compose down` then `docker volume rm sentinelops_postgres_data` then `docker compose up -d`) rather than editing `.env` alone.

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
