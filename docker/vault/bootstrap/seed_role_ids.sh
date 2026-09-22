#!/usr/bin/env bash
# Baking a secret_id into an image is a deliberate dev-lab trade-off; rotate by re-running this and rebuilding.
set -euo pipefail

export VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
export VAULT_TOKEN="${VAULT_DEV_ROOT_TOKEN:?VAULT_DEV_ROOT_TOKEN must be set}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

declare -A ROLE_MAP=(
  [api]=api
  [webhook-handler]=webhook_handler
  [worker]=worker
  [report-generator]=report_generator
  [maintenance-monitor]=maintenance_monitor
  [grafana]=grafana
)

for svc in "${!ROLE_MAP[@]}"; do
    role_name="${ROLE_MAP[$svc]}"
    out_dir="$REPO_ROOT/docker/vault/agent/roleids/${svc}"
    mkdir -p "$out_dir"

    vault read -field=role_id "auth/approle/role/${role_name}/role-id" > "$out_dir/role-id"
    vault write -field=secret_id -f "auth/approle/role/${role_name}/secret-id" > "$out_dir/secret-id"

    echo "Seeded role/secret IDs for ${svc} at ${out_dir}"
done
