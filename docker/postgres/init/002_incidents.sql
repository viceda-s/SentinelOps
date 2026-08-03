-- Primary incident record.
--
-- Exactly one row represents one active incident. The incident's lifecycle (NEW → ACKNOWLEDGED → IN_PROGRESS → RESOLVED → CLOSED) is tracked by the status column, while a complete audit trail of every change is stored separately in incident_events.
--
-- Fingerprint deduplication is enforced by a partial unique index: only incidents that are still active participate in the uniqueness check. Once an incident reaches a terminal state (CLOSED or SUPPRESSED_MAINTENANCE), the same fingerprint may legitimately create a new incident in the future.
--
-- labels and annotations store the original Alertmanager metadata exactly as received so the response engine retains the complete alert context.

CREATE TABLE incidents (
    id SERIAL PRIMARY KEY,
    reference TEXT UNIQUE NOT NULL,
    fingerprint TEXT NOT NULL,
    alert_name TEXT NOT NULL,
    service TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    owner TEXT,
    tier TEXT,
    criticality TEXT,
    playbook TEXT,
    detected_at TIMESTAMPTZ NOT NULL,
    acknowledged_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    sla_response_minutes INTEGER,
    sla_resolution_minutes INTEGER,
    sla_response_breached BOOLEAN NOT NULL DEFAULT FALSE,
    sla_resolution_breached BOOLEAN NOT NULL DEFAULT FALSE,
    root_cause_analysis TEXT,
    labels JSONB NOT NULL,
    annotations JSONB NOT NULL
);

CREATE UNIQUE INDEX incidents_active_fingerprint_idx
ON incidents (fingerprint)
WHERE status NOT IN ('CLOSED', 'SUPPRESSED_MAINTENANCE');

