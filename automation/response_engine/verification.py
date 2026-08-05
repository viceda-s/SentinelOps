import logging

import requests
from docker.errors import APIError, NotFound

logger = logging.getLogger(__name__)

def verify_recovery(client, container_name: str, verification: dict) -> bool:
    """
    Perform a single recovery verification

    Returns:
        True if recovery succeeded.

        False if the service is reachable but unhealthy (including HTTP/network failures).

    Raises:
        docker.errors.NotFound:
            The target container could not be found at the time of verification.

        docker.errors.APIError:
            Docker verification failures (for example, container lookup failures) are propagated to the caller.
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

    if verification["type"] == "http":
        try:
            response = requests.get(verification["url"], timeout=5)
        except requests.exceptions.RequestException:
            return False
        return response.status_code == 200

    #
    # validate_cmdb.py should prevent this ever happening
    #

    raise ValueError(
        f"Unknown verification type: {verification_type}"
    )
