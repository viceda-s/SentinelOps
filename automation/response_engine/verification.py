import logging

import requests
from docker.errors import APIError, NotFound

logger = logging.getLogger(__name__)

def verify_recovery(client, container_name: str, verification: dict) -> bool:
    """
    Perform a single recovery verification

    Returns:
        True if the service currently satisfies its configured verification strategy, otherwise False

    Raises:
        docker.errors.NotFound:
            The configured container does not exist.
        docker.errors.APIError:
            Docker Engine communication failed.
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
        health = (container.attrs.get("State", {}).get("Health"))

        #
        # CMDB says this container should expose a HEALTHCHECK, but it doesn't. Treat as verification failure rather than crashing the worker.
        #

        if health is None:
            logger.warning(
                "Container has no Docker HEALTHCHECK",
                extra={
                    "container": container_name
                },
            )
            return False
        return health.get("Status") == "healthy"

    if verification_type == "http":
        response = requests.get(verification["url"], timeout=5)
        return response.status_code == 200

    #
    # validate_cmdb.py should prevent this ever happening
    #

    raise ValueError(
        f"Unknown verification type: {verification_type}"
    )
