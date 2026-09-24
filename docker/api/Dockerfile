FROM python:3.14-alpine

WORKDIR /app

COPY docker/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY docker/api/app/ .

RUN apk add --no-cache curl unzip && \
    curl -fsSL -o /tmp/vault.zip https://releases.hashicorp.com/vault/2.1.1/vault_2.1.1_linux_amd64.zip && \
    unzip /tmp/vault.zip -d /usr/local/bin && \
    rm /tmp/vault.zip && \
    apk del curl unzip

COPY docker/vault/agent/api-agent.hcl /vault/agent/api-agent.hcl
COPY docker/vault/agent/roleids/api/role-id /vault/agent/roleids/role-id
COPY docker/vault/agent/roleids/api/secret-id /vault/agent/roleids/secret-id

EXPOSE 5000

HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"

ENTRYPOINT ["vault", "agent", "-config=/vault/agent/api-agent.hcl"]
