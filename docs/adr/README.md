# Architectural Decision Records

| ADR | Decision |
|---|---|
| [001](001-separate-webhook-ingestion-from-worker.md) | Separate webhook ingestion from the remediation worker |
| 002 | *Reserved — Alertmanager silences, not a custom flag (see DESIGN.md's decision table)* |
| [003](003-use-postgresql-as-the-system-of-record.md) | Use PostgreSQL as the system of record |
| [004](004-drive-remediation-from-the-cmdb.md) | Drive remediation from the CMDB |
| [005](005-explicit-incident-state-machine.md) | Enforce incident transitions through an explicit state machine |
| 006 | *Reserved — root cause analysis stays manual (see DESIGN.md's decision table)* |
| 007 | *Reserved — YAML CMDB, not a database (see DESIGN.md's decision table)* |
| [008](008-autonomous-remediation-with-bounded-verification.md) | Autonomous remediation with bounded verification |
| [009](009-maintenance-window-alertmanager-suppression.md) | Maintenance window Alertmanager suppression |
| [010](010-sla-breach-calculation-and-metrics.md) | SLA breach calculation and metrics |
| [011](011-decoupled-report-generation-and-health-dashboard.md) | Decoupled report generation and health dashboard |

Numbers 002, 006, and 007 correspond to decisions originally recorded in `docs/DESIGN.md`'s decision table and subsequently addressed in Phase 1.2 via ADRs 009 (Alertmanager silences), 010 (SLA tracking), and 011 (reporting service).
