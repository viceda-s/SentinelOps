# ADR-008: Autonomous remediation with bounded verification

**Status:** Accepted

## Context

Once an incident reaches `IN_PROGRESS`, the remediation worker executes the configured playbook (`restart_service` or `collect_diagnostics` in `automation/response_engine/remediation.py`) without waiting for human intervention.

Autonomous remediation requires more than issuing a restart command: the worker must determine whether the service actually recovered. It also needs a clear point at which automated recovery stops and the incident is escalated to a human operator instead of retrying indefinitely.

The response engine must also support different verification mechanisms, since not every managed service exposes the same health signal.

## Decision

`restart_service()` restarts the target container and verifies recovery within a bounded polling window rather than declaring success immediately or waiting indefinitely.

The verification behaviour is controlled by four constants:

* `VERIFY_TIMEOUT = 30` seconds — default time allowed for a verification attempt. For `docker-health` verification, `_verify_timeout_for()` extends this per attempt to cover the target container's own `HEALTHCHECK` interval and timeout (plus a fixed margin), up to a hard ceiling of `HEALTHCHECK_VERIFY_MAX = 60` seconds — see Consequences.
* `VERIFY_INTERVAL = 1` second — interval between verification checks.
* `RESTART_COOLDOWN = 5` seconds — delay before a subsequent restart attempt.
* `MAX_RESTART_ATTEMPTS = 2` — maximum restart attempts before escalating the incident.

Recovery verification is implemented by `automation/response_engine/verification.py` and selected per service through the CMDB's `verification.type` field.

Three verification strategies are supported:

* **`http`** — performs an HTTP GET against the configured health endpoint. Any non-200 response or request exception is treated as a failed verification.
* **`docker-health`** — reads Docker's existing `HEALTHCHECK` status from `container.attrs["State"]["Health"]["Status"]`.
* **`running`** — verifies only that the container is in the `running` state, for services that expose no stronger health signal.

Each remediation attempt records its start and finish timestamps using `clock_timestamp()` rather than `NOW()`, ensuring recorded durations reflect real elapsed wall-clock time even though the remediation executes within a single database transaction.

If verification does not succeed within the configured retry budget, the incident transitions to `ESCALATED` for human intervention.

## Alternatives considered

* **Restart and immediately declare success.** Rejected because issuing a restart command does not guarantee the service has recovered, leading to inaccurate incident resolution.

* **Retry indefinitely until recovery.** Rejected because a permanently broken service could occupy the worker forever instead of being escalated.

* **Perform a single verification immediately after restart.** Rejected because most services require time to become operational after restarting, making an immediate one-shot check prone to false negatives.

## Consequences

* Remediation is autonomous but time-bounded: the worker will not resolve an incident unless recovery can be verified, and it will not retry indefinitely if recovery never occurs.
* Verification quality depends on the configured strategy for each service. `http` provides the strongest guarantee because it performs a fresh request, while `running` provides only a basic liveness check.
* The `docker-health` strategy reads Docker's cached `HEALTHCHECK` status rather than initiating a new health probe. Consequently, verification freshness is determined by the monitored container's own `HEALTHCHECK` interval, not by `VERIFY_INTERVAL`. A fixed `VERIFY_TIMEOUT` shorter than that interval could previously make a genuinely recovering container escalate before its first post-restart probe ever landed (see issue #59); `_verify_timeout_for()` now sizes the deadline off the container's own `Config.Healthcheck`, capped at `HEALTHCHECK_VERIFY_MAX`. Containers whose healthcheck interval, timeout, and `start_period` sum past that cap can still escalate spuriously — this is a bounded mitigation, not a general solution. Issue #43 (`RemediationSettings` / per-service CMDB verification timing) is the planned general fix and would supersede this constant-derivation approach.
* Recording remediation attempts with `clock_timestamp()` preserves accurate wall-clock durations even though an entire remediation attempt executes within a single database transaction.
