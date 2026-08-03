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

