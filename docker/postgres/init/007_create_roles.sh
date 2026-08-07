#!/usr/bin/env bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
    -v response_engine_password="$RESPONSE_ENGINE_DB_PASSWORD" \
    -v report_generator_password="$REPORT_GENERATOR_DB_PASSWORD" \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" <<-'EOSQL'

CREATE ROLE response_engine LOGIN PASSWORD :'response_engine_password';
CREATE ROLE report_generator LOGIN PASSWORD :'report_generator_password';



GRANT SELECT, INSERT, UPDATE ON incidents, incident_events, remediation_attempts, incident_reference_counters TO response_engine;
GRANT USAGE ON SCHEMA public to response_engine;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO response_engine;
GRANT SELECT ON incident_reports TO response_engine;

GRANT SELECT ON incidents, incident_events, remediation_attempts TO report_generator;
GRANT USAGE ON SCHEMA public TO report_generator;
GRANT SELECT, INSERT ON incident_reports TO report_generator;
EOSQL
