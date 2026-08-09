"""
Recovery verification module for SentinelOps.

Executes CMDB-driven verification strategies (`http`, `docker-health`, `running`) to determine
whether a container service has recovered following remediation playbook execution.
"""

import logging

import requests

logger = logging.getLogger(__name__)


def verify_recovery(client, container_name: str, verification: dict) -> bool:
    """
    Perform a single recovery verification check according to CMDB policy.

    Args:
        client: Docker SDK client instance.
        container_name: Name of target container to verify.
        verification: CMDB dictionary specifying `type` ('http', 'docker-health', 'running')
            and parameters (such as `url` for HTTP checks).

    Returns:
        bool: True if service recovery is verified; False if verification failed or is unreachable.

    Raises:
        docker.errors.NotFound: If the container does not exist.
        docker.errors.APIError: If communication with Docker daemon fails.
        ValueError: If an unrecognized verification type is provided.
    """

    verification_type = verification["type"]

    #
    # Always inspect fresh state
    #

    container = client.containers.get(container_name)
    container.reload()

    if verification_type == "running":
        return container.status == "running"

    if verification_type == "docker-health":
        health = container.attrs.get("State", {}).get("Health")

        #
        # CMDB says this container should expose a HEALTHCHECK, but it doesn't. Treat as verification failure rather than crashing the worker.
        #

        if health is None:
            logger.warning(
                "Container has no Docker HEALTHCHECK",
                extra={"container": container_name},
            )
            return False
        return health.get("Status") == "healthy"

    if verification["type"] == "http":
        try:
            response = requests.get(verification["url"], timeout=5)
        except requests.exceptions.RequestException:
            return False
        return response.status_code == 200

    #
    # validate_cmdb.py should prevent this ever happening
    #

    raise ValueError(f"Unknown verification type: {verification_type}")
