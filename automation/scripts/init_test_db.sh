#!/usr/bin/env bash
# Reusable test database schema initialization and table verification script.
# Applies all initialization scripts from docker/postgres/init/ in numeric order
# against a fresh target PostgreSQL instance and verifies table creation.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INIT_DIR="$REPO_ROOT/docker/postgres/init"

if [[ -f "$REPO_ROOT/.env.test" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env.test"
    set +a
fi

export PGHOST="${POSTGRES_HOST:-127.0.0.1}"
export PGPORT="${POSTGRES_PORT:-5432}"
export PGDATABASE="${POSTGRES_DB:-sentinelops_test}"
export PGUSER="${POSTGRES_USER:-sentinelops_test}"
export PGPASSWORD="${POSTGRES_PASSWORD:-sentinelops_test_password}"

echo "Connecting to PostgreSQL at ${PGHOST}:${PGPORT}/${PGDATABASE}..."

if psql -tAc "SELECT 1 FROM information_schema.tables WHERE table_name='incidents'" 2>/dev/null | grep -q 1; then
    echo "Test database $PGDATABASE schema already initialized."
else
    echo "Initializing fresh test database schema at ${PGHOST}:${PGPORT}/${PGDATABASE}..."

    for f in "$INIT_DIR"/*; do
        if [[ -f "$f" ]]; then
            case "$f" in
                *.sql)
                    echo "Applying $(basename "$f")..."
                    psql -v ON_ERROR_STOP=1 -f "$f"
                    ;;
                *.sh)
                    echo "Executing $(basename "$f")..."
                    bash "$f"
                    ;;
            esac
        fi
    done
fi

echo "Verifying schema tables..."
REQUIRED_TABLES=("incidents" "incident_events" "remediation_attempts" "incident_reference_counters" "incident_reports")
for table in "${REQUIRED_TABLES[@]}"; do
    count=$(psql -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='$table'")
    if [[ "$count" -lt 1 ]]; then
        echo "error: Table $table was not found in database $PGDATABASE" >&2
        exit 1
    fi
done

echo "Schema initialization and verification complete."
