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

Numbers 002, 006, and 007 correspond to decisions already made and recorded in `docs/DESIGN.md`'s decision table, but not yet written up as standalone ADRs — not a gap in the numbering, just not due yet. They cover decisions for features (maintenance windows, RCA tooling, CMDB storage) that Phase 1 doesn't build.
