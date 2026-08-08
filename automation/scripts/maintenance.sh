#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://localhost:9093}"
CMDB_PATH="${CMDB_PATH:-${REPO_ROOT}/cmdb/services.yaml}"

usage() {
    cat <<EOF
Usage:
  maintenance.sh
  maintenance.sh list
  maintenance.sh start <service> <duration>
  maintenance.sh end <silence-id>
  maintenance.sh help

Examples:
  maintenance.sh
  maintenance.sh list
  maintenance.sh start api 2h
  maintenance.sh start worker 30m
  maintenance.sh start postgres 1d
  maintenance.sh end 3b5c5e54-f5fb-47c5-8a0e-3af3f3afed71
EOF
}

validate_service() {
    local service="$1"

    python3 - "$CMDB_PATH" "$service" <<'PY'
import sys
import yaml

cmdb_path = sys.argv[1]
service = sys.argv[2]

with open(cmdb_path, encoding="utf-8") as f:
    cmdb = yaml.safe_load(f)

services = cmdb["services"]

if service not in services:
    print(f"Unknown service: {service}", file=sys.stderr)
    sys.exit(1)
PY
}

parse_duration() {
    local duration="$1"

    python3 - "$duration" <<'PY'
import re
import sys

duration = sys.argv[1]

pattern = re.fullmatch(
    r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?',
    duration,
)

if pattern is None or not any(pattern.groups()):
    print(
        f"Invalid duration: {duration!r} "
        "(expected a form like 30m, 1h, 2h30m, 1d)",
        file=sys.stderr,
    )
    sys.exit(1)

days = int(pattern.group(1) or 0)
hours = int(pattern.group(2) or 0)
minutes = int(pattern.group(3) or 0)

total = days * 86400 + hours * 3600 + minutes * 60

if total == 0:
    print(f"Duration cannot be zero: {duration!r}", file=sys.stderr)
    sys.exit(1)

print(total)
PY
}

list_silences() {
    local silences_json

    silences_json="$(
        curl -fsS \
            "${ALERTMANAGER_URL}/api/v2/silences"
    )"

    python3 - "$silences_json" <<'PY'
import json
import sys

silences = json.loads(sys.argv[1])

active = [
    silence
    for silence in silences
    if silence["status"]["state"] == "active"
]

if not active:
    print("No active maintenance windows.")
    raise SystemExit

print(f"{'ID':36}  {'SERVICE':20}  {'ENDS AT'}")

for silence in active:
    service = "-"

    for matcher in silence["matchers"]:
        if matcher["name"] == "job":
            service = matcher["value"]
            break

    print(
        f"{silence['id']:36}  "
        f"{service:20}  "
        f"{silence['endsAt']}"
    )
PY
}

start_maintenance() {
    local service="$1"
    local duration="$2"

    validate_service "$service"

    local seconds
    seconds="$(parse_duration "$duration")"

    local starts_at
    starts_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

    local ends_at
    ends_at="$(
        python3 - "$starts_at" "$seconds" <<'PY'
from datetime import datetime, timedelta, timezone
import sys

start = datetime.strptime(
    sys.argv[1],
    "%Y-%m-%dT%H:%M:%SZ",
).replace(tzinfo=timezone.utc)

seconds = int(sys.argv[2])

end = start + timedelta(seconds=seconds)

print(end.strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)"

    python3 - "$service" "$starts_at" "$ends_at" <<'PY' | curl -fsS \
    -H "Content-Type: application/json" \
    -X POST \
    --data @- \
    "${ALERTMANAGER_URL}/api/v2/silences"
import json
import sys

service = sys.argv[1]
starts_at = sys.argv[2]
ends_at = sys.argv[3]

print(json.dumps({
    "matchers": [
        {
            "name": "job",
            "value": service,
            "isRegex": False,
        }
    ],
    "startsAt": starts_at,
    "endsAt": ends_at,
    "createdBy": "maintenance.sh",
    "comment": "Scheduled maintenance",
}))
PY

    echo
    echo "Maintenance window created."
}

end_maintenance() {
    local silence_id="$1"

    curl -fsS \
        -X DELETE \
        "${ALERTMANAGER_URL}/api/v2/silence/${silence_id}"

    echo
    echo "Maintenance window ended."
}

command="${1:-list}"

case "${command}" in
    list)
        list_silences
        ;;

    start)
        [[ $# -eq 3 ]] || {
            usage
            exit 1
        }

        start_maintenance "$2" "$3"
        ;;

    end)
        [[ $# -eq 2 ]] || {
            usage
            exit 1
        }

        end_maintenance "$2"
        ;;

    help|-h|--help)
        usage
        ;;

    *)
        usage
        exit 1
        ;;
esac
