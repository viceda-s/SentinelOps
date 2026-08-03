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
