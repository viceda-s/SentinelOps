from __future__ import annotations

#
# Playbooks implemented by the remediation worker.
#
# "none" is a valid CMDB playbook value meaning "no automated remediation"; it is intentionally excluded from this set because the worker never executes it. validate_cmdb.py accepts it separately as IMPLEMENTED_PLAYBOOKS | {"none"}.
#

IMPLEMENTED_PLAYBOOKS = frozenset(
    {
        "restart_service",
        "collect_diagnostics",
    }
)
