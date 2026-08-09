#!/usr/bin/env bash

# Deliberately omitting -e (despite project convention) to uphold the
# "never short-circuit" contract for this script. If a command substitution
# like `docker compose ps` fails, the script must continue checking the rest.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "$REPO_ROOT" || exit 1

usage() {
    cat <<EOF
Usage:
  healthcheck.sh
  healthcheck.sh help

One-shot status of every SentinelOps component. Checks container state and a
functional probe for each. Exits 0 if everything passes, 1 if anything fails.
EOF
}

if [[ "${1:-}" == "help" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091  # .env is gitignored and machine-specific.
    source .env
    set +a
fi

failed=0

report() {
    local component="$1"
    local status="$2"
    local reason="${3:-}"

    if [[ "$status" == "OK" ]]; then
        printf '%-22s OK\n' "$component"
    else
        printf '%-22s FAIL: %s\n' "$component" "$reason"
        failed=1
    fi
}

#
# Container state. A missing Docker HEALTHCHECK is not itself a failure --
# only postgres declares one, and services legitimately expose different health
# signals. If a HEALTHCHECK exists, require it to be healthy.
#
check_state() {
    local service="$1"
    local container_id state health

    container_id="$(docker compose ps -q "$service" 2>/dev/null)"

    if [[ -z "$container_id" ]]; then
        echo "no container"
        return 1
    fi

    state="$(docker inspect -f '{{.State.Status}}' "$container_id" 2>/dev/null)"

    if [[ "$state" != "running" ]]; then
        echo "container ${state}"
        return 1
    fi

    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container_id" 2>/dev/null)"

    if [[ -n "$health" && "$health" != "healthy" ]]; then
        echo "healthcheck ${health}"
        return 1
    fi

    return 0
}

# Probe a URL from the host.
check_http() {
    local url="$1"

    if ! curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
        echo "HTTP probe failed (${url})"
        return 1
    fi

    return 0
}

# Probe from inside the Compose network. The engine processes serve /metrics on
# port 8000 but publish no host port.
check_internal_http() {
    local service="$1"
    local url="$2"

    if ! docker compose exec -T "$service" \
        python3 -c "import urllib.request,sys; urllib.request.urlopen('${url}', timeout=5)" \
        >/dev/null 2>&1; then
        echo "metrics probe failed (${url})"
        return 1
    fi

    return 0
}

# Probe a service's own HTTP endpoint using tooling inside that same
# container. node-exporter and cadvisor are minimal non-Python images (no
# python3, unlike the engine processes' python:3.13-slim base) but ship
# BusyBox wget, which uses -T SEC for a timeout -- it has no --timeout
# long-flag, confirmed against both images before writing this.
#
# Architectural limitation, confirmed by testing: this is an in-container
# liveness probe, not a network reachability probe. It verifies the
# service's HTTP endpoint responds from its own network namespace (over
# localhost, via docker compose exec) -- it does NOT verify host-to-
# container, inter-container, or external network connectivity. Confirmed
# directly: docker network disconnect on a live node-exporter container
# left this probe returning success, since disconnecting the container's
# external network attachment has no effect on its loopback interface. This
# is inherent to probing via docker compose exec + localhost, not a defect;
# closing it would require publishing a host port for node-exporter/cadvisor
# purely for diagnostics, which is a deliberate trade-off this fix declines
# to make. A container-stopped failure is still caught by check_state()
# above, and an HTTP server that's actually dead/unresponsive inside its own
# container is still caught by this probe -- only an external network-path
# failure with the process still alive and responsive to itself falls
# outside what self-http can observe.
check_self_http() {
    local service="$1"
    local url="$2"

    if ! docker compose exec -T "$service" \
        wget -qO- -T 5 "$url" >/dev/null 2>&1; then
        echo "HTTP probe failed (${url})"
        return 1
    fi

    return 0
}

# Probe whether Prometheus can actually scrape a target, via its own
# recorded up{} metric -- not whether the target responds to itself over
# loopback. This is the correct check for node-exporter/cadvisor: the
# failure mode that matters is "Prometheus can't scrape this," since that's
# what determines whether DiskPressure can evaluate at all, and a loopback
# probe cannot observe that (confirmed live: a broken Compose DNS alias
# left node-exporter answering localhost while Prometheus's own scrape
# target for it was down, and the loopback probe never caught it).
#
# Scoped to job AND instance, not just job, so a query can't accidentally
# pass because some other node-exporter target elsewhere is healthy.
#
# Bounded by a freshness check on the sample's own timestamp, same
# principle as disk_cleanup's Prometheus re-check in remediation.py: an up
# value that Prometheus stopped updating (e.g. Prometheus itself wedged)
# must not be trusted just because it happens to read 1.
check_prometheus_up() {
    local job="$1"
    local instance="$2"

    local query="up{job=\"${job}\",instance=\"${instance}\"}"
    local encoded_query
    encoded_query="$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$query")"
    local url="${PROMETHEUS_URL:-http://localhost:9090}/api/v1/query?query=${encoded_query}"

    local response
    if ! response="$(curl -fsS --max-time 5 "$url" 2>&1)"; then
        echo "Prometheus query failed for up{job=\"${job}\",instance=\"${instance}\"}"
        return 1
    fi

    python3 - "$response" "$job" "$instance" <<'PY'
import json
import sys
import time

response, job, instance = sys.argv[1], sys.argv[2], sys.argv[3]

MAX_SAMPLE_AGE_SECONDS = 30

try:
    body = json.loads(response)
except json.JSONDecodeError:
    print(f"malformed Prometheus response for up{{job={job!r}, instance={instance!r}}}")
    sys.exit(1)

if body.get("status") != "success":
    print(f"Prometheus returned non-success status for up{{job={job!r}, instance={instance!r}}}")
    sys.exit(1)

result = body.get("data", {}).get("result", [])

if len(result) != 1:
    print(f"expected exactly one series for up{{job={job!r}, instance={instance!r}}}, got {len(result)}")
    sys.exit(1)

sample_timestamp, raw_value = result[0]["value"]
sample_age = time.time() - float(sample_timestamp)

if sample_age > MAX_SAMPLE_AGE_SECONDS:
    print(f"up{{job={job!r}, instance={instance!r}}} sample is stale: {sample_age:.1f}s old")
    sys.exit(1)

if raw_value != "1":
    print(f"Prometheus cannot scrape job={job!r} instance={instance!r} (up={raw_value})")
    sys.exit(1)
PY
}

check_component() {
    local component="$1"
    local probe_type="${2:-}"
    local probe_arg="${3:-}"
    local reason

    if ! reason="$(check_state "$component")"; then
        report "$component" FAIL "$reason"
        return
    fi

    case "$probe_type" in
        http)
            if ! reason="$(check_http "$probe_arg")"; then
                report "$component" FAIL "$reason"
                return
            fi
            ;;
        metrics)
            if ! reason="$(check_internal_http "$component" "$probe_arg")"; then
                report "$component" FAIL "$reason"
                return
            fi
            ;;
        self-http)
            if ! reason="$(check_self_http "$component" "$probe_arg")"; then
                report "$component" FAIL "$reason"
                return
            fi
            ;;
        prometheus-up)
            if ! reason="$(check_prometheus_up "$component" "$probe_arg")"; then
                report "$component" FAIL "$reason"
                return
            fi
            ;;
        postgres)
            if ! docker compose exec -T postgres pg_isready -U "$POSTGRES_USER" >/dev/null 2>&1; then
                report "$component" FAIL "pg_isready failed"
                return
            fi
            ;;
    esac

    report "$component" OK
}

#
# Every component is checked; the script never short-circuits. During a
# multi-component outage one invocation must tell the whole story.
#
# nginx is probed at /nginx-health, a dedicated nginx-native endpoint, rather
# than / (proxies to api, which doesn't implement /, so it always 404s even
# when nginx is healthy) or /health/ (only 200s because it happens to serve a
# static file the report generator wrote, not a real nginx liveness signal).
#
check_component nginx               http     "http://localhost:8081/nginx-health"
check_component api                 http     "http://localhost:5001/health"
check_component postgres            postgres
check_component prometheus          http     "http://localhost:9090/-/healthy"
check_component alertmanager        http     "http://localhost:9093/-/healthy"
check_component grafana             http     "http://localhost:3001/api/health"
check_component worker              metrics  "http://worker:8000/metrics"
check_component webhook-handler     metrics  "http://webhook-handler:8000/metrics"
check_component maintenance-monitor metrics  "http://maintenance-monitor:8000/metrics"
check_component node-exporter       prometheus-up "node-exporter:9100"
check_component cadvisor            prometheus-up "cadvisor:8080"
#
# report-generator has no functional probe: no HEALTHCHECK, no published
# port, no HTTP server -- it's a background polling loop with no
# external-facing surface. State-only check, per the rule above that a
# missing probe is not itself a failure.
#
check_component report-generator

exit "$failed"
