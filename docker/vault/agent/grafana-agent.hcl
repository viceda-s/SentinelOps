pid_file = "/tmp/vault-agent.pid"

vault {
  address = "http://vault:8200"
}

auto_auth {
  method "approle" {
    mount_path = "auth/approle"
    config = {
      role_id_file_path                   = "/vault/agent/roleids/role-id"
      secret_id_file_path                 = "/vault/agent/roleids/secret-id"
      remove_secret_id_file_after_reading = false
    }
  }

  sink "file" {
    config = {
      path = "/tmp/vault-agent-token"
    }
  }
}

env_template "GF_SECURITY_ADMIN_PASSWORD" {
  contents = "{{ with secret \"secret/data/sentinelops/grafana\" }}{{ .Data.data.admin_password }}{{ end }}"
}

exec {
  command                   = ["/run.sh"]  # TODO(Task 6): confirm via docker inspect grafana/grafana:11.2.0 --format '{{.Config.Entrypoint}}'
  restart_on_secret_changes = "always"
  restart_stop_signal       = "SIGTERM"
}
