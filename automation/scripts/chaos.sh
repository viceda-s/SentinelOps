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
FILL_TARGET_PERCENT=10

# Allocate down to this many points below FILL_TARGET_PERCENT, not to the threshold
# itself. df's measurement has enough noise (rounding, a few hundred KB reclaimed or
# written elsewhere between the fill's own check and Prometheus's next scrape) that
# landing exactly at the threshold risks one evaluation cycle reading back above it --
# which resets the DiskPressure alert rule's `for: 2m` pending timer and can burn the
# entire sustain window without ever reaching a stable firing state.
FILL_MARGIN_PERCENT="${CHAOS_FILL_MARGIN_PERCENT:-3}"
FILL_DEST_PERCENT=$(( FILL_TARGET_PERCENT - FILL_MARGIN_PERCENT ))

# Refuse to allocate more than this. On a large, nearly-empty disk, reaching the
# threshold would mean many gigabytes.
FILL_MAX_MB="${CHAOS_FILL_MAX_MB:-5120}"

# How long to keep watching free space after the initial fill and top it back up if
# it drifts above target. Must comfortably exceed the DiskPressure alert rule's
# `for: 2m` -- a fill that dips below target only briefly (host-level reclaim,
# concurrent writes elsewhere on the disk) never lets that sustained-duration
# requirement complete, so the alert silently never fires.
SUSTAIN_SECONDS="${CHAOS_FILL_SUSTAIN_SECONDS:-150}"
SUSTAIN_POLL_INTERVAL=10

# Report the current free percentage of the filesystem holding the repo, truncated
# to an integer for human-readable output. Not precise enough to gate the fill loop:
# a filesystem sitting at e.g. 10.4% free truncates to "10", which would read as
# already-at-target against a 10% threshold and skip allocating entirely.
current_free_percent() {
    df -Pk "$REPO_ROOT" | awk 'NR==2 {printf "%d", $4 * 100 / $2}'
}

# Whether free space is still above the target, using unrounded KB arithmetic
# so a target equal to the truncated current_free_percent doesn't short-circuit
# the fill loop before anything is allocated.
above_fill_target() {
    df -Pk "$REPO_ROOT" | awk -v target="$FILL_TARGET_PERCENT" 'NR==2 {exit !($4 * 100 > target * $2)}'
}

# Top up the filler by the KB needed to bring free space down to FILL_DEST_PERCENT
# (below target, not merely at it -- see FILL_MARGIN_PERCENT), respecting FILL_MAX_MB.
# Prints progress and mutates $allocated_mb (caller's running total) in place; on
# cap-exceeded or write failure, removes the filler and exits the script.
allocate_needed() {
    local total_kb avail_kb dest_avail_kb needed_kb needed_mb

    total_kb="$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $2}')"
    avail_kb="$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $4}')"

    dest_avail_kb=$(( total_kb * FILL_DEST_PERCENT / 100 ))
    needed_kb=$(( avail_kb - dest_avail_kb ))
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
    while above_fill_target; do
        allocate_needed
    done

    echo
    echo "Holding below ${FILL_TARGET_PERCENT}% free for ${SUSTAIN_SECONDS}s so the" \
        "DiskPressure alert's sustained-duration window can complete..."

    # A brief dip below target isn't enough: the alert rule requires free space to
    # stay under threshold continuously for 2m. Host-level reclaim or concurrent
    # writes elsewhere on the disk can push free space back above target within
    # seconds of the initial fill -- keep watching and top up if that happens.
    local elapsed=0
    while (( elapsed < SUSTAIN_SECONDS )); do
        if above_fill_target; then
            echo "Free space drifted back above ${FILL_TARGET_PERCENT}%; topping up..."
            allocate_needed
        fi

        sleep "$SUSTAIN_POLL_INTERVAL"
        elapsed=$(( elapsed + SUSTAIN_POLL_INTERVAL ))
    done

    echo
    echo "Chaos event injected:"
    echo "  type: fill"
    echo "  path: $FILL_FILE"
    echo "  size: ${allocated_mb}MB"
    echo "  free:  $(current_free_percent)% (threshold: ${FILL_TARGET_PERCENT}%)"
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
