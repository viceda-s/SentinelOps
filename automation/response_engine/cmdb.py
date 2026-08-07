from __future__ import annotations

import os

import yaml


def load_cmdb() -> dict:
    """
    Load the SentinelOps CMDB.

    Reads from the CMDB_PATH environment variable, falling back to the container's default mount point.
    """

    cmdb_path = os.environ.get("CMDB_PATH", "/app/cmdb/services.yaml")

    with open(cmdb_path, encoding="utf-8") as f:
        return yaml.safe_load(f)
