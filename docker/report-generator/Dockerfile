FROM python:3.14-alpine

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/report-generator/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Keep the package structure intact so the module can be executed as:
#   python -m automation.report_generator.report_generator
COPY automation ./automation

# Report generation consumes the shared CMDB.
COPY cmdb ./cmdb

RUN apk add --no-cache curl unzip && \
    curl -fsSL -o /tmp/vault.zip https://releases.hashicorp.com/vault/2.1.1/vault_2.1.1_linux_amd64.zip && \
    unzip /tmp/vault.zip -d /usr/local/bin && \
    rm /tmp/vault.zip && \
    apk del curl unzip

COPY docker/vault/agent/report-generator-agent.hcl /vault/agent/report-generator-agent.hcl
COPY docker/vault/agent/roleids/report-generator/role-id /vault/agent/roleids/role-id
COPY docker/vault/agent/roleids/report-generator/secret-id /vault/agent/roleids/secret-id

ENTRYPOINT ["vault", "agent", "-config=/vault/agent/report-generator-agent.hcl"]
