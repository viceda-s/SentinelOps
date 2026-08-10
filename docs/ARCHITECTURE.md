# Architecture

This document describes what SentinelOps's Phase 1.1 implementation actually is: the components that exist, how they communicate, and why the system is split the way it is. It documents the built system, not the proposed one — `docs/DESIGN.md` is the frozen v1.0 design; `docs/implementation-findings.md` records every point where the real implementation diverged from it, and why. Where this document and DESIGN.md disagree, the implementation findings are the source of truth.

## Purpose

SentinelOps is a self-hosted incident-response lab: a monitored estate of services, an observability stack that detects when one of them fails, and a response engine that automatically enriches, tracks, and remediates the resulting incident — without a human in the loop for the common case. Phase 1.1's scope is proving that loop closes correctly for a small, real service estate; later phases add breadth (more fault types, more playbooks) and depth (SLA tracking, reporting) on top of a foundation that already works.

## High-level architecture

```
┌─────────────┐    scrape     ┌────────────┐   alert    ┌──────────────┐
│  Monitored   │◄─────────────│ Prometheus │───────────►│ Alertmanager │
│   estate     │               └────────────┘            └──────┬───────┘
│ (api, nginx, │                                                 │ webhook
│  postgres,   │                                                 ▼
│  node-       │                                        ┌──────────────────┐
│  exporter,   │                                        │  webhook-handler │
│  cadvisor)   │                                        │  (Flask/gunicorn)│
└──────┬───────┘                                        └────────┬─────────┘
       │                                                          │ enrich + persist
       │ restart via                                              ▼
       │ Docker Engine API                              ┌──────────────────┐
       │                                                 │    PostgreSQL    │
┌──────┴───────┐          claim (SKIP LOCKED)            │  (incidents,     │
│    worker    │◄─────────────────────────────────────── │   events,        │
│ (remediation │                                          │   attempts,      │
│   engine)    │─────────────────────────────────────────►│   CMDB-backed)   │
└──────┬───────┘          record attempts + transitions   └──────────────────┘
       │
       │ reads
       ▼
┌──────────────┐
│ cmdb/services │
│    .yaml      │
└──────────────┘
```

Grafana reads from Prometheus for dashboards and isn't in the incident pipeline itself; it's included in the component overview below for completeness.

## Component overview

### Monitored estate

Five application services form the monitored estate. All five have CMDB entries; Prometheus currently scrapes three of them (`api`, `node-exporter`, and `cadvisor`):

- **`api`** (`docker/api/`) — a small Flask app whose `/health` endpoint backs `http`-type recovery verification, and whose `/items` endpoint exercises a real `Client → nginx → api → postgres` round trip against a synthetic `items` table (`docker/postgres/init/001_items.sql`). Exposes `/metrics` via `prometheus-client` for Prometheus to scrape.
- **`nginx`** — reverse proxy in front of `api`. Not scraped (see "Known limitations" below).
- **`postgres`** — the system of record for `api`'s synthetic data and for the entire incident/response data model described below. Not scraped.
- **`node-exporter`** — host-level metrics (CPU, memory, disk), the data source for `HighCPU`/`HighMemory`/`DiskPressure`.
- **`cadvisor`** (`gcr.io/cadvisor/cadvisor:v0.49.1`) — per-container resource metrics. Mounted read-only against the host's cgroup/Docker state; in this environment it can't reach the Docker daemon for container names, so its metrics carry only anonymous cgroup IDs (this is why `ContainerRestartLoop` isn't implemented — see "Known limitations" below).

### Observability stack

- **Prometheus** (`docker/prometheus/`) scrapes `api`, `node-exporter`, and `cadvisor` (`prometheus.yml`'s `scrape_configs` — three `job_name`s, the actual static source of truth for "what's monitored") and evaluates the 6 alert rules in `rules/alerts.yml`: `ServiceDown`, `HighCPU`, `HighMemory`, `DiskPressure`, `HighErrorRate`, `HighLatency`.
- **Alertmanager** groups by `(alertname, job)`, waits `group_wait: 10s` before an initial notification, `group_interval: 30s` before adding new alerts to an existing group's notification, and `repeat_interval: 1h` before resending an unchanged firing alert — routes everything to a single `webhook` receiver pointed at `webhook-handler:8000/alerts`, with `send_resolved: true` so recovery is reported too.
- **Grafana** is provisioned entirely from files (`docker/grafana/`) — one datasource, one 8-panel dashboard (`dashboards/phase1.json`) — no UI-drift risk, since a fresh `bootstrap.sh` run reproduces the exact same dashboard.

### Response engine (`automation/response_engine/`)

Two separate runtime processes, deliberately not one:

- **`webhook_handler.py`** — a Flask app run under gunicorn (`docker/webhook-handler/`), the `/alerts` route Alertmanager posts to. Per-request: parse the payload, open a request-scoped PostgreSQL connection, call `handlers.handle_alert()` once per alert in the payload, commit. `configure_logging()` runs at module scope, not `if __name__ == "__main__":`, since gunicorn imports this module rather than executing it.
- **`handlers.py`** — `handle_alert()`: ignores non-`firing` deliveries (these are `resolved` notifications or duplicate-suppression NOTEs, not errors), resolves the service from the CMDB via the alert's `job` label, resolves the playbook from the CMDB's `playbooks:` map, dedupes on Alertmanager's `fingerprint` against currently-open incidents (open means `NEW`/`ACKNOWLEDGED`/`IN_PROGRESS`/`ESCALATED`), and either creates a new incident or appends a `NOTE` event to an existing open one. An alert for a service not in the CMDB is created and immediately escalated rather than silently dropped.
- **`state_machine.py`** — `transition()`, the single function every status change in the system goes through. Validates the transition against `ALLOWED_TRANSITIONS`, updates `incidents.status` (plus the relevant timestamp column — `acknowledged_at`/`resolved_at`/`closed_at`), and appends an `incident_events` row in the same statement. Callers own the transaction; this function never calls `commit()`/`rollback()`.
- **`worker.py`** — the remediation engine's entry point, a continuous process (`docker/worker/`) polling every 5 seconds. `claim.py`'s `claim_incident()` uses `SELECT ... FOR UPDATE SKIP LOCKED` so multiple worker replicas could pull from the same queue without double-claiming (a Phase 1.1 property proven correct, though Phase 1.1 runs a single replica). Dispatches on `incident["playbook"]` to `remediation.py`'s `restart_service()` or `collect_diagnostics()`. Transaction discipline is explicit: a clean iteration commits; a Docker Engine `APIError` still commits (the playbook's own failure record must survive) before retrying next poll; any other exception rolls back, returning the incident to claimable state.
- **`remediation.py`** — the playbooks themselves. `restart_service()`: restart the container via the Docker Engine API, poll `verify_recovery()` for up to `VERIFY_TIMEOUT = 30s` (interval `1s`), up to `MAX_RESTART_ATTEMPTS = 2` with a `RESTART_COOLDOWN = 5s` between them, `RESOLVED` on success or `ESCALATED` after exhausting attempts. `collect_diagnostics()`: no restart, no retry — snapshot the last 100 log lines and current stats to `./diagnostics/<incident>-attempt-<n>.json`, unconditionally `ESCALATED` so a human always sees it. Both record every attempt in `remediation_attempts` via `record_attempt_start()`/ `record_attempt_finish()`, using `clock_timestamp()` (not `NOW()`) so `started_at`/`finished_at` reflect real elapsed time rather than the transaction-start timestamp every other write in the same transaction shares.
- **`verification.py`** — `verify_recovery()`, one function dispatching on the CMDB's `verification.type` per service: `http` (GET a URL, `200` = healthy, any `RequestException` — including the transient `ConnectionError` of polling a port immediately after restart — treated as a failed check, not a crash), `docker-health` (read the container's existing Docker `HEALTHCHECK` status without triggering a fresh probe — see "Known limitations"), `running` (container status only, for services with neither an HTTP endpoint nor a `HEALTHCHECK`).
- **`playbooks.py`** — `IMPLEMENTED_PLAYBOOKS`, a frozen, dependency-free set (`{"restart_service", "collect_diagnostics"}`) imported by both `remediation.py` and `validate_cmdb.py`. Split into its own module specifically so the validator doesn't need the Docker SDK installed — importing it from `remediation.py` directly pulled in `docker`, and this repo's own top-level `docker/` directory shadows the real package via Python's implicit namespace packages when run from the host.
- **`logging_config.py`** — `JsonFormatter`/`configure_logging()`, called once per process. Every log line is one JSON object: `timestamp`/`level`/`logger`/`message`/`incident_reference`/`exception` always present (defaulting to `null`), plus an automatically-populated `context` object holding any other `extra=` fields a call site attaches.

### Data model (`docker/postgres/init/`, applied in numeric order on first boot)

- **`incidents`** — one row per incident. `status` drives the lifecycle; `fingerprint` plus a partial unique index (`WHERE status IN ('NEW','ACKNOWLEDGED','IN_PROGRESS','ESCALATED')`) enforces deduplication at the database layer, not just in application code. `labels`/`annotations` (JSONB) preserve the original Alertmanager payload verbatim.
- **`incident_events`** — append-only audit trail, one row per state change or note, `(incident_id, sequence)` unique so ordering is never ambiguous.
- **`remediation_attempts`** — one row per playbook execution attempt, `(incident_id, attempt_number)` unique. `started_at`/`finished_at` use `clock_timestamp()`, so they reflect real elapsed time.
- **`incident_reference_counters`** — backs the human-readable `INC-YYYY-NNNN` reference format.
- **`items`** — unrelated to incident response; backs `api`'s `/items` health-check endpoint, present from an earlier phase of the project.

### Configuration-as-code (`cmdb/services.yaml`)

The single source of truth for everything the response engine needs to know
about a service that isn't already implicit in its container: `owner`,
`escalation_contact`, `tier`, `criticality`, `runbook`, `verification`
(strategy + params), `playbooks` (alert name → playbook name map), `sla`,
and optionally `dependencies`. Five entries — `api`, `nginx`, `postgres`,
`node-exporter`, `cadvisor` — deliberately a superset of what Prometheus
actually scrapes: the CMDB is allowed to be ahead of current monitoring
coverage, though the reverse isn't required.

### Operational scripts (`automation/scripts/`)

- **`bootstrap.sh`** — idempotent stack startup. `.env` auto-creation with placeholder-credential warnings, port-conflict detection with actionable `lsof` output, `--validate-only` running the full config-validation chain (`validate_cmdb.py`, `docker compose config`, `promtool check rules`, `amtool check-config`) without starting anything, then (unless `--validate-only`) starting the stack and polling for every service to report healthy.
- **`teardown.sh`** — `docker compose down --remove-orphans`; `--purge` additionally removes the named volume after an interactive confirmation.
- **`chaos.sh`** — `stop <service>`: validate the service exists in the Compose project, then `docker compose stop` it (not plain `docker stop`, to stay scoped to this project and to the same service names the CMDB uses). `case "$COMMAND"` structure so Phase 1.2 fault types (`kill`, `pause`, `network`) extend without restructuring.
- **`validate_cmdb.py`** — checks the CMDB is well-formed, every referenced playbook is in `IMPLEMENTED_PLAYBOOKS`, every referenced verification type is one of the three implemented, and every Prometheus scrape job has a CMDB entry. The check is one-directional: it doesn't require every CMDB entry to have a scrape job.

## Incident lifecycle

```
NEW ──► ACKNOWLEDGED ──► IN_PROGRESS ──┬──► RESOLVED ──► CLOSED
 │                                     │
 │  (unrecognized service)             │
 └──────────────► ESCALATED ◄─────────┘
                     │
                     └──► IN_PROGRESS (re-attempt) or RESOLVED
```

The `NEW → ESCALATED` path exists specifically for alerts against services the CMDB doesn't recognize — enrichment can fail before any worker exists to claim the incident, so `ACKNOWLEDGED` (which specifically means "claimed by a worker") can't be a synthetic step on that path.

A concrete walk, `restart_service` case:

1. Alertmanager posts a `firing` webhook. `handle_alert()` finds no open incident with this fingerprint, creates one at `NEW`, resolves the playbook and enrichment from the CMDB.
2. `worker.py`'s poll loop claims it: `claim_incident()`'s `SELECT ... FOR UPDATE SKIP LOCKED` moves it to `ACKNOWLEDGED` atomically.
3. `restart_service()` transitions to `IN_PROGRESS`, restarts the container, polls `verify_recovery()`.
4. On success: `RESOLVED`. On exhausting `MAX_RESTART_ATTEMPTS`: `ESCALATED`.
5. A human (or, later, an automated report) eventually moves a `RESOLVED` incident to `CLOSED` — the one state transition Phase 1.1 doesn't drive automatically, since it represents documentation/RCA having been done, not a system condition.

Any further `firing` webhook with the same fingerprint while the incident remains open (`NEW`/`ACKNOWLEDGED`/`IN_PROGRESS`/`ESCALATED`) appends a `NOTE` event instead of creating a second incident — including, correctly, a NOTE on an `ESCALATED` incident, since escalation still leaves it open for a human or a later retry.

## Repository layout

```
automation/
  response_engine/    Response engine: webhook handler + worker + shared logic
  scripts/             bootstrap.sh, teardown.sh, chaos.sh, validate_cmdb.py
cmdb/
  services.yaml         Configuration-as-code for the monitored estate
docker/
  api/                  Sample monitored application
  alertmanager/         Alertmanager config
  grafana/               Provisioned datasource + dashboard
  nginx/                 Reverse proxy config
  postgres/init/          Schema migrations, applied in order on first boot
  prometheus/             Scrape config + alert rules
  webhook-handler/        Dockerfile for the webhook_handler.py process
  worker/                 Dockerfile for the worker.py process
docs/
  DESIGN.md                Frozen v1.0 design
  implementation-findings.md  Every real discrepancy found building it
  runbooks/                 Operational runbooks, organized by response not alert
  ARCHITECTURE.md          This document
diagnostics/              collect_diagnostics() output, host-mounted
```

## Operational characteristics

- **Statelessness where it matters**: `webhook_handler.py` holds no in-process state between requests — every request opens its own connection and commits before returning. `worker.py` holds no state between poll iterations beyond what's in the database. Either process can restart without losing anything beyond in-flight work, which the database already tracks as an attempt in progress.
- **The database is the coordination point**, not application memory: dedup is a unique index, not an in-memory set; claiming work is a row lock, not a queue library. This is what makes multiple worker replicas safe without any additional coordination infrastructure.
- **Transaction ownership is explicit and asymmetric by design**: every function that writes state documents whether it commits/rolls back or expects its caller to. Getting this wrong was the exact mechanism behind a real production-severity bug this session (an uncaught `ConnectionError` in `verify_recovery()`'s `http` branch triggering a rollback that reverted the database claim but couldn't undo an already-executed `container.restart()`, producing a genuine restart loop) — fixed, and the discipline it forced is now load-bearing throughout the engine.
- **The Docker socket mount gives the `worker` container administrative control over every container on the host**, not just SentinelOps's own — confirmed directly (`docker.from_env()`/`client.containers.list()` sees everything), and an accepted, documented tradeoff for a lab environment, not something Phase 1.1 attempts to sandbox.

## Known limitations

Full detail and reasoning for each of these lives in
`docs/implementation-findings.md`; this is a pointer list, not a
restatement.

- **`ContainerRestartLoop` is unwritten.** `cadvisor` can't reach the Docker daemon in this environment, so its metrics carry anonymous cgroup IDs with no container name to key an alert on.
- **`HighErrorRate` undercounts.** Only errors caught inside route handlers increment the metric; an unhandled exception that gunicorn turns into a bare 500 isn't counted, since request accounting happens inline per route rather than in Flask middleware.
- **`docker-health` verification can race a slow `HEALTHCHECK` interval** (finding 7). `cadvisor`'s upstream image probes every 30 seconds, the same as `restart_service`'s own verification timeout; a 30-second verification window can span an entire gap between probes and see stale status even after genuine recovery. A fix was built and verified working, then deliberately left unshipped — there's no `docker/cadvisor/` build context in this repo to attach a `HEALTHCHECK` override to without introducing a new file for what would be a single line.
- **One `runbook:` per CMDB service, not per alert** (finding 3). `api` fires both `ServiceDown` and several `collect_diagnostics`-mapped alerts, but its CMDB entry can only point at one runbook.
- **`nginx` and `postgres` are unmonitored by Prometheus**, so `ServiceDown` structurally cannot fire for either — they're CMDB entries without a corresponding scrape job (finding 5), which is deliberate CMDB-ahead-of- monitoring design, not an oversight, but does mean these two services' failure-independence properties were never exercised through the real alert pipeline.
