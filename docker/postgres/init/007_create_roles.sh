#!/usr/bin/env bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" <<EOSQL

DO \$$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'response_engine') THEN
        CREATE ROLE response_engine LOGIN PASSWORD '${RESPONSE_ENGINE_DB_PASSWORD}';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'report_generator') THEN
        CREATE ROLE report_generator LOGIN PASSWORD '${REPORT_GENERATOR_DB_PASSWORD}';
    END IF;
END \$$;

GRANT SELECT, INSERT, UPDATE ON incidents, incident_events, remediation_attempts, incident_reference_counters TO response_engine;
GRANT USAGE ON SCHEMA public to response_engine;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO response_engine;
GRANT SELECT ON incident_reports TO response_engine;

GRANT SELECT ON incidents, incident_events, remediation_attempts TO report_generator;
GRANT USAGE ON SCHEMA public TO report_generator;
GRANT SELECT, INSERT ON incident_reports TO report_generator;
EOSQL
