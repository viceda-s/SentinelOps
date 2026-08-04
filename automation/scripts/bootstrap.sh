#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$REPO_ROOT"

#
# Host ports (single source of truth)
#

API_PORT=8081
GRAFANA_PORT=3001
POSTGRES_PORT=5432
PROMETHEUS_PORT=9090
ALERTMANAGER_PORT=9093

VALIDATE_ONLY=false

usage() {
cat <<EOF
Usage:
    ./automation/scripts/bootstrap.sh [--validate-only]

Options:
    --validate-only    Run all validation checks only.
    -h, --help         Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --validate-only)
            VALIDATE_ONLY=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

check_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1"
        exit 1
    fi
}

check_disk_space() {

    #
    # df reports KiB blocks.
    # Require at least 1 GiB free.
    #

    local available

    available=$(df -Pk . | awk 'NR==2 {print $4}')

    if (( available < 1048576 )); then
        echo "Less than 1 GiB of free disk space available."
        exit 1
    fi
}

check_ports() {

    local compose_service_count
    local running_service_count

    compose_service_count=$(docker compose config --services | wc -l | tr -d ' ')
    running_service_count=$(docker compose ps -q | wc -l | tr -d ' ')

    #
    # Stack already running.
    #

    if (( compose_service_count > 0 &&
          running_service_count == compose_service_count )); then

        echo "SentinelOps stack already running; skipping host port checks."
        return
    fi

    #
    # Partial stack.
    #

    if (( running_service_count > 0 )); then
        echo "SentinelOps stack partially running; skipping host port checks."
        return
    fi

    local ports=(
        "$API_PORT"
        "$GRAFANA_PORT"
        "$POSTGRES_PORT"
        "$PROMETHEUS_PORT"
        "$ALERTMANAGER_PORT"
    )

    for port in "${ports[@]}"; do
        if lsof -PiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
            echo "Port $port is already in use by:"
            lsof -PiTCP:"$port" -sTCP:LISTEN
            echo
            echo "Stop the conflicting process or change the port mapping in docker-compose.yml."
            exit 1
        fi
    done
}

validate_cmdb() {
    echo "Validating CMDB..."
    python3 -m automation.scripts.validate_cmdb
}

validate_prometheus() {

    echo "Validating Prometheus rules..."

    docker compose run --rm \
        --entrypoint sh \
        prometheus \
        -c 'promtool check rules /etc/prometheus/rules/*.yml'
}

validate_alertmanager() {

    echo "Validating Alertmanager configuration..."

    docker compose run --rm \
        --entrypoint sh \
        alertmanager \
        -c 'amtool check-config /etc/alertmanager/alertmanager.yml'

    #
    # TODO:
    #
    # DESIGN.md also requires verifying that the maintenance route exists.
    # Maintenance windows are Phase 2, so this check is intentionally
    # deferred until that feature is implemented.
    #
}

validate_compose() {

    echo "Validating Docker Compose configuration..."

    docker compose config >/dev/null
}

wait_for_health() {

    echo "Waiting for containers to become healthy..."

    local deadline
    local unhealthy

    deadline=$(( $(date +%s) + 60 ))

    while (( $(date +%s) < deadline )); do

        unhealthy=$(
            docker compose ps --format json |
            python3 -c '
import json
import sys

services = [
    json.loads(line)
    for line in sys.stdin
    if line.strip()
]

bad = []

for svc in services:

    #
    # Container must be running.
    #

    if svc["State"] != "running":
        bad.append(svc["Service"])
        continue

    #
    # Containers without a Docker HEALTHCHECK expose an
    # empty Health field. Only containers with a health
    # check must report "healthy".
    #

    health = svc.get("Health", "")

    if health and health != "healthy":
        bad.append(svc["Service"])

print(len(bad))
'
        )

        if [[ "$unhealthy" == "0" ]]; then
            return
        fi

        sleep 2

    done

    echo "Timed out waiting for containers to become healthy."
    exit 1
}

print_urls() {

cat <<EOF

==================================================

SentinelOps is ready.

Application:
    http://localhost:${API_PORT}

Grafana:
    http://localhost:${GRAFANA_PORT}

Prometheus:
    http://localhost:${PROMETHEUS_PORT}

Alertmanager:
    http://localhost:${ALERTMANAGER_PORT}

==================================================

EOF
}

echo "Checking host prerequisites..."

check_command docker
check_disk_space
check_ports

if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "Created .env from .env.example with placeholder credentials."
    echo "Edit .env and set real values for POSTGRES_PASSWORD and GRAFANA_ADMIN_PASSWORD before continuing."
fi

validate_cmdb
validate_compose
validate_prometheus
validate_alertmanager

if "$VALIDATE_ONLY"; then
    echo
    echo "Validation successful."
    exit 0
fi

echo
echo "Starting SentinelOps..."

docker compose up -d

wait_for_health

print_urls
