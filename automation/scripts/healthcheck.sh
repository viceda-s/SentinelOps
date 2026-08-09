#!/usr/bin/env bash

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
check_component node-exporter        self-http "http://localhost:9100/metrics"
check_component cadvisor             self-http "http://localhost:8080/healthz"
#
# report-generator has no functional probe: no HEALTHCHECK, no published
# port, no HTTP server -- it's a background polling loop with no
# external-facing surface. State-only check, per the rule above that a
# missing probe is not itself a failure.
#
check_component report-generator

exit "$failed"
