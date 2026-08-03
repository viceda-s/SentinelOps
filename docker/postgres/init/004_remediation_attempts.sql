-- Records every automated remediation attempt executed by the worker.
--
-- An incident may have multiple attempts. Each attempt is numbered     sequentially so retries become part of the permanent audit trail rather than overwriting previous executions.
--
-- The UNIQUE constraint prevents two workers from accidentally recording the same attempt number for a single incident.

CREATE TABLE remediation_attempts (
    id SERIAL PRIMARY KEY,
    incident_id INTEGER NOT NULL
        REFERENCES incidents(id)
        ON DELETE RESTRICT,
    playbook TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    result TEXT,
    diagnostics_path TEXT,
    error TEXT,

    UNIQUE (incident_id, attempt_number)
);
