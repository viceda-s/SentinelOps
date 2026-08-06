#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 INCIDENT_REFERENCE" >&2
    exit 1
fi

REFERENCE="$1"

if [[ ! -f .env ]]; then
    echo "error: .env not found in repository root." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1091  # .env is gitignored and machine-specific.
source .env
set +a

export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432

checksum() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        echo "error: neither sha256sum nor shasum is available." >&2
        exit 1
    fi
}

RAW_FILE="$(mktemp)"
RCA_FILE="$(mktemp)"

cleanup() {
    rm -f "${RAW_FILE}" "${RCA_FILE}"
}
trap cleanup EXIT

cat >"${RAW_FILE}" <<'EOF'
# Root Cause Analysis
#
# Describe what caused the incident.
#
# Lines beginning with '#' are ignored.
# Leaving this file unchanged aborts the operation.
#
EOF

before="$(checksum "${RAW_FILE}")"

"${EDITOR:-vi}" "${RAW_FILE}"

after="$(checksum "${RAW_FILE}")"

if [[ "${before}" == "${after}" ]]; then
    echo "Aborted: root cause analysis unchanged."
    exit 1
fi

grep -v '^#' "${RAW_FILE}" >"${RCA_FILE}" || true

if [[ ! -s "${RCA_FILE}" ]] || [[ -z "$(tr -d '[:space:]' <"${RCA_FILE}")" ]]; then
    echo "Aborted: root cause analysis is empty."
    exit 1
fi

python3 -m automation.scripts.close_incident \
    "${REFERENCE}" \
    "${RCA_FILE}"
