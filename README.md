# SentinelOps

An enterprise-inspired monitoring and incident response lab: Prometheus, Grafana, Docker, Python, and PostgreSQL, wired together to practise the full incident lifecycle — detect, triage, enrich, remediate, verify, document, audit — not just the monitoring part of it.

**Status: Phase 1 in progress.** The monitored estate, observability stack, and webhook ingestion pipeline (Alertmanager → webhook handler → Postgres) are done and running as real containers. Both Phase 1 playbooks (`restart_service`, `collect_diagnostics`) are built and verified against real infrastructure; the worker still has no polling loop tying `claim_incident()` to either of them, so nothing runs autonomously yet. See [Current status](#current-status) for the full breakdown. Design reasoning lives in [`docs/DESIGN.md`](docs/DESIGN.md); real gaps found between that design and reality while building are tracked in [`docs/implementation-findings.md`](docs/implementation-findings.md).

## Overview

Most monitoring labs stop at "the alert fired." SentinelOps is built to show what happens after that: how an alert becomes an incident, who owns it, what gets fixed automatically, what has to go to a human, and what record is left behind. Prometheus and Grafana are components here, not the subject — the subject is incident management.

The full design rationale, including what was deliberately left out and why, is in [`docs/DESIGN.md`](docs/DESIGN.md).

## Architecture

Three groups of services:

- **Monitored estate** — `nginx`, `api`, `postgres`, `node-exporter`, `cAdvisor`. The thing being watched.
- **Observability** — Prometheus, Alertmanager, Grafana. Detection and routing.
- **Response engine** *(partially built)* — webhook handler, remediation worker, report generator, backed by Postgres. Turns alerts into incidents, tries to fix them, and records what happened. The webhook handler (data model, state machine, CMDB, and both its core logic and its HTTP layer) is built and running as its own container; the remediation worker can claim incidents off the queue and both Phase 1 playbooks (`restart_service`, `collect_diagnostics`) are fully built and verified, but nothing yet calls them automatically — there's no polling loop wiring the queue to a playbook; the report generator isn't built yet.

See `docs/DESIGN.md`'s architecture diagram and "How a fault becomes a resolved incident" section for the full flow and the reasoning behind splitting the webhook handler from the remediation worker.

## Current status

**Built and verified:**

- The monitored estate (`nginx`, `api`, `postgres`, `node-exporter`, `cAdvisor`) is up, wired, and tested end-to-end, including a real `api` → Postgres dependency in its health check.
- Prometheus is scraping the estate; Alertmanager is running and confirmed reachable from it.
- 6 of 9 alert rules are written and loaded: `ServiceDown`, `HighCPU`, `HighMemory`, `DiskPressure`, `HighErrorRate`, `HighLatency`.
- Grafana is fully provisioned from files (datasource + an 8-panel dashboard), no UI drift.
- The webhook ingestion pipeline is built and running as a real container (`webhook-handler`, `docker/webhook-handler/`), verified end-to-end through Docker Compose: Alertmanager posts to it over the compose network, it enriches and dedupes against the CMDB and the data model, and persists a correctly-populated incident in Postgres. Underneath it: the data model (`incidents`, `incident_events`, `remediation_attempts`, with dedupe and history-integrity constraints enforced by the database itself), the state machine (`transition()`, one function every status change goes through), the CMDB (`cmdb/services.yaml`, all 5 services), and `handle_alert()`'s core logic (enrich, resolve the playbook, dedupe, create the incident, escalate unknown services). Design details and reasoning for each are in `docs/implementation-findings.md` and the code itself.
- The remediation worker's queue claim (`automation/response_engine/worker.py`, `claim_incident()`) is written and verified under real concurrency: `SELECT ... FOR UPDATE SKIP LOCKED` lets multiple workers pull from the same `incidents` queue without ever double-claiming or blocking on each other, confirmed with overlapping transactions and a held row lock, not just sequential calls. Claiming an incident atomically moves it `NEW → ACKNOWLEDGED` via `transition()`, so callers only ever see incidents they genuinely own.
- Both Phase 1 runbooks are written (`docs/runbooks/service-down.md`, `docs/runbooks/collect-diagnostics.md`), organized by operational response rather than one-per-alert-type since `collect_diagnostics` covers four alerts with an identical automated response — a deliberate, documented deviation from DESIGN.md's wording (`docs/implementation-findings.md`, finding 3). `automation/scripts/validate_cmdb.py` now passes cleanly for the first time this session.
- Every service in `cmdb/services.yaml` now declares a `verification` strategy (`http` with a URL, `docker-health`, or `running`), so the worker can check whether a restarted service actually recovered without hardcoding service-specific logic — the estate turned out to have no single mechanism that works for all five services (only `api` has an HTTP health endpoint; `postgres` and `cadvisor` have Docker `HEALTHCHECK`s; `nginx` and `node-exporter` have neither). Documented as a real gap in DESIGN.md's "check `/health`" wording (`docs/implementation-findings.md`, finding 4). The new schema field and its validation in `validate_cmdb.py` were confirmed against three deliberately broken CMDB files (missing block, invalid type, missing URL) before being trusted.
- The remediation worker now runs as its own container (`worker`, `docker/worker/`), with the Docker socket mounted so playbooks can control other containers via the Docker Engine API — unlike cAdvisor's socket mount earlier in this project, this one was tested directly (not assumed) and confirmed working: `docker.from_env()` and `client.containers.list()` succeed from inside the built container. That test also concretely confirmed DESIGN.md's own security note — the socket gives this container visibility into and control over *every* container on the host, not just SentinelOps's own, which is exactly the "administrative control over the host" tradeoff the design document already calls out as lab-only.
- The `restart_service` playbook (`automation/response_engine/remediation.py`) is fully built and verified against a real container, not just tested in isolation: it restarts the target via the Docker Engine API, polls recovery using whichever verification strategy the CMDB declares, records every attempt in `remediation_attempts`, and drives the incident through `IN_PROGRESS → RESOLVED` on success or `→ ESCALATED` after 2 failed attempts. Proven two ways — stopping and restarting real `nginx` end-to-end (confirmed via the container's actual restart timestamp, not just its reported status) and a missing-container run that correctly escalated after exactly one attempt, no wasted retry. `verify_recovery()` (`verification.py`) — the `http`/`docker-health`/`running` dispatch — was independently tested against all three real services beforehand. Finding this work also caught a real bug in `state_machine.py`: `IN_PROGRESS` was missing `ESCALATED` from its allowed transitions, contradicting DESIGN.md's own original table — a plain transcription error, fixed directly, not logged as a new design deviation.
- The `collect_diagnostics` playbook (also `remediation.py`) is fully built and verified: unlike `restart_service`, it never restarts anything or retries — it snapshots the last 100 log lines and current container stats from the Docker Engine API, writes them to one JSON file per attempt under a mounted `./diagnostics/` host directory (`diagnostics_path` on the `remediation_attempts` row), and unconditionally drives the incident to `ESCALATED` so a human always sees it. Verified against a real `api` container, including confirming the JSON artifact actually lands on the *host* filesystem, not just inside the container — proving the volume mount, not just the code, is correct. All three failure paths were tested too: a missing container escalates with no file written; a simulated disk-full `OSError` while writing still escalates with the audit trail intact; a simulated Docker Engine `APIError` re-raises and leaves the incident `IN_PROGRESS` rather than pretending it resolved anything. That last test also surfaced a constraint worth flagging for the dispatch loop: `record_attempt_finish()`'s "record then re-raise" pattern only holds if the caller commits before letting the exception propagate — a bare `with conn:` around the call would silently roll back the failure record along with everything else.

**Known gap:**

- `HighErrorRate`'s ratio only reflects errors caught inside route handlers (`OperationalError`); an unhandled exception that gunicorn turns into a 500 doesn't currently increment either the error or request counter, since request accounting happens inline in each route rather than in Flask middleware. Fixing this means moving metric recording to `after_request`/`teardown_request` so every request is counted regardless of how it ends — not yet done.

**Not yet built:**

- The remaining 3 alert rules: `ContainerRestartLoop`, `ResponseEngineDown`, `RemediationFailureRateHigh`. The latter two need a response engine that doesn't fully exist yet. `ContainerRestartLoop` is blocked on an environment limitation: cAdvisor here can't reach the Docker daemon, so every cAdvisor metric carries only an anonymous cgroup `id`, with no container name to key an alert on — writing the rule against raw cgroup ids would be both unreadable and unmappable to the `service` labels the rest of the design relies on. Left unwritten on purpose; options for later: mount a working Docker socket, add a small purpose-built exporter, or revisit if the project ever moves to Kubernetes.
- `worker.py`'s actual polling loop/dispatch that ties `claim_incident()` to a playbook — both `restart_service` and `collect_diagnostics` only run when called directly right now; there's no process wiring the queue to either yet. The report generator.
- `bootstrap.sh`, `teardown.sh`, `chaos.sh`, ARCHITECTURE.md, ADRs.

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
│   ├── DESIGN.md
│   ├── implementation-findings.md
│   └── runbooks/         service-down.md, collect-diagnostics.md
├── docker-compose.yml
├── .env.example
├── docker/
│   ├── api/              Flask app, Dockerfile, requirements
│   ├── webhook-handler/  Dockerfile, requirements (code lives in automation/)
│   ├── worker/           Dockerfile, requirements (code lives in automation/)
│   ├── nginx/            reverse proxy config
│   ├── postgres/init/    schema + seed data, runs on first boot
│   ├── prometheus/       scrape config, alert rules
│   ├── alertmanager/     routing config
│   └── grafana/          provisioning, dashboards
├── automation/
│   ├── response_engine/  state_machine.py, handlers.py, webhook_handler.py, worker.py
│   └── scripts/          validate_cmdb.py
├── cmdb/
│   └── services.yaml
└── requirements-dev.txt
```

The full target layout — `docs/adr/`, `reports/`, `tests/` — is in `docs/DESIGN.md`'s repository layout section. Those directories don't exist yet; they'll appear as the corresponding pieces get built. (`docs/runbooks/` already exists — see [Runbooks](#runbooks).)

## Incident Lifecycle

Not demonstrable yet — this section will describe the detect → triage → enrich → remediate → verify → document → audit flow once the response engine exists. Until then, see `docs/DESIGN.md`'s "How a fault becomes a resolved incident" section for the intended behavior.

## Runbooks

Two runbooks, following `docs/DESIGN.md`'s format (symptom, detection, automated response, manual verification, escalation):

- [`docs/runbooks/service-down.md`](docs/runbooks/service-down.md) — `ServiceDown` → `restart_service`.
- [`docs/runbooks/collect-diagnostics.md`](docs/runbooks/collect-diagnostics.md) — `HighCPU`, `HighMemory`, `HighErrorRate`, `HighLatency` → `collect_diagnostics`. One runbook rather than four, since all four alerts share the same automated response; see `docs/implementation-findings.md` for why this reads "one per alert type" as "one per operational response."

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
