#!/usr/bin/env bash
# Idempotent: safe to re-run against a fresh dev-mode Vault (no persistent storage).
set -euo pipefail

export VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
export VAULT_TOKEN="${VAULT_DEV_ROOT_TOKEN:?VAULT_DEV_ROOT_TOKEN must be set}"

SERVICES=(api webhook-handler worker report-generator maintenance-monitor grafana)

vault auth enable approle 2>/dev/null || echo "approle already enabled"
vault secrets enable -path=secret -version=2 kv 2>/dev/null || echo "kv already enabled at secret/"

vault kv put secret/sentinelops/grafana admin_password="${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD must be set}"

vault secrets enable database 2>/dev/null || echo "database engine already enabled"

vault write database/config/sentinelops-postgres \
    plugin_name=postgresql-database-plugin \
    connection_url="postgresql://{{username}}:{{password}}@postgres:5432/${POSTGRES_DB:?POSTGRES_DB must be set}?sslmode=disable" \
    allowed_roles="response_engine,report_generator,api" \
    username="${POSTGRES_USER:?POSTGRES_USER must be set}" \
    password="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"

# CREATE ROLE ... IN ROLE, not ALTER ROLE: each lease is its own login so concurrent services never overwrite each other's credential.
# REASSIGN OWNED/DROP OWNED/DROP ROLE, not bare DROP ROLE: tolerates a role that still owns grants or has a live connection.
for db_role in response_engine report_generator api; do
    vault write "database/roles/${db_role}" \
        db_name=sentinelops-postgres \
        creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}' IN ROLE \"${db_role}\";" \
        revocation_statements="REASSIGN OWNED BY \"{{name}}\" TO \"${db_role}\"; DROP OWNED BY \"{{name}}\"; DROP ROLE IF EXISTS \"{{name}}\";" \
        default_ttl="1h" \
        max_ttl="1h"
done

for svc in "${SERVICES[@]}"; do
    role_name="${svc//-/_}"

    if [[ "$svc" == "webhook-handler" || "$svc" == "worker" || "$svc" == "maintenance-monitor" ]]; then
        db_role="response_engine"
    elif [[ "$svc" == "report-generator" ]]; then
        db_role="report_generator"
    elif [[ "$svc" == "api" ]]; then
        db_role="api"
    else
        db_role=""
    fi

    policy_hcl=""
    [[ -n "$db_role" ]] && policy_hcl="path \"database/creds/${db_role}\" { capabilities = [\"read\"] }"
    [[ "$svc" == "grafana" ]] && policy_hcl="${policy_hcl}
path \"secret/data/sentinelops/grafana\" { capabilities = [\"read\"] }"

    echo "$policy_hcl" | vault policy write "${role_name}-policy" -

    # token_max_ttl=4h with secret_id_num_uses unlimited (default): Vault Agent can re-auth after forced token expiry using the same baked-in secret_id.
    vault write "auth/approle/role/${role_name}" \
        token_policies="${role_name}-policy" \
        token_ttl=1h \
        token_max_ttl=4h

    echo "Role ID and Secret ID for ${svc}:"
    vault read -field=role_id "auth/approle/role/${role_name}/role-id"
    echo
    vault write -field=secret_id -f "auth/approle/role/${role_name}/secret-id"
    echo
done


echo "Vault bootstrap complete."
