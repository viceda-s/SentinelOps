# Implementation findings

Real discrepancies between `docs/DESIGN.md` v1.0 and what building it actually
required, found during Phase 1.1. Not a changelog and not a wishlist — only
things where the design's own words contradict each other or contradict
observed reality.

The findings below were reconciled into `docs/DESIGN.md` v1.1 on 2026-08-05
— see `CHANGELOG.md` for a summary of what changed. They are retained here as
an engineering history of how the design evolved: `docs/DESIGN.md`, the ADRs,
and `CHANGELOG.md` are now the canonical documentation, and none of this is
required reading to understand the system as currently designed.

## 1. Alertmanager identifies services by `job`, not `service`

DESIGN.md says the handler "looks the service up in the CMDB" without saying
where the service identifier comes from. A real captured webhook payload
(2026-08-03, triggered by stopping `api` and pointing Alertmanager at a
throwaway echo container) shows the alert's `labels` are `alertname`,
`instance`, `job`, `playbook`, `severity` — there is no `service` label.

`job` is what identifies the service in practice, and it already matches the
CMDB's own keys (`api`, `postgres`, `nginx`, `node-exporter`, `cadvisor`) by
construction. The fix is at the integration boundary: the handler reads
`labels["job"]`, looks that up in the CMDB, and stores the result in
`incidents.service` — the column name and domain concept don't change, only
where the value comes from.

Proposed DESIGN.md wording: "The handler uses the Prometheus `job` label as
the service identifier, looks that service up in the CMDB, enriches the
incident with ownership, SLA and operational metadata, and resolves the
playbook from the CMDB."

## 2. `NEW -> ESCALATED` is a required transition

DESIGN.md states two things that can't both be true as written:

- an unknown service (not in the CMDB) "goes straight to `ESCALATED`"
- the allowed-transitions table only permits `NEW -> ACKNOWLEDGED |
  SUPPRESSED_MAINTENANCE`

`ACKNOWLEDGED` specifically means "claimed by a worker" — the handler
manufacturing a fake `ACKNOWLEDGED` event to satisfy the table before
escalating an unknown service would make the audit trail describe something
that didn't happen. The correction is to the transition table, not the
handler: `NEW -> ESCALATED` needs to be a valid transition, since escalation
can legitimately happen during enrichment, before any worker exists to claim
the incident.

Applied in code now (`automation/response_engine/state_machine.py`), with a
comment pointing back to this file, since the alternative — leaving the
design's contradiction in place and papering over it in the handler — would
have been worse than deviating from a frozen document.

## 3. Runbooks are one per operational response, and the CMDB can't express that

DESIGN.md says runbooks are written "one per alert type." Phase 1.1's two
playbooks don't map cleanly onto that: `restart_service` serves `ServiceDown`
alone, but `collect_diagnostics` serves four different alerts (`HighCPU`,
`HighMemory`, `HighErrorRate`, `HighLatency`) with an identical automated
response. Writing four near-duplicate runbooks that would need to stay in
sync forever adds no value over one runbook organized around the response
instead of the rule that triggered it — so `docs/runbooks/` has
`service-down.md` and `collect-diagnostics.md`, not one file per alert.

That surfaced a second, separate problem: `cmdb/services.yaml`'s schema has
one `runbook:` field per *service*, not per alert or per playbook. `api` can
fire both `ServiceDown` and `HighCPU`/`HighErrorRate`/etc., but its CMDB entry
can only point at one runbook path. Every service's `runbook:` currently
points at `service-down.md`, which is only correct for the `ServiceDown` case
— there's no way today for the CMDB to tell an operator "for this alert, see
this runbook" when a service has more than one alert type mapped to it.

Not fixed now — this needs either a `runbook:` per playbook (mirroring how
`playbooks:` already maps alert name to playbook name) or a lookup that
combines the fired alert's playbook with a playbook-to-runbook table
elsewhere. Left as a known gap rather than a quick patch, since the CMDB
schema change affects `validate_cmdb.py` and every existing entry.

## 4. Recovery verification is service-specific operational metadata

DESIGN.md describes the `restart_service` playbook as "check container exists,
restart, wait, check `/health`, max 2 attempts with a cooldown." Building the
worker against the real monitored estate showed that no single verification
mechanism exists across all services:

- `api` exposes an HTTP `/health` endpoint but has no Docker `HEALTHCHECK`.
- `postgres` and `cadvisor` expose Docker `HEALTHCHECK`s.
- `nginx` and `node-exporter` expose neither, leaving only the container's
  running state as a generic signal.

Treating "check `/health`" literally would require the worker to grow
service-specific knowledge ("if service == api ..."), which contradicts the
CMDB's purpose of keeping operational metadata out of the response engine.
Falling back to "container is running" for every service would also weaken
verification for `api`, where an application-level health endpoint already
exists and can distinguish a healthy service from a merely running process.

The solution is to make recovery verification explicit CMDB metadata, alongside
ownership, criticality and playbook mappings. Each service declares one
verification strategy:

- `http` with a URL (for `api`)
- `docker-health` (for `postgres` and `cadvisor`)
- `running` (for `nginx` and `node-exporter`)

The worker dispatches verification based on that metadata rather than the
service name, keeping the playbook generic while accurately reflecting the
capabilities of each monitored service.

This requires a CMDB schema extension (`verification:`), corresponding
validation in `validate_cmdb.py`, and updates to every existing service entry.
Applied in Phase 1.1 because the design's single "`/health`" step could not
describe the real monitored estate without either hardcoded exceptions or
incorrect recovery verification.

## 5. Alert coverage is defined by Prometheus scrape jobs, not alert rules

DESIGN.md says `bootstrap.sh` validates that "an alert rule's service label has
a CMDB entry." The implemented Prometheus configuration doesn't contain a
static service label in its alert rules. Each rule uses the runtime
`$labels.job` value attached to the firing time series, so the service identity
only exists once Prometheus evaluates the rule.

The static source of truth for monitored services is
`docker/prometheus/prometheus.yml`, where each `scrape_config` defines a
`job_name`. These job names (`api`, `node-exporter`, `cadvisor`, etc.) are the
same identifiers the webhook handler later receives as `labels["job"]` and uses
to look up the service in the CMDB.

The validation therefore moved from "every alert rule has a CMDB entry" to
"every configured Prometheus scrape job has a CMDB entry." This preserves the
operational intent of the original design while matching how Prometheus
actually models monitored services.

Proposed DESIGN.md wording: "bootstrap.sh validates that every configured
Prometheus scrape job has a corresponding CMDB entry before starting the
stack."

## 6. "Open incident" is undefined, and the code guessed wrong

DESIGN.md says the handler dedupes on the Alertmanager `fingerprint`: "If
there's already an open incident with that fingerprint, it appends an event
rather than creating a new incident." It also says the fingerprint uniqueness
is enforced by the database: "a partial unique index on `fingerprint` where
the status isn't terminal." Neither sentence defines which states count as
"open," and the state table's terminal/non-terminal labeling (only `CLOSED`
and `SUPPRESSED_MAINTENANCE` are marked terminal) doesn't settle it either —
non-terminal and open are different claims. `RESOLVED` can still transition to
`CLOSED`, which makes it non-terminal, but that says nothing about whether a
*fresh* alert with the same fingerprint should reuse a `RESOLVED` incident or
start a new one.

Both existing enforcement points resolved the ambiguity the same way, by
accident rather than decision: `002_incidents.sql`'s partial unique index
(`WHERE status NOT IN ('CLOSED', 'SUPPRESSED_MAINTENANCE')`) and
`handle_alert()`'s dedupe query used identical scoping, both treating
`RESOLVED` as still-open. Live testing (2026-08-04, `chaos.sh stop api` run
twice against the same service, once before and once after the first
incident reached `RESOLVED`) confirmed the consequence: the second
`ServiceDown` firing — a genuine new alert, confirmed via Alertmanager's own
`/api/v2/alerts`, same fingerprint by construction since none of the alert's
labels changed — produced no new incident. It silently appended a `NOTE`
event to the original `RESOLVED` incident instead.

Decided: an incident is open for deduplication purposes only while its status
is `NEW`, `ACKNOWLEDGED`, `IN_PROGRESS`, or `ESCALATED`. `RESOLVED` ends the
dedup window, the same as `CLOSED` and `SUPPRESSED_MAINTENANCE` already did.
Reasoning: the worker's unit of work is one incident — claim, run a playbook,
verify, resolve — and that lifecycle is complete once `RESOLVED` is reached.
A later alert with the same fingerprint is a new remediation, not a
continuation of the old one, and Phase 1.2's MTTR/remediation-success-rate
metrics only have an unambiguous meaning if one outage maps to one incident.
`CLOSED` remains a separate, deliberately administrative state (RCA written,
report generated) — whether an operator has gotten around to documentation
shouldn't determine whether a fresh outage gets its own incident. Flapping
(the same fault re-firing within seconds) is a real but separate concern,
better solved later with Alertmanager's own `for:`/grouping/inhibition or a
purpose-built correlation window — not by conflating "still open" with "the
same operational event."

Applied and verified (2026-08-04): both enforcement points were updated
together — `002_incidents.sql`'s partial unique index now reads `WHERE status
IN ('NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'ESCALATED')`, and `handlers.py`'s
dedupe query matches exactly. Confirmed by repeating the original test —
`chaos.sh stop api` run twice against the same service, letting the first
incident fully reach `RESOLVED` in between — after `teardown.sh --purge` +
`bootstrap.sh` applied the corrected schema to a fresh volume. The second run
produced `INC-2026-0002`, a genuinely distinct incident with its own complete
`CREATED → ACKNOWLEDGED → IN_PROGRESS → RESOLVED` event trail, same
fingerprint as `INC-2026-0001` by construction, no cross-contamination
between the two histories.

Proposed DESIGN.md wording: "An incident is open — eligible for
fingerprint-based deduplication — while its status is `NEW`, `ACKNOWLEDGED`,
`IN_PROGRESS`, or `ESCALATED`. Once an incident reaches `RESOLVED`, `CLOSED`,
or `SUPPRESSED_MAINTENANCE`, a subsequent alert with the same fingerprint
creates a new incident rather than appending to the old one."

## 7. `docker-health` verification can race a slow `HEALTHCHECK` interval, and the audit trail hid it

`chaos.sh stop cadvisor` (2026-08-04) escalated `INC-2026-0003` after exactly 2
`restart_service` attempts, both recorded with `started_at` identical to
`finished_at` down to the microsecond and `error: "Verification timed out
after 30 seconds"`. Read literally, that looked like `verify_recovery()`
never actually polled — as if the whole 30-second budget were consumed
before the loop body ran even once, which would point at `container.restart()`
itself blocking for the full duration.

Live instrumentation (temporary `logger.info()` calls around
`container.restart()` and each iteration of the verification poll loop,
removed once the investigation concluded) disproved that directly: a repeat
test (`INC-2026-0004`) showed `container.restart()` returning in well under
half a second, the verification deadline starting with the full `30.000s`
intact, and the poll loop executing normally — once per second, counting down
correctly — for the entire budget on both attempts. The worker was doing
real, correct work the whole time; the database just wasn't showing it.

The identical `started_at`/`finished_at` timestamps turned out to be a
PostgreSQL behavior, not a code bug: `NOW()` (and `CURRENT_TIMESTAMP`) is
fixed at transaction start and returns the same value on every call for the
rest of that transaction — confirmed directly (`SELECT NOW(), NOW(), NOW();`
inside one statement returns three identical values). `record_attempt_start()`
and `record_attempt_finish()` both wrote `NOW()`, and both calls, along with
every state transition in between, ran inside the single long-lived
transaction `restart_service()` operates under (`worker.py` only commits
after `dispatch()` returns). Every timestamp in `remediation_attempts` was
therefore frozen at the moment the transaction began, regardless of how much
real time the playbook actually spent — a genuine defect in the audit trail's
accuracy, independent of whether the underlying remediation logic was correct.

With the timestamps no longer misleading, the real cause of the original
escalation became visible: `cadvisor`'s Docker `HEALTHCHECK` — baked into the
upstream `gcr.io/cadvisor/cadvisor:v0.49.1` image itself, not written by this
project — probes only every 30 seconds. `verify_recovery()`'s `docker-health`
branch reads whatever status Docker last recorded; it doesn't trigger a fresh
probe. A 30-second `VERIFY_TIMEOUT` window checked against a service with a
30-second (or longer) probe interval can easily span a gap between two
scheduled checks and see nothing but a stale `starting`/`unhealthy` status the
entire time, even though the container itself recovered normally. `postgres`,
the CMDB's other `docker-health` service, never hit this because its own
`HEALTHCHECK` (defined in `docker-compose.yml`, not an upstream image) already
runs every 5 seconds.

Fixed: `remediation_attempts.started_at`/`finished_at` now write PostgreSQL's
`clock_timestamp()` instead of `NOW()` — the function PostgreSQL itself
documents for measuring real elapsed time within a transaction, since it
advances on every call rather than freezing at transaction start. State
transition timestamps (`incidents.acknowledged_at`/`resolved_at`, every
`incident_events.occurred_at`) were deliberately left on `NOW()`, since those
correctly represent *when this transaction recorded the change*, not a
duration.

Not fixed: the `HEALTHCHECK`-interval race itself. `cadvisor`'s upstream
image bakes in `interval: 30s`, and there's no `docker/cadvisor/` build
context in this repo to attach a shorter interval to without introducing a
new Dockerfile for a single-line change — a real tradeoff, not an oversight.
A Compose-level `healthcheck:` override was built and verified working
(interval dropped to `5s`, probes confirmed 6x more frequent via
`docker inspect`), then deliberately reverted in favor of documenting the gap
rather than adding a config-only override with no corresponding source file
to explain it. `postgres`'s own `HEALTHCHECK`, by contrast, is legitimately
defined in `docker-compose.yml` already (not an override of anything), so it
carries no equivalent burden.

Verified end-to-end (2026-08-04, with the interval override in place): a
clean `chaos.sh stop cadvisor` run (`INC-2026-0005`, after
`INC-2026-0003`/`INC-2026-0004` were manually resolved via `transition()` to
clear the dedup window) resolved on the first attempt in `10.334077` real
seconds — a genuinely distinct, correct `started_at`/`finished_at` pair —
with a clean `CREATED → ACKNOWLEDGED → IN_PROGRESS → RESOLVED` trail and no
escalation. The `clock_timestamp()` fix is confirmed correct independent of
whether the interval override ships; the interval race remains a live,
reproducible risk against the current 30-second upstream default.

This investigation also incidentally re-confirmed finding 6's dedup behavior
under live conditions: three further `ServiceDown` firings for the same
fingerprint while `INC-2026-0003` sat `ESCALATED` (itself an open state)
each correctly appended a `NOTE` event ("Duplicate Alertmanager notification
received") rather than creating a new incident or silently failing — the
apparent "missing" webhook deliveries chased earlier in the investigation
were this same correct, working behavior, not a delivery or logging bug.

Proposed DESIGN.md wording: "For services verified via `docker-health`, the
service's own Docker `HEALTHCHECK` interval must be short relative to
`restart_service`'s verification timeout, or recovery can go undetected
until the next scheduled probe. `remediation_attempts` timestamps record
real elapsed wall-clock time, not transaction-start time."

**Update (issue #59):** the interval race above reproduced in production
against unmodified `main` and was fixed — `_verify_timeout_for()` now derives
the verification deadline from the target container's own
`Config.Healthcheck` (interval + timeout + a fixed margin) for `docker-health`
verification, capped at `HEALTHCHECK_VERIFY_MAX = 60s`, instead of using the
bare `VERIFY_TIMEOUT = 30s` for every verification type. The DESIGN.md
constraint proposed above ("the healthcheck interval must be short relative
to the verification timeout") is now the reverse of the fix's approach — the
timeout is sized to the interval, not the other way around — and should be
updated accordingly if adopted. The `HEALTHCHECK_VERIFY_MAX` cap means the
race is only closed for containers whose `interval + timeout` stays under
~55s; a longer upstream interval (or a `start_period`, which the derivation
does not read) can still reproduce this finding. Issue #43
(`RemediationSettings` / per-service CMDB verification timing) is the planned
general fix.

## 8. The JSON logging schema evolved away from DESIGN.md's fixed `event`/`component` vocabulary

DESIGN.md specifies that every log line carries `component` and `event`
fields, with `event` drawn from a fixed vocabulary (`alert_received`,
`incident_created`, `state_transition`, `remediation_attempt`,
`verification`, `suppressed_maintenance`, `config_invalid`). Building
`JsonFormatter` (`automation/response_engine/logging_config.py`) against real
log call sites across `webhook_handler.py` and `worker.py` showed that
`component` duplicates information Python's own `logger` name already
carries (`sentinelops.webhook_handler`, `sentinelops.worker`, etc.), and that
forcing every log statement into one of seven `event` values either lost
detail an unstructured `context` object already conveys more naturally, or
required inventing sub-categories the fixed vocabulary didn't anticipate
(as finding 7's temporary debug logging would have needed to).

The implemented schema is `timestamp`, `level`, `logger`, `message`,
`incident_reference` (when applicable), `exception` (on error), and an
optional free-form `context` object — structurally simpler than DESIGN.md's
proposal, and it still satisfies Phase 1.1's actual requirement (every log
line from an incident is valid JSON, filterable by `incident_reference`).
Not caught at the time as a documented deviation, unlike findings 1-7 — the
schema simply evolved during implementation without a corresponding
DESIGN.md update. Recorded here now rather than treated as a defect to fix,
since reintroducing a fixed `event` vocabulary would provide no capability
the current schema lacks.

Proposed DESIGN.md wording: "Every log line is JSON with `timestamp`,
`level`, `logger`, and `message`. Log calls associated with a specific
incident add `incident_reference`. Exceptions add a formatted `exception`
field. Additional structured detail, where useful, goes in a free-form
`context` object rather than a fixed `event` vocabulary."

## 9. `incident_events` records lifecycle transitions, not remediation execution detail

DESIGN.md's `event_type` list for `incident_events` includes `PLAYBOOK_STEP`
and `VERIFICATION` alongside `CREATED`, `STATE_CHANGE`, and `NOTE`, and its
worked timeline example shows per-attempt lines ("Restart attempt 1 of 2",
"Health check passed") coming from that table. In practice, only `CREATED`
(`handlers.py`), `NOTE` (`handlers.py`, for deduplicated alerts), and
`STATE_CHANGE` (`state_machine.py`) are ever written — restart attempts and
verification results are recorded exclusively in `remediation_attempts`,
which already has the right shape for that data (`started_at`,
`finished_at`, `result`, `error`, an attempt counter) and would duplicate it
awkwardly as free-text `incident_events` rows.

The two tables ended up with a cleaner split than DESIGN.md described:
`incident_events` is the incident's lifecycle audit trail (what state did it
enter, when, why), and `remediation_attempts` is the playbook execution
history (what did the worker try, how long did it take, did it succeed).
Reconstructing the full picture DESIGN.md's timeline example shows requires
joining both tables on `incident_id`, not reading `incident_events` alone —
not fixed now, since collapsing the two into one table would either lose
`remediation_attempts`' typed columns or force `incident_events` to grow
playbook-specific structure it doesn't otherwise need.

Proposed DESIGN.md wording: "`incident_events` records the incident's
lifecycle: creation, state transitions, and operator/system notes.
Remediation execution detail — individual restart attempts, their timing,
and their verification outcome — is recorded separately in
`remediation_attempts` and joined by `incident_id` when reconstructing a
full incident timeline."

## 10. CMDB lookups must tolerate configuration drift

The response engine originally assumed the CMDB would remain unchanged for the lifetime of an incident. This created a failure mode where removing or renaming a service entry while an incident was still open could strand the incident indefinitely. The worker now treats missing CMDB entries as a terminal condition and escalates the incident instead of retrying forever.

## Phase 1.2 Findings (2026-08-09)

Discrepancies and architectural clarifications discovered during Phase 1.2 implementation, reconciled alongside Phase 1.2 runbooks and ADRs.

### 11. Maintenance window suppression relies on Alertmanager silences and partial unique index deduplication

Phase 1.2 required suppressing alert notifications during maintenance windows without ignoring alerts entirely. The implemented system handles maintenance windows by fetching active silences directly from Alertmanager (`/api/v2/alerts?silenced=true&active=true`) via a dedicated `maintenance-monitor` worker process.

Suppressed alerts create incident records in the `SUPPRESSED_MAINTENANCE` state rather than being discarded. If an active alert collides with an open actionable incident (created before maintenance began), the incident state is left unchanged while a `NOTE` event is appended. To prevent repeated polling from flooding the incident timeline with duplicate notes, a partial unique index (`incident_events_maintenance_silence_idx`) on `(incident_id, silence_id)` enforces idempotency.

### 12. SLA breach calculation runs asynchronously in the worker loop and uses wall-clock interval checks

Phase 1.2 SLA tracking introduces severity-based response and resolution targets (for `critical` / P1 services: 5 min response / 60 min resolution; for `warning` / P2 services: 15 min response / 240 min resolution) evaluated asynchronously by the remediation worker via `check_sla_breaches()`.

To prevent transaction freeze issues (where `NOW()` returns a static timestamp throughout a transaction), SLA queries compare `clock_timestamp()` against `detected_at + make_interval(mins => sla_..._minutes)`. When a breach occurs, the engine updates `sla_response_breached` or `sla_resolution_breached` flags, appends an `incident_event` audit entry, and increments the `sentinelops_sla_breaches_total` Prometheus counter.

### 13. Decoupled report generation and health page rendering use atomic file swaps and dedicated role permissions

DESIGN.md specified generating PDF reports and exposing system health status. In Phase 1.2, this responsibility was decoupled from the main response worker into a standalone `report-generator` service.

The service performs two periodic tasks:
1. **Health Dashboard**: Queries PostgreSQL and the CMDB, renders `health/index.html` using Jinja2 templates, and publishes it via atomic file swap (`index.html.tmp` -> `index.html`) to prevent web clients from reading partially-written HTML.
2. **PDF Reports**: Automatically scans for incidents reaching `CLOSED` status, generates formal PDF incident reports using ReportLab, records metadata in `incident_reports`, and saves the file to `reports/INC-*.pdf`. Nginx serves `/health/` and `/reports/` directly with read-only access.
