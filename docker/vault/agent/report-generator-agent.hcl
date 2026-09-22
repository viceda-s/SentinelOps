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

env_template "REPORT_GENERATOR_DB_USER" {
  contents = "{{ with secret \"database/creds/report_generator\" }}{{ .Data.username }}{{ end }}"
}

env_template "REPORT_GENERATOR_DB_PASSWORD" {
  contents = "{{ with secret \"database/creds/report_generator\" }}{{ .Data.password }}{{ end }}"
}

exec {
  command                   = ["python", "-m", "automation.report_generator.report_generator"]
  restart_on_secret_changes = "always"
  restart_stop_signal       = "SIGTERM"
}
