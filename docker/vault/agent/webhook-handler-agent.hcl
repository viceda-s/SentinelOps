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

env_template "RESPONSE_ENGINE_DB_USER" {
  contents = "{{ with secret \"database/creds/response_engine\" }}{{ .Data.username }}{{ end }}"
}

env_template "RESPONSE_ENGINE_DB_PASSWORD" {
  contents = "{{ with secret \"database/creds/response_engine\" }}{{ .Data.password }}{{ end }}"
}

exec {
  command                   = ["gunicorn", "--bind", "0.0.0.0:8000", "response_engine.webhook_handler:app"]
  restart_on_secret_changes = "always"
  restart_stop_signal       = "SIGTERM"
}
