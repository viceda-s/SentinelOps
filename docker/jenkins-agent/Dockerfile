FROM node:22-slim AS node

FROM jenkins/inbound-agent:3391.va_37fa_a_305d6d-3-jdk21

USER root

# Installs the Docker CLI (not the daemon -- reached via the socket bind in docker-compose.yml) plus docker-compose-plugin, so `docker`/`docker compose` work in pipeline steps on this agent.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc && \
    chmod a+r /etc/apt/keyrings/docker.asc && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin && \
    rm -rf /var/lib/apt/lists/*

# Python toolchain for pytest/ruff/yamllint (installed into a venv per-build by the Jenkinsfile, since requirements-dev.txt changes independently of this image), shellcheck for the Config & Static Validation stage, and psql for init_test_db.sh -- none of these ship on this minimal Debian base, unlike GitHub Actions' ubuntu-latest runner.
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-venv shellcheck postgresql-client && \
    rm -rf /var/lib/apt/lists/*

# Node.js for the pinned release-please CLI below, copied from the official image -- NodeSource's install script failed intermittently with npm network errors in this build context.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx && \
    npm install -g release-please@17.11.2

# The bound socket's GID varies by host platform (Docker Desktop often presents GID 0/root) -- join whichever group already owns that GID, or create one if none does, so this Dockerfile works unmodified on any machine.
ARG DOCKER_GID
RUN if getent group "${DOCKER_GID}" > /dev/null 2>&1; then \
        usermod -aG "$(getent group "${DOCKER_GID}" | cut -d: -f1)" jenkins; \
    else \
        groupadd -g "${DOCKER_GID}" hostdocker && usermod -aG hostdocker jenkins; \
    fi

USER jenkins

# Bind-mounted workspaces are owned by the host user's UID, which git (as the jenkins user) refuses to touch without this (CVE-2022-24765) -- must run after the USER switch above, or it'd configure root instead.
RUN git config --global --add safe.directory '*'
