#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$REPO_ROOT"

PURGE=false

usage() {
cat <<EOF
Usage:
    ./automation/scripts/teardown.sh [--purge]

Options:
    --purge    Remove named volumes after confirmation.
    -h, --help Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --purge)
            PURGE=true
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

confirm_purge() {

    local reply=""

    printf "\n"
    printf "This will permanently remove SentinelOps volumes.\n"
    printf "All PostgreSQL and Grafana data will be lost.\n"
    printf "\n"
    printf "Continue? [y/N]: "

    #
    # Treat EOF (Ctrl-D, piped input, etc.) as "no".
    #

    if ! IFS= read -r reply; then
        echo
        echo "Cancelled."
        exit 1
    fi

    case "$reply" in
        y|Y|yes|YES)
            ;;
        *)
            echo "Cancelled."
            exit 0
            ;;
    esac
}

echo "Stopping SentinelOps..."

check_command docker

if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose is not available."
    exit 1
fi

if "$PURGE"; then
    confirm_purge

    docker compose down \
        --volumes \
        --remove-orphans

    echo
    echo "SentinelOps stopped."
    echo "Volumes removed."

else

    docker compose down \
        --remove-orphans

    echo
    echo "SentinelOps stopped."
    echo "Volumes preserved."

fi
