#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "$REPO_ROOT"

BACKUP_DIR="${BACKUP_DIR:-${REPO_ROOT}/backups}"
BACKUP_RETENTION="${BACKUP_RETENTION:-7}"
DASHBOARD_DIR="${REPO_ROOT}/docker/grafana/dashboards"

usage() {
    cat <<EOF
Usage:
  backup.sh
  backup.sh help

Archives declared Grafana configuration and PostgreSQL state into one
timestamped .tar.gz, then prunes all but the newest BACKUP_RETENTION archives.

Environment:
  BACKUP_DIR         Output directory (default: ./backups)
  BACKUP_RETENTION   Archives to keep (default: 7)

Restore the database with:
  docker compose exec -T postgres psql -U "\$POSTGRES_USER" -d "\$POSTGRES_DB" < postgres.sql
EOF
}

if [[ "${1:-}" == "help" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if [[ ! -f .env ]]; then
    echo "error: .env not found" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1091  # .env is gitignored and machine-specific.
source .env
set +a

#
# BACKUP_RETENTION=0 would make the prune step's `tail -n "+1"` select every
# archive including the one this run just created -- deleting all backups,
# the exact zero-archives outcome count-based retention exists to prevent.
# Reject anything that isn't a positive integer before doing any work.
#
# Placed after .env is sourced, not right after the line-11 default: .env
# uses `set -a` and can overwrite BACKUP_RETENTION, so validating the
# pre-.env value would validate the wrong number -- the effective value is
# whatever survives after .env is loaded. Placed after the --help check
# above so a bad value never blocks --help from working.
#
if ! [[ "$BACKUP_RETENTION" =~ ^[1-9][0-9]*$ ]]; then
    echo "error: BACKUP_RETENTION must be a positive integer, got: ${BACKUP_RETENTION}" >&2
    exit 1
fi

timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"
final_archive="${BACKUP_DIR}/sentinelops-${timestamp}.tar.gz"
tmp_archive="${BACKUP_DIR}/.sentinelops-${timestamp}.tar.gz.tmp"

mkdir -p "$BACKUP_DIR"

#
# Clear any .tmp left behind by a previously crashed run.
#
rm -f "${BACKUP_DIR}"/.sentinelops-*.tar.gz.tmp

staging="$(mktemp -d)"

cleanup() {
    rm -rf "$staging"
    rm -f "$tmp_archive"
}
trap cleanup EXIT

#
# 1. PostgreSQL: mutable state. Full database, schema + data, plain SQL.
#    Taken through the container so the client version matches the server.
#
echo "Dumping PostgreSQL..."
docker compose exec -T postgres \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "${staging}/postgres.sql"

#
# 2. Grafana: declared configuration. Git is authoritative, so the dashboards
#    are copied from the provisioned files rather than exported from a running
#    Grafana. Backup therefore does not depend on Grafana being up.
#
echo "Copying Grafana dashboards..."
mkdir -p "${staging}/grafana"
cp "${DASHBOARD_DIR}"/*.json "${staging}/grafana/"

#
# 3. Build the archive under a temporary name, then rename it into place.
#    tar itself can fail partway and leave a truncated file, so a final
#    sentinelops-*.tar.gz must only ever appear after a complete, successful
#    archive. The .tmp lives in BACKUP_DIR so the rename stays on one
#    filesystem and is atomic.
#
echo "Creating archive..."
tar -czf "$tmp_archive" -C "$staging" postgres.sql grafana
mv "$tmp_archive" "$final_archive"

echo "Created ${final_archive}"

#
# 4. Prune only after the new archive is safely installed. Pruning earlier would
#    let a failed backup delete valid ones -- and repeated, leave zero archives,
#    the exact outcome count-based retention exists to prevent.
#
pruned=0
# shellcheck disable=SC2012  # ls -t is intentional: need mtime order, not filename order
while IFS= read -r stale; do
    rm -f "$stale"
    pruned=$(( pruned + 1 ))
done < <(ls -1t "${BACKUP_DIR}"/sentinelops-*.tar.gz 2>/dev/null | tail -n "+$(( BACKUP_RETENTION + 1 ))")

echo "Retained newest ${BACKUP_RETENTION} archive(s); pruned ${pruned}."
