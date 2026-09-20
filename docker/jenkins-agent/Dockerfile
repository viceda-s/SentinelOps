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

# The bound socket's GID varies by host platform (Docker Desktop often presents GID 0/root) -- join whichever group already owns that GID, or create one if none does, so this Dockerfile works unmodified on any machine.
ARG DOCKER_GID
RUN if getent group "${DOCKER_GID}" > /dev/null 2>&1; then \
        usermod -aG "$(getent group "${DOCKER_GID}" | cut -d: -f1)" jenkins; \
    else \
        groupadd -g "${DOCKER_GID}" hostdocker && usermod -aG hostdocker jenkins; \
    fi

USER jenkins