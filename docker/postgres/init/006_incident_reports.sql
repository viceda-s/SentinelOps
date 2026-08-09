-- Adds the incident_reports table used to coordinate asynchronous PDF generation between close_incident.py and report_generator.
--
-- This file contains schema only. PostgreSQL roles, passwords, and grants are created separately by 007_create_roles.sh so credentials come from the container environment rather than being hard-coded in version-controlled SQL.
--
-- Each incident can have at most one generated report. Using incident_id as the primary key enforces this invariant at the database level.

CREATE TABLE incident_reports (
    incident_id INTEGER PRIMARY KEY
        REFERENCES incidents(id)
        ON DELETE RESTRICT,
    generated_at TIMESTAMPTZ NOT NULL,
    path TEXT NOT NULL,
    checksum TEXT NOT NULL
);

COMMENT ON TABLE incident_reports IS
'Metadata for generated incident PDF reports. One immutable report per incident.';
