from __future__ import annotations

#
# Playbooks implemented by the remediation worker.
#
# This module is intentionally dependency-free so tools such as validate_cmdb.py can import it without pulling in the Docker SDK or other runtime dependencies.
#

IMPLEMENTED_PLAYBOOKS = frozenset(
    {
        "restart_service",
        "collect_diagnostics",
    }
)
