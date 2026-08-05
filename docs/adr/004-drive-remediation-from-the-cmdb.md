# ADR-004: Drive remediation from the CMDB

**Status:** Accepted

## Context

The response engine must decide how to remediate an incident after receiving an Alertmanager notification. Hard-coding remediation logic into alert rules or application code would tightly couple operational policy to implementation, making changes require code modifications and redeployment.

The system also needs a single authoritative place to describe operational metadata about each managed service, including ownership, criticality, and the appropriate remediation playbooks for the alerts that service can generate.

## Decision

Use a Configuration Management Database (CMDB) as the source of operational metadata for managed services.

Each service is represented by a single entry in `cmdb/services.yaml`, containing information such as:

- service name
- owner
- criticality
- verification strategy
- remediation playbooks (mapped by alert name)
- service-level objectives
- dependencies

When an alert is received, the webhook handler resolves the affected service against the CMDB before creating an incident. If the service is unknown, or no remediation playbook is configured for the alert, the incident is escalated immediately rather than entering the remediation queue. Only incidents with a valid playbook are dispatched to the worker for automated remediation.

The worker executes the playbook recorded on the incident rather than making service-specific decisions itself. Supported playbook names are validated against the playbook registry during CMDB validation, which is run by `bootstrap.sh`, ensuring configuration errors are detected before the response engine starts.

## Alternatives considered

- **Hard-coded service logic.** Rejected because adding or changing a service would require modifying application code instead of configuration.

- **Encoding remediation in Prometheus or Alertmanager configuration.** Rejected because monitoring configuration should describe detection, not operational policy. Coupling remediation to alert definitions would make the monitoring stack responsible for application behaviour.

- **Separate configuration files for ownership, verification, and remediation.** Rejected because operational metadata would become fragmented, increasing the risk of inconsistencies between related configuration.

## Consequences

- Adding a new managed service is primarily a configuration change rather than an application change.
- Operational metadata is defined in a single authoritative location.
- Remediation behaviour can be changed by updating CMDB configuration without modifying response-engine code.
- Invalid playbook references are detected during validation rather than at incident time.
- The response engine remains generic: it executes configured playbooks without containing service-specific remediation logic.
