#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$REPO_ROOT"

usage() {
cat <<EOF
Usage:
    ./automation/scripts/chaos.sh <command> [service]

Commands:
    stop <service>    Stop a Compose service.
    fill              Allocate a bounded file until disk is under 15% free.
    reset             Remove the disk filler.

Examples:
    ./automation/scripts/chaos.sh stop api
    ./automation/scripts/chaos.sh fill
    ./automation/scripts/chaos.sh reset

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
    local candidate

    while IFS= read -r candidate; do
        if [[ "$candidate" == "$service" ]]; then
            return
        fi
    done < <(docker compose config --services)

    echo "Unknown service: $service"
    echo
    echo "Available services:"
    docker compose config --services

    exit 1
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

# The filler lives in its own owned path, never under diagnostics/ -- disk_cleanup
# deliberately prunes that directory, so a filler placed there could be destroyed
# by the very playbook under test.
CHAOS_DIR="${REPO_ROOT}/.chaos"
FILL_FILE="${CHAOS_DIR}/disk-fill"

# The target is this script's own constant, deliberately not read from the
# worker's DISK_PRESSURE_FREE_PERCENT or the alert rule: a chaos tool that
# shares configuration with the system under test cannot demonstrate the two agree.
FILL_TARGET_PERCENT=14

# Refuse to allocate more than this. On a large, nearly-empty disk, reaching the
# threshold would mean many gigabytes.
FILL_MAX_MB=5120

# Report the current free percentage of the filesystem holding the repo.
current_free_percent() {
    df -Pk "$REPO_ROOT" | awk 'NR==2 {printf "%d", $4 * 100 / $2}'
}

fill_disk() {

    if [[ -e "$FILL_FILE" ]]; then
        echo "Filler already exists: $FILL_FILE"
        echo "Run './automation/scripts/chaos.sh reset' first."
        exit 1
    fi

    mkdir -p "$CHAOS_DIR"

    local allocated_mb=0

    #
    # Allocate in rounds and re-measure after each. Filesystem rounding,
    # reserved blocks, and concurrent writes mean a single calculated
    # allocation may not actually cross the threshold -- and a fill that
    # reports success while Prometheus never fires is worse than no tool.
    #
    while (( $(current_free_percent) > FILL_TARGET_PERCENT )); do
        local total_kb avail_kb target_avail_kb needed_kb needed_mb

        total_kb="$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $2}')"
        avail_kb="$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $4}')"

        target_avail_kb=$(( total_kb * FILL_TARGET_PERCENT / 100 ))
        needed_kb=$(( avail_kb - target_avail_kb ))
        needed_mb=$(( needed_kb / 1024 + 1 ))

        if (( allocated_mb + needed_mb > FILL_MAX_MB )); then
            rm -f "$FILL_FILE"
            echo "Refusing to allocate $(( allocated_mb + needed_mb ))MB (cap: ${FILL_MAX_MB}MB)."
            echo "This disk is too large to fill safely; test disk_cleanup with unit tests instead."
            exit 1
        fi

        echo "Allocating ${needed_mb}MB (total ${allocated_mb}MB so far)..."

        # bs=1048576 is 1MiB written portably: GNU dd spells the suffix 1M and
        # BSD/macOS spells it 1m, but the raw byte count works on both.
        # Appending via shell redirection rather than oflag=append, which BSD dd
        # rejects outright ("unknown open flag append") -- leaving the filler
        # silently under-allocated and the alert never firing.
        if ! dd if=/dev/zero bs=1048576 count="$needed_mb" 2>/dev/null >> "$FILL_FILE"; then
            rm -f "$FILL_FILE"
            echo "Allocation failed; filler removed."
            exit 1
        fi

        allocated_mb=$(( allocated_mb + needed_mb ))
    done

    echo
    echo "Chaos event injected:"
    echo "  type: fill"
    echo "  path: $FILL_FILE"
    echo "  size: ${allocated_mb}MB"
    echo "  free:  $(current_free_percent)% (threshold: 15%)"
    echo
    echo "DiskPressure fires after 2m. Undo with:"
    echo "  ./automation/scripts/chaos.sh reset"
}

reset_chaos() {

    if [[ ! -e "$FILL_FILE" ]]; then
        echo "No filler to remove."
        return
    fi

    rm -f "$FILL_FILE"

    echo "Removed $FILL_FILE"
}

COMMAND="${1:-}"

if [[ -z "$COMMAND" ]]; then
    usage
    exit 1
fi

check_command docker
check_compose

case "$COMMAND" in
    stop)
        SERVICE="${2:-}"

        if [[ -z "$SERVICE" ]]; then
            usage
            exit 1
        fi

        validate_service "$SERVICE"
        stop_service "$SERVICE"
        ;;
    fill)
        fill_disk
        ;;
    reset)
        reset_chaos
        ;;
    *)
        echo "Unknown command: $COMMAND"
        echo
        usage
        exit 1
        ;;
esac
