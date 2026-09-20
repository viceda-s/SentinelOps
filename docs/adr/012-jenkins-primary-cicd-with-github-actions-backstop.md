# ADR-012: Jenkins as the primary CI/CD pipeline, with GitHub Actions retained as a public backstop

**Status:** Accepted

## Context

Phase 3 already shipped a working GitHub Actions pipeline (`.github/workflows/quality-gate.yml`, issue #23): lint, format, pytest against an ephemeral Postgres service container, shellcheck, yamllint, compose build validation, and a manually-gated E2E chaos job.

Separately, the person maintaining this repo has professional exposure to Jenkins-based CI/CD ahead of an internship, and this repo's existing multi-service, already-functional pipeline is a more realistic vehicle for deliberate Jenkins practice than a toy project. The decision below is therefore driven by a practice/ownership goal as much as an engineering one, and this ADR records that honestly rather than presenting Jenkins as strictly technically necessary.

## Decision

Jenkins becomes the primary, required CI/CD system. It covers the full gate: config validation, build/test with coverage, a SonarQube Cloud quality gate, first-party container builds, a Trivy vulnerability scan of those images, and a manually-triggered E2E chaos suite. GitHub Actions is not removed — `quality-gate.yml` is slimmed to a lint-and-unit-test-only job and kept as an always-on, non-required backstop.

### Why replace-as-primary rather than run both at equal weight

Practicing end-to-end pipeline ownership — including real GitHub PR integration, not just isolated build stages — is the internship-relevant skill. Running Jenkins as a second, lower-stakes system alongside a fully-weighted GitHub Actions pipeline would not exercise that ownership; the full gate needed to live in Jenkins for the exercise to be real.

### Trade-off: losing free hosted CI and native PR-check visibility

GitHub Actions runs on GitHub's own infrastructure — a public-repo visitor sees CI results with zero operational dependency on the maintainer's machine. A local Jenkins controller (run via Docker Compose) only posts status while the machine and its GitHub-webhook tunnel are both up. This is mitigated two ways:

1. `quality-gate.yml` is kept, not deleted, reduced to lint+unit-tests only, so the repo always shows some always-on CI signal.
2. The SonarQube Cloud quality gate stage (run only in Jenkins) publishes a public quality badge, partially offsetting the loss of always-visible GitHub Actions checks.

### Trade-off: two status checks with different scope, and how merges are gated

Once both pipelines post statuses, a PR shows two independent checks that can disagree, since GitHub Actions covers only lint+tests while Jenkins covers the full gate. Branch protection on `main` (a repository ruleset, not classic branch protection) marks **only** `continuous-integration/jenkins/pr-head` as a required status check; `Lint & Unit Tests` and `SonarCloud Code Analysis` remain present but not required. This is a deliberate choice, not an oversight: Jenkins is the pipeline of record, and requiring both would create ambiguity about which failure actually blocks a merge.

### Trade-off: Docker build-agent socket access, reconciled against existing hardening plans

`ROADMAP.md`'s Post-v1 section already commits to replacing the `worker` service's raw `/var/run/docker.sock` mount with a restricted API proxy. `README.md`'s Security Considerations section explains why: the worker is the only externally-influenced service with Docker Engine access, and that access is deliberately not extended to the webhook handler, to minimize privilege exposed to externally reachable components.

The Jenkins build agent (`jenkins-agent`) also binds the host Docker socket, to build and Trivy-scan the four first-party images. This is treated as a **build-time, operator-controlled** concern, not a **runtime, externally-reachable** one: the agent runs no application code, is not reachable from outside the Jenkins controller's own network, and is only ever invoked by pipeline runs the maintainer (or, once webhook-triggered, GitHub events the maintainer's own PRs generate) controls — the same trust tier as the person running `docker compose up` locally. This is a different risk profile from the `worker`'s actual threat model (a process reacting to externally-delivered Alertmanager webhooks with Docker access), and is not assumed solved by the same future socket-proxy work. If the Post-v1 socket-proxy item is implemented for the `worker`, the Jenkins agent's socket access should be re-evaluated for the same treatment rather than assumed exempt indefinitely.

Docker-in-Docker was considered and rejected as the default: it trades a host-socket mount for a privileged container, which is not a strict security improvement, and adds image-layer-caching complexity with no offsetting benefit for a dev-only local agent.

### Trade-off: `jenkins`/`jenkins-agent` share `docker-compose.yml` and a Compose project with the local dev stack

`jenkins-agent` runs `docker compose` commands against the host's Docker daemon (via the bound socket) from inside pipeline steps — a Docker-outside-of-Docker (DooD) pattern. Making those commands resolve relative bind-mount paths and reach sibling services (e.g. `postgres`) correctly required pinning `COMPOSE_PROJECT_NAME=sentinelops`, matching the project name the maintainer's own local `docker compose up` already uses. The consequence is that CI runs and the local dev stack share container names and the `postgres_data` volume; both `bootstrap.sh` (via a new `app_services()` helper) and every pipeline cleanup step are scoped to exclude `jenkins`/`jenkins-agent` and avoid `-v`/`--remove-orphans`, so a CI run cannot tear down the Jenkins containers running it or delete the maintainer's local database. The accepted residual risk is that the local dev stack and a Jenkins build must not run simultaneously against the same project, since they would otherwise contend for the same containers.

### Implementation notes that shaped the final pipeline

A few details only became clear during implementation and are recorded here since they affect how the pipeline should be read or extended:

* The four first-party images (`api`, `webhook-handler`, `worker`, `report-generator`) were moved from `python:3.14-slim` (Debian) to `python:3.14-alpine`, clearing 44 HIGH-severity, upstream-unpatched `util-linux`/`libmount`/`libacl` CVEs that Trivy flagged in the Debian base layer. Two remaining findings (`GHSA-6v7p-g79w-8964`, `CVE-2025-47273`) live inside `pip`'s own vendored/license-metadata files in the official Alpine base image, are never imported by application code, and are documented and excluded via `.trivyignore` rather than chased with base-image changes that don't reach them.
* Trivy's vulnerability database is cached in a named Docker volume (`trivy-cache`) mounted into each scan's container, since the default no-cache behavior re-downloaded the ~115MB database on every one of the four per-image scans and made the stage unnecessarily exposed to transient network failures.
* `docker compose up -d postgres` returns once the container starts, not once Postgres accepts connections; the `Build & Test` stage uses `--wait` (backed by the service's existing `pg_isready` healthcheck) to close a real, observed race against `init_test_db.sh`.
* The GitHub webhook relay (`smee-client`) has a version-specific bug: v5's `undici`-based fetch forwards a `sec-fetch-mode` header as a literal CORS `mode` option, which triggers a browser-style `OPTIONS` preflight that Jenkins's webhook endpoint (no CORS handling) rejects with 405. `smee-client@2` does not exhibit this and is the version actually run.

## Alternatives considered

* **Run Jenkins and GitHub Actions at equal weight, both required.** Rejected per the "why replace-as-primary" reasoning above — it would not exercise real pipeline ownership and would leave merges gated on two independently-authoritative signals with no tie-breaking rule.
* **Delete GitHub Actions entirely.** Rejected because the public repository would then show no CI signal at all whenever the maintainer's machine or webhook tunnel is down, which is worse than a deliberately thin backstop.
* **Docker-in-Docker for the Jenkins build agent instead of a host-socket bind.** Rejected: trades one privilege-exposure model for another (a privileged container) without a net security improvement, while adding layer-caching complexity a dev-only local agent doesn't need.

## Consequences

* Jenkins (`docker-compose.yml`'s `jenkins` + `jenkins-agent` services, `Jenkinsfile`) is the pipeline of record; `.github/workflows/quality-gate.yml` is a thin, non-required backstop.
* A smee.io tunnel (`smee-client@2`, not the current v5 default) and a running Jenkins stack are both required for real-time PR status checks; if either is down, only the GitHub Actions backstop check reports.
* The `jenkins-agent` service's Docker socket bind is a scoped, documented exception to the Post-v1 socket-hardening direction, not an oversight.
* CI and the local dev stack share a Compose project name and its `postgres_data` volume; both must be treated as mutually exclusive at any given time, and any new `docker compose` command added to `bootstrap.sh` or the `Jenkinsfile` must account for `jenkins`/`jenkins-agent` living in the same compose file.
