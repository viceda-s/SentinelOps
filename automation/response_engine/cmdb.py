"""
CMDB loader module for SentinelOps.

Loads and parses service definitions, ownership, SLA targets, and playbook mappings
from the YAML configuration file on disk.
"""

from __future__ import annotations

import yaml

from .config import CMDBSettings


def load_cmdb(settings: CMDBSettings | None = None) -> dict:
    """
    Load and parse the SentinelOps Configuration Management Database (CMDB).

    Reads from the path specified by CMDBSettings.

    Returns:
        dict: Parsed CMDB configuration mapping service keys to operational metadata.

    Raises:
        FileNotFoundError: If the CMDB configuration file cannot be found.
        yaml.YAMLError: If the CMDB file contains invalid YAML.
    """
    if settings is None:
        settings = CMDBSettings.from_env()

    with open(settings.path, encoding="utf-8") as f:
        return yaml.safe_load(f)
