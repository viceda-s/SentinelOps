# Changelog

All notable changes to SentinelOps's design are recorded here. This
tracks changes to `docs/DESIGN.md`'s recorded decisions, not every commit
— see git history for full implementation detail.

## [2.1] - 2026-08-09

### Added

- Introduced `automation/response_engine/config.py` with immutable configuration dataclasses (`DatabaseSettings`, `PrometheusSettings`, `DiagnosticsSettings`, `CMDBSettings`, `AlertmanagerSettings`) for centralized environment variable management.
- Implemented centralized event sequence generation in `automation/response_engine/events.py` using PostgreSQL row-level locking (`SELECT ... FOR UPDATE`) to enforce strictly monotonic event sequence numbers across concurrent operations.

### Changed

- Decomposed `automation/response_engine/handlers.py` into dedicated helper functions (`_reconcile_duplicate_alert`, `_create_new_incident_from_alert`) for improved alert processing modularity and maintainability.
- Decoupled `CMDB_PATH` resolution across scripts (`validate_cmdb.py`, `close_incident.py`, `health_page.py`) to support both containerized execution and local CLI/test invocations.
- Added explicit database connection type hints (`psycopg2.extensions.connection`) across all response engine modules.
- Reconciled `README.md` and `docs/DESIGN.md` with post-Phase 2 architectural refactorings.

## [2.0] - 2026-08-08

### Added

- Shipped Phase 2 operational runbooks: `maintenance-windows.md`, `incident-closure-and-reports.md`, `backup-and-disaster-recovery.md`, `disk-cleanup.md`.
- Added Architecture Decision Records ADR-009 (Maintenance Window Alertmanager Suppression), ADR-010 (SLA Breach Calculation and Metrics), and ADR-011 (Decoupled Report Generation and Health Dashboard).
- Recorded Phase 2 implementation findings 11–13 in `docs/implementation-findings.md` covering maintenance deduplication, `clock_timestamp()` SLA intervals, and atomic health page file publication.
- Performed a repository-wide Python docstring and comment audit establishing PEP 257 Google-style docstrings and explaining critical code invariants without altering application logic.

### Changed

- Updated `README.md` and `docs/DESIGN.md` to reflect Phase 2 completion.
- Reconciled `docs/adr/README.md` index table with Phase 2 ADR additions.

## [1.1] - 2026-08-05

### Changed

- Clarified that the webhook handler identifies services by Alertmanager's
  `job` label, not a `service` label that doesn't exist in practice.
- Documented `NEW → ESCALATED` as a valid incident transition, for
  services unknown to the CMDB that must escalate before any worker has
  claimed them.
- Reorganized the design's description of runbooks around operational
  response rather than alert type, matching how they were actually
  written; documented the CMDB's current per-service (not per-playbook)
  runbook mapping as a known limitation.
- Documented recovery verification as CMDB-driven metadata rather than
  hardcoded worker logic, and updated the CMDB example to include the
  verification configuration (`http`, `docker-health`, or `running`).
- Corrected config validation's alert-coverage check to reflect that
  coverage is defined by Prometheus scrape jobs, not by a `service` label
  on alert rules.
- Clarified incident deduplication semantics: an incident is open for
  fingerprint-based deduplication only while `NEW`, `ACKNOWLEDGED`,
  `IN_PROGRESS`, or `ESCALATED`; `RESOLVED` ends the dedup window.
- Documented that `docker-health` verification reads Docker's existing
  `HEALTHCHECK` status rather than triggering a fresh probe, and that
  remediation timing is recorded with real elapsed wall-clock time.
- Replaced the design's fixed `event`/`component` logging vocabulary with
  the schema actually implemented: `timestamp`, `level`, `logger`,
  `message`, optional `incident_reference`, optional `exception`, and a
  free-form `context` object.
- Clarified that `incident_events` records incident lifecycle only;
  remediation execution detail lives in `remediation_attempts` and the two
  are joined when reconstructing a full timeline.
- Documented that the remediation worker loads the CMDB once at startup
  and escalates incidents referencing a service missing from that
  snapshot. Changes to `cmdb/services.yaml` take effect only after the
  worker is restarted.
