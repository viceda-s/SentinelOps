"""
CMDB loader module for SentinelOps.

Loads and parses service definitions, ownership, SLA targets, and playbook mappings
from the YAML configuration file on disk.
"""

from __future__ import annotations

import os

import yaml


def load_cmdb() -> dict:
    """
    Load and parse the SentinelOps Configuration Management Database (CMDB).

    Reads from the path specified by the `CMDB_PATH` environment variable, falling back
    to `/app/cmdb/services.yaml`.

    Returns:
        dict: Parsed CMDB configuration mapping service keys to operational metadata.

    Raises:
        FileNotFoundError: If the CMDB configuration file cannot be found.
        yaml.YAMLError: If the CMDB file contains invalid YAML.
    """

    cmdb_path = os.environ.get("CMDB_PATH", "/app/cmdb/services.yaml")

    with open(cmdb_path, encoding="utf-8") as f:
        return yaml.safe_load(f)
