FROM grafana/grafana:11.2.0

USER root

RUN curl -fsSL -o /tmp/vault.zip https://releases.hashicorp.com/vault/2.1.1/vault_2.1.1_linux_amd64.zip && \
    unzip /tmp/vault.zip -d /usr/local/bin && \
    rm /tmp/vault.zip

COPY docker/vault/agent/grafana-agent.hcl /vault/agent/grafana-agent.hcl
COPY docker/vault/agent/roleids/grafana/role-id /vault/agent/roleids/role-id
COPY docker/vault/agent/roleids/grafana/secret-id /vault/agent/roleids/secret-id

USER 472

ENTRYPOINT ["vault", "agent", "-config=/vault/agent/grafana-agent.hcl"]
