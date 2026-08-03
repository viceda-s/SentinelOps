# Implementation findings

Real discrepancies between `docs/DESIGN.md` v1.0 and what building it actually
required, found during Phase 1. Not a changelog and not a wishlist — only
things where the design's own words contradict each other or contradict
observed reality. Each one becomes a CHANGELOG entry and an ADR when DESIGN.md
gets its v1.1 pass; until then the code follows the finding, not the frozen
doc, and says so at the point of deviation.

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

DESIGN.md says runbooks are written "one per alert type." Phase 1's two
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
