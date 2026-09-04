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
    fill              Build disposable dangling Docker images until disk is under 10% free.
    reset             Remove the disk filler images.

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

# Never under diagnostics/ -- disk_cleanup prunes that directory.
CHAOS_DIR="${REPO_ROOT}/.chaos"

# Filler images are built dangling (no --tag) so disk_cleanup's unmodified
# `images.prune(dangling=True)` reclaims them for real, not via a test-only path.
FILL_IMAGE_IDS_FILE="${CHAOS_DIR}/disk-fill-image-ids"
FILL_DOCKERFILE="${CHAOS_DIR}/disk-fill.Dockerfile"

# Already local by the time chaos.sh runs (bootstrap.sh starts the postgres service).
FILLER_BASE_IMAGE="postgres:16-alpine"

# Not read from the worker's config -- sharing config with the system under test
# can't demonstrate the two agree.
FILL_TARGET_PERCENT=10

# Margin below target: df/Prometheus measurement noise can otherwise land exactly at
# the threshold and flip back above it, resetting the alert's `for: 2m` timer.
FILL_MARGIN_PERCENT="${CHAOS_FILL_MARGIN_PERCENT:-3}"
FILL_DEST_PERCENT=$(( FILL_TARGET_PERCENT - FILL_MARGIN_PERCENT ))

# Total allocation cap, in case of a large disk.
FILL_MAX_MB="${CHAOS_FILL_MAX_MB:-5120}"

# Per-build cap: a `docker build` is one opaque, uninterruptible operation, and
# Docker Desktop's VM disk has been observed to grow well past the MB requested in
# one large build. Small rounds bound the damage and let the loop re-measure between
# them instead of trusting one giant calculated allocation.
FILL_ROUND_MAX_MB="${CHAOS_FILL_ROUND_MAX_MB:-4096}"

# Must exceed the alert's `for: 2m` -- a dip that's brief never lets it fire.
SUSTAIN_SECONDS="${CHAOS_FILL_SUSTAIN_SECONDS:-150}"
SUSTAIN_POLL_INTERVAL=10

current_free_percent() {
    df -Pk "$REPO_ROOT" | awk 'NR==2 {printf "%d", $4 * 100 / $2}'
}

# Unrounded KB arithmetic so a target equal to the truncated percent above doesn't
# short-circuit the loop before anything is allocated.
above_fill_target() {
    df -Pk "$REPO_ROOT" | awk -v target="$FILL_TARGET_PERCENT" 'NR==2 {exit !($4 * 100 > target * $2)}'
}

# Builds one dangling image, sized to close the gap to FILL_DEST_PERCENT but capped
# at FILL_ROUND_MAX_MB per round and FILL_MAX_MB in total. Mutates $allocated_mb
# (caller's running total) in place; removes filler and exits on cap or failure.
allocate_needed() {
    local total_kb avail_kb dest_avail_kb needed_kb needed_mb round_mb image_id

    total_kb="$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $2}')"
    avail_kb="$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $4}')"

    dest_avail_kb=$(( total_kb * FILL_DEST_PERCENT / 100 ))
    needed_kb=$(( avail_kb - dest_avail_kb ))
    needed_mb=$(( needed_kb / 1024 + 1 ))

    round_mb=$needed_mb
    if (( round_mb > FILL_ROUND_MAX_MB )); then
        round_mb=$FILL_ROUND_MAX_MB
    fi

    if (( allocated_mb + round_mb > FILL_MAX_MB )); then
        reset_chaos
        echo "Refusing to allocate $(( allocated_mb + round_mb ))MB (cap: ${FILL_MAX_MB}MB)."
        echo "This disk is too large to fill safely; test disk_cleanup with unit tests instead."
        exit 1
    fi

    echo "Allocating ${round_mb}MB (total ${allocated_mb}MB so far, ~${needed_mb}MB still needed)..."

    # Multi-stage: the builder stage is discarded by BuildKit, so the final
    # dangling image (-q, no --tag) is just the generated data.
    if ! image_id="$(docker build -q \
        --build-arg "FILL_MB=${round_mb}" \
        --build-arg "BASE_IMAGE=${FILLER_BASE_IMAGE}" \
        -f "$FILL_DOCKERFILE" "$CHAOS_DIR" 2>/dev/null)"; then
        reset_chaos
        echo "Allocation failed; filler images removed."
        exit 1
    fi

    # BuildKit leaves the RUN layer in the build cache too, roughly doubling real
    # host-disk usage per round if left alone -- prune it immediately so only the
    # image itself (tracked in $allocated_mb) persists.
    docker builder prune -af >/dev/null 2>&1 || true

    echo "$image_id" >> "$FILL_IMAGE_IDS_FILE"
    allocated_mb=$(( allocated_mb + round_mb ))
}

fill_disk() {

    if [[ -e "$FILL_IMAGE_IDS_FILE" ]]; then
        echo "Filler images already recorded: $FILL_IMAGE_IDS_FILE"
        echo "Run './automation/scripts/chaos.sh reset' first."
        exit 1
    fi

    mkdir -p "$CHAOS_DIR"

    # RUN generates the data in-container (no build-context upload); FROM scratch
    # keeps the final image to just that data.
    cat > "$FILL_DOCKERFILE" <<'DOCKERFILE'
ARG BASE_IMAGE
FROM ${BASE_IMAGE} AS filler-base
ARG FILL_MB
RUN dd if=/dev/zero of=/chaos-filler bs=1M count=${FILL_MB} 2>/dev/null

FROM scratch
COPY --from=filler-base /chaos-filler /chaos-filler
DOCKERFILE

    local allocated_mb=0

    # Re-measure after each round rather than trusting one calculated allocation.
    while above_fill_target; do
        allocate_needed
    done

    echo
    echo "Holding below ${FILL_TARGET_PERCENT}% free for ${SUSTAIN_SECONDS}s so the" \
        "DiskPressure alert's sustained-duration window can complete..."

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
    echo "  images: $(wc -l < "$FILL_IMAGE_IDS_FILE" | tr -d ' ')"
    echo "  size: ${allocated_mb}MB"
    echo "  free:  $(current_free_percent)% (threshold: ${FILL_TARGET_PERCENT}%)"
    echo
    echo "DiskPressure fires after 2m. Undo with:"
    echo "  ./automation/scripts/chaos.sh reset"
}

reset_chaos() {

    if [[ ! -e "$FILL_IMAGE_IDS_FILE" ]]; then
        echo "No filler images to remove."
        return
    fi

    while IFS= read -r image_id; do
        [[ -n "$image_id" ]] || continue
        docker rmi -f "$image_id" >/dev/null 2>&1 || true
    done < "$FILL_IMAGE_IDS_FILE"

    docker builder prune -af >/dev/null 2>&1 || true

    rm -f "$FILL_IMAGE_IDS_FILE" "$FILL_DOCKERFILE"

    echo "Removed filler images."
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
