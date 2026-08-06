#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
    echo "error: .env not found" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1091  # .env is gitignored and machine-specific; nothing to follow.
source .env
set +a

# Tests run from host, not the Docker network
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export CMDB_PATH="$REPO_ROOT/cmdb/services.yaml"

exec pytest "$@"
