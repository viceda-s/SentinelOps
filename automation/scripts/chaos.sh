#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$REPO_ROOT"

usage() {
cat <<EOF
Usage:
    ./automation/scripts/chaos.sh <command> <service>

Commands:
    stop        Stop a Compose service.

Examples:
    ./automation/scripts/chaos.sh stop api
    ./automation/scripts/chaos.sh stop postgres

EOF
}

check_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1"
        exit 1
    fi
}

check_compose() {
    if ! docker compose version >/dev/null 2>&1; then
        echo "Docker Compose is not available."
        exit 1
    fi
}

validate_service() {

    local service="$1"

    if ! docker compose config --services | grep -Fxq "$service"; then
        echo "Unknown service: $service"
        echo
        echo "Available services:"
        docker compose config --services
        exit 1
    fi
}

stop_service() {

    local service="$1"

    echo "Stopping service '$service'..."

    docker compose stop "$service"

    echo
    echo "Chaos event injected:"
    echo "  type: stop"
    echo "  service: $service"
}

COMMAND="${1:-}"
SERVICE="${2:-}"

if [[ -z "$COMMAND" || -z "$SERVICE" ]]; then
    usage
    exit 1
fi

check_command docker
check_compose
validate_service "$SERVICE"

case "$COMMAND" in
    stop)
        stop_service "$SERVICE"
        ;;
    *)
        echo "Unknown command: $COMMAND"
        echo
        usage
        exit 1
        ;;
esac
