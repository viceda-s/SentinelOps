# ADR-005: Enforce incident transitions through an explicit state machine

**Status:** Accepted

## Context

An incident's lifecycle spans multiple components: the webhook handler creates incidents, the remediation worker progresses them through remediation, and a human operator may eventually close them. Allowing each component to update `incidents.status` directly would make it possible for incidents to enter invalid or contradictory states—for example, transitioning directly from `NEW` to `RESOLVED`, or reopening a `CLOSED` incident.

The system also requires a complete audit trail explaining when and why each status change occurred, not just the incident's current state.

## Decision

All incident status changes are performed through a single function, `transition()` in `automation/response_engine/state_machine.py`, rather than through direct `UPDATE incidents SET status = ...` statements throughout the codebase.

`transition()` enforces a fixed set of legal transitions (`ALLOWED_TRANSITIONS`):

* `NEW` → `ACKNOWLEDGED`, `SUPPRESSED_MAINTENANCE`, or `ESCALATED`
* `ACKNOWLEDGED` → `IN_PROGRESS` or `ESCALATED`
* `IN_PROGRESS` → `RESOLVED` or `ESCALATED`
* `ESCALATED` → `IN_PROGRESS` or `RESOLVED`
* `RESOLVED` → `CLOSED`

Attempting any transition outside this table raises `ValueError` before any database changes are made.

Every successful transition performs two writes within the same transaction:

* updates `incidents.status` (and any associated timestamp column, such as `resolved_at`, where applicable);
* inserts a `STATE_CHANGE` event into `incident_events`, recording the actor, previous status, new status, and a human-readable message.

This guarantees that the incident's current state and its audit history remain
consistent.

`NEW` → `ESCALATED` is an intentional extension beyond the original `DESIGN.md` v1.0 transition table. When an alert references a service with no matching CMDB entry, the webhook handler immediately escalates the incident instead of routing it through `ACKNOWLEDGED`. This preserves the meaning of `ACKNOWLEDGED` as "claimed by a remediation worker." An unknown-service incident is never claimed, so inserting a synthetic `ACKNOWLEDGED` transition would misrepresent the incident's audit trail by recording a state change that never actually occurred.

## Alternatives considered

* **Direct `UPDATE` statements at each call site.** Rejected because every caller would need to implement transition validation and audit logging independently, increasing the risk of inconsistent behaviour.

* **Database-enforced transitions (triggers or constraints).** Rejected for Phase 1 because it moves lifecycle rules into the database schema, making them harder to read, test, and evolve alongside the response engine. Database enforcement remains a possible defence-in-depth enhancement in the future.

* **No transition validation.** Rejected because independent components (webhook handler and worker) could silently corrupt incident state if either contained a bug.

## Consequences

* Illegal transitions fail immediately with `ValueError` instead of silently corrupting incident state.
* The incident's current status and its audit trail cannot diverge because both are written atomically by the same function.
* Adding a new status or lifecycle path requires a single, explicit change to `ALLOWED_TRANSITIONS`, making the complete incident lifecycle easy to audit.
* `SUPPRESSED_MAINTENANCE` currently has no outgoing transitions defined in `ALLOWED_TRANSITIONS`. As implemented, an incident entering this state cannot transition further until additional transitions are introduced.
