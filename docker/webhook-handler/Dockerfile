FROM python:3.14-alpine

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/webhook-handler/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY automation/response_engine/ /app/response_engine/
COPY cmdb/ /app/cmdb/

RUN apk add --no-cache curl unzip && \
    curl -fsSL -o /tmp/vault.zip https://releases.hashicorp.com/vault/2.1.1/vault_2.1.1_linux_amd64.zip && \
    unzip /tmp/vault.zip -d /usr/local/bin && \
    rm /tmp/vault.zip && \
    apk del curl unzip

COPY docker/vault/agent/webhook-handler-agent.hcl /vault/agent/webhook-handler-agent.hcl
COPY docker/vault/agent/roleids/webhook-handler/role-id /vault/agent/roleids/role-id
COPY docker/vault/agent/roleids/webhook-handler/secret-id /vault/agent/roleids/secret-id

ENTRYPOINT ["vault", "agent", "-config=/vault/agent/webhook-handler-agent.hcl"]
