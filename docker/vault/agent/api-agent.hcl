pid_file = "/tmp/vault-agent.pid"

vault {
  address = "http://vault:8200"
}

auto_auth {
  method "approle" {
    mount_path = "auth/approle"
    config = {
      role_id_file_path   = "/vault/agent/roleids/role-id"
      secret_id_file_path = "/vault/agent/roleids/secret-id"
    }
  }

  sink "file" {
    config = {
      path = "/tmp/vault-agent-token"
    }
  }
}

env_template "API_DB_USER" {
  contents = "{{ with secret \"database/creds/api\" }}{{ .Data.username }}{{ end }}"
}

env_template "API_DB_PASSWORD" {
  contents = "{{ with secret \"database/creds/api\" }}{{ .Data.password }}{{ end }}"
}

exec {
  command                   = ["gunicorn", "--bind", "0.0.0.0:5000", "main:app"]
  restart_on_secret_changes = "always"
  restart_stop_signal       = "SIGTERM"
}
