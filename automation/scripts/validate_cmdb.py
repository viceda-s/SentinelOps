#!/usr/bin/env python3
"""Check cmdb/services.yaml against what the rest of the project expects.

Called by bootstrap.sh --validate-only. Can also be run on its own:

    python3 automation/scripts/validate_cmdb.py

Collects every problem it finds and prints them all before exiting, rather than
stopping at the first one.
"""

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CMDB_PATH = REPO_ROOT / "cmdb" / "services.yaml"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"

REQUIRED_KEYS = (
    "container_name",
    "owner",
    "tier",
    "criticality",
    "runbook",
    "sla",
)
REQUIRED_SLA_KEYS = ("response_minutes", "resolution_minutes")

# TODO: once the playbooks are their own files under
# automation/response_engine/playbooks/, read the directory instead of keeping
# this list in step with the worker by hand.
KNOWN_PLAYBOOKS = {
    "restart_service",
    "collect_diagnostics",
    "disk_cleanup",
    "none",
}

VALID_CRITICALITY = {"high", "medium", "low"}


class CmdbError(Exception):
    """The CMDB can't be loaded at all, so there's nothing to validate."""


class DuplicateKeyError(CmdbError):
    pass


class StrictLoader(yaml.SafeLoader):
    """yaml.safe_load keeps the last duplicate key and says nothing about it.

    A service defined twice would silently lose its first definition, so catch
    it here instead.
    """


def no_duplicates(loader: yaml.Loader, node: yaml.Node, deep: bool = False) -> dict:
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise DuplicateKeyError(f"duplicate key: {key}")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, no_duplicates
)


def load_cmdb() -> dict:
    """Parse the CMDB, or raise CmdbError if it isn't usable."""
    if not CMDB_PATH.exists():
        raise CmdbError(f"{CMDB_PATH} does not exist")

    try:
        cmdb = yaml.load(CMDB_PATH.read_text(), Loader=StrictLoader) or {}
    except DuplicateKeyError:
        raise
    except yaml.YAMLError as e:
        raise CmdbError(f"not valid YAML: {e}") from e

    if "services" not in cmdb:
        raise CmdbError("no 'services' key")

    return cmdb


def load_compose_services() -> set[str] | None:
    """Service and container names from docker-compose.yml.

    Returns None if there's no compose file yet, so the check can be skipped
    rather than reported as a failure.
    """
    if not COMPOSE_PATH.exists():
        return None

    compose = yaml.safe_load(COMPOSE_PATH.read_text()) or {}
    names = set()
    for name, body in (compose.get("services") or {}).items():
        names.add(name)
        if isinstance(body, dict) and "container_name" in body:
            names.add(body["container_name"])
    return names


def validate(cmdb: dict) -> list[str]:
    errors: list[str] = []
    services = cmdb["services"] or {}
    compose_services = load_compose_services()

    for name, svc in services.items():
        if not isinstance(svc, dict):
            errors.append(f"[{name}] expected a mapping")
            continue

        for key in REQUIRED_KEYS:
            if key not in svc:
                errors.append(f"[{name}] missing '{key}'")

        crit = svc.get("criticality")
        if crit is not None and crit not in VALID_CRITICALITY:
            errors.append(
                f"[{name}] criticality '{crit}' should be one of "
                f"{', '.join(sorted(VALID_CRITICALITY))}"
            )

        runbook = svc.get("runbook")
        if runbook and not (REPO_ROOT / runbook).exists():
            errors.append(f"[{name}] runbook '{runbook}' does not exist")

        sla = svc.get("sla")
        if isinstance(sla, dict):
            for key in REQUIRED_SLA_KEYS:
                if key not in sla:
                    errors.append(f"[{name}] sla is missing '{key}'")
                elif not isinstance(sla[key], int):
                    errors.append(f"[{name}] sla.{key} should be a number")
        elif sla is not None:
            errors.append(f"[{name}] sla should be a mapping")

        playbooks = svc.get("playbooks") or {}
        if isinstance(playbooks, dict):
            for alert, playbook in playbooks.items():
                if playbook not in KNOWN_PLAYBOOKS:
                    errors.append(
                        f"[{name}] alert '{alert}' maps to unknown playbook "
                        f"'{playbook}'"
                    )
        else:
            errors.append(f"[{name}] playbooks should be a mapping")

        container = svc.get("container_name")
        if (
            container
            and compose_services is not None
            and container not in compose_services
        ):
            errors.append(
                f"[{name}] container_name '{container}' is not in docker-compose.yml"
            )

        # TODO: detect dependency cycles. Two services depending on each other
        # parses fine but means neither can be brought up first.
        for dep in svc.get("dependencies") or []:
            if dep not in services:
                errors.append(f"[{name}] dependency '{dep}' is not in the cmdb")

    return errors


def main() -> None:
    try:
        cmdb = load_cmdb()
    except CmdbError as e:
        print("CMDB validation failed:")
        print(f"  [cmdb] {e}")
        sys.exit(1)

    errors = validate(cmdb)
    if errors:
        print(f"CMDB validation failed ({len(errors)} problem(s)):")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)

    print(f"CMDB OK ({len(cmdb['services'])} services)")


if __name__ == "__main__":
    main()
