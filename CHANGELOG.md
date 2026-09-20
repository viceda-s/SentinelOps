# Changelog

All notable changes to SentinelOps's design are recorded here. This
tracks changes to `docs/DESIGN.md`'s recorded decisions, not every commit
— see git history for full implementation detail.

## [1.4.0](https://github.com/viceda-s/SentinelOps/compare/v1.3.0...v1.4.0) (2026-09-20)


### Features

* add active maintenance windows tracking and update health page rendering ([5f40565](https://github.com/viceda-s/SentinelOps/commit/5f40565498f91ff7eba2de6830421bef9cb4b04f))
* add backup.sh with atomic archive creation and retention pruning ([2482aef](https://github.com/viceda-s/SentinelOps/commit/2482aef01809e5e7d8507a8a6a2b516e4f85df40))
* add chaos.sh fill/reset to trigger DiskPressure ([9a8f4b9](https://github.com/viceda-s/SentinelOps/commit/9a8f4b92015cde4e8ec9cae7efd24e15b1f1f1e8))
* add CLI script for closing incidents with root cause analysis ([91b6acf](https://github.com/viceda-s/SentinelOps/commit/91b6acfb23ec3c1758bc6e040f44f710bb1ba25e))
* add CMDB entries and alert rule for worker/webhook-handler self-monitoring ([3fd60aa](https://github.com/viceda-s/SentinelOps/commit/3fd60aadd39a68815da6491f7d1e6073f1c3a310))
* add details on new nginx routes for incident reports and response engine roles in Phase 2 ([fb5c3f7](https://github.com/viceda-s/SentinelOps/commit/fb5c3f74b953872f6fb71c2599df1b744eb09df1))
* add Dockerfile and requirements for report generator service ([80bcb18](https://github.com/viceda-s/SentinelOps/commit/80bcb18f181634ce47606511df42ad4a5cf5fbbb))
* add health page model, rendering logic, and associated HTML template ([4f57ca0](https://github.com/viceda-s/SentinelOps/commit/4f57ca0a656a35d161f6418a11689ab1f187f08e))
* add healthcheck.sh with layered state/functional probes, add nginx health endpoint ([fcd1718](https://github.com/viceda-s/SentinelOps/commit/fcd171849852605a83a67884869096b568194533))
* add live SLA breach detection ([e5dfe15](https://github.com/viceda-s/SentinelOps/commit/e5dfe15753708a5b8f6c7d5911a69af8a4f49cd1))
* add local pytest wrapper and fail-fast database configuration ([b830302](https://github.com/viceda-s/SentinelOps/commit/b830302b080128b5275b4b878643c647b6d1cd86))
* add maintenance monitor configuration and alerting rules ([01a7342](https://github.com/viceda-s/SentinelOps/commit/01a73427eaf6fa00f221fdfc4203f4e08b7f83da))
* add maintenance monitor service and update Dockerfiles to use Python 3.13 ([7a798b3](https://github.com/viceda-s/SentinelOps/commit/7a798b3c21eccadcfca058fc336e32d4de43a420))
* add maintenance script for managing maintenance windows and silences ([847bceb](https://github.com/viceda-s/SentinelOps/commit/847bceb66154ced60b62d471ab8b0d29e616c55c))
* add new metrics for suppressed alerts and maintenance heartbeat ([a07165e](https://github.com/viceda-s/SentinelOps/commit/a07165e9d27d11aee78d66e2ecb4e97bc0983038))
* add Prometheus metrics endpoint and corresponding test ([d223c39](https://github.com/viceda-s/SentinelOps/commit/d223c397182b3f290e061c6c7c23adab585f96be))
* add report model and associated tests for incident diagnostics ([ee569ba](https://github.com/viceda-s/SentinelOps/commit/ee569ba0244bd54ff8175c759d29c433c313c143))
* add SentinelOps — Response Engine Grafana dashboard ([7ac5e31](https://github.com/viceda-s/SentinelOps/commit/7ac5e3110962ef54b9985642cde5022f72145642))
* add shared Prometheus metrics module for the response engine ([1d77b32](https://github.com/viceda-s/SentinelOps/commit/1d77b32377969b0a98c73920ba582af61bf3a062))
* add silence_id column and partial unique index to incident_events ([431d4ee](https://github.com/viceda-s/SentinelOps/commit/431d4ee3ba8ef61513ef4b2070b75930ed9c2c50))
* add SQL-backed collectors for incident and queue-depth state metrics ([1915913](https://github.com/viceda-s/SentinelOps/commit/1915913ef4feecf9d26b1f1886501006ffc1048e))
* add tests for transitioning to and from suppressed maintenance state ([d598f25](https://github.com/viceda-s/SentinelOps/commit/d598f25eacd5092fe4f6b112daf036faa20758ea))
* add text escaping for special characters in PDF rendering and enhance tests for alert name and root cause analysis ([f7a071a](https://github.com/viceda-s/SentinelOps/commit/f7a071a4e10236df58aa13efaefc44bc4d57079a))
* allow record_note_event to record an Alertmanager silence id ([37c303d](https://github.com/viceda-s/SentinelOps/commit/37c303d2e2f0c0fb90fd01e6c279a31ff14cda21))
* **ci:** add gated E2E chaos stage and archive/report stage ([68b7daf](https://github.com/viceda-s/SentinelOps/commit/68b7daf9deede8301dc8dfb65e4522e3a94ed443))
* **ci:** add Jenkins controller and Docker-CLI-equipped build agent to compose stack ([465675d](https://github.com/viceda-s/SentinelOps/commit/465675d28c02fbf2025e0bfa2c84a8b0d0ec3080))
* **ci:** add JENKINS_AGENT_WORKDIR to .env.example and update docker-compose.yml for volume binding ([b8532fa](https://github.com/viceda-s/SentinelOps/commit/b8532faeead464454fe69b4bbaa4a036aeab6ccb))
* **ci:** add Jenkinsfile with config-validation and build-test stages ([a40b75b](https://github.com/viceda-s/SentinelOps/commit/a40b75b54b7d01c976cb9ef9a887653726b823d9))
* **ci:** add non-blocking Release Please stage gated to main ([1cdca87](https://github.com/viceda-s/SentinelOps/commit/1cdca87cf12bf18c06df927d28fe3561188c55f9))
* **ci:** add POSTGRES_HOST environment variable in Build & Test stage ([a619d57](https://github.com/viceda-s/SentinelOps/commit/a619d5768d39796bdd59744c76415dc6dd9de0fe))
* **ci:** add Release Please automation for versioning and changelog ([c3a4968](https://github.com/viceda-s/SentinelOps/commit/c3a496883afa1b9d99a7861fa47c5bec9d9c03bc))
* **ci:** add SonarQube Cloud quality gate, container build, and Trivy scan stages ([34923b4](https://github.com/viceda-s/SentinelOps/commit/34923b4baa167c73a41d72fb2496b2b37e2a60a5))
* **ci:** install Node.js and pinned release-please CLI on jenkins-agent ([94bc465](https://github.com/viceda-s/SentinelOps/commit/94bc465bb576f2ec51f6d70a12093ec56f896aed))
* **ci:** migrate to Jenkins as primary CI/CD pipeline ([f3ab65a](https://github.com/viceda-s/SentinelOps/commit/f3ab65a677065be1060e735a0563c258b114b6f3))
* **db:** add incident reporting roles and schema ([5059486](https://github.com/viceda-s/SentinelOps/commit/505948626e08250970630c2cd9f1154649237c9a))
* enhance health page severity handling and improve error logging in report generator ([90709e5](https://github.com/viceda-s/SentinelOps/commit/90709e50db8ea4843374f4af7e0c56fab526f158))
* enhance logging configuration to ensure multiple handler support and prevent duplicates ([44c288b](https://github.com/viceda-s/SentinelOps/commit/44c288bc8a887feb958de3f9f42fff84847b9225))
* enhance process_suppressed_alert to handle multiple silences and deduplicate notes ([f1c883b](https://github.com/viceda-s/SentinelOps/commit/f1c883bad7bdcaba472dcdc7c14a9070838f05c4))
* enhance Prometheus monitoring with new metrics and alert rules ([200b8c6](https://github.com/viceda-s/SentinelOps/commit/200b8c6f7139fe89793b20993e5dca83e749019c))
* implement close incident functionality with transaction handling and tests ([d1a553e](https://github.com/viceda-s/SentinelOps/commit/d1a553e45bfdef8bb87b1137ed292a890ddef124))
* implement CMDB loading and PostgreSQL connection functions ([5659c26](https://github.com/viceda-s/SentinelOps/commit/5659c2626faf53ab257294eb06947a4b1f6b6039))
* implement disk_cleanup playbook ([e00175a](https://github.com/viceda-s/SentinelOps/commit/e00175aecabec0ca92e3f4f73beda19c95a19356))
* implement ingest_alert function to create new incidents from alerts and enhance alert handling in handle_alert ([a84e3de](https://github.com/viceda-s/SentinelOps/commit/a84e3deb4b84ea56effa6dce0ae567d187692fdf))
* implement maintenance window handling with suppressed alerts processing and related tests ([acfa52a](https://github.com/viceda-s/SentinelOps/commit/acfa52a78c5990caf213c58f15ea3c46c75712f8))
* implement PDF report generation and associated formatting helpers ([5d88491](https://github.com/viceda-s/SentinelOps/commit/5d88491b279459efb2514b7e7161410baf019145))
* implement phase 2.1 architectural refactors including centralized configuration, monotonic event sequencing, and modularized alert processing. ([ad9c41d](https://github.com/viceda-s/SentinelOps/commit/ad9c41d1c5ee2fbb3149b5e6f5d6dc17eb07f625))
* implement record_note_event function and enhance incident processing logic ([13c2a0f](https://github.com/viceda-s/SentinelOps/commit/13c2a0fede4e04b6a8e66a8d2e588ad526dac045))
* implement report generator for incident reporting and health page refresh ([9ad39aa](https://github.com/viceda-s/SentinelOps/commit/9ad39aa5c2f420364d176b0a680f342ef8b9d5cd))
* implement severity ranking function and enhance health page incident handling; improve PDF rendering with text escaping ([267dece](https://github.com/viceda-s/SentinelOps/commit/267deced4604821f2e6f4ee2830c66d2ad36d98e))
* implement timeline generation for incident reporting ([744d185](https://github.com/viceda-s/SentinelOps/commit/744d1857e06542e0ed3b158238af8774ee62771e))
* implement transitions for SUPPRESSED_MAINTENANCE state and update tests ([bb6b521](https://github.com/viceda-s/SentinelOps/commit/bb6b521adb9a48db9eaacc75775ce9acb6a6e4ea))
* increment sentinelops_incidents_created_total on new incident creation ([318c9a2](https://github.com/viceda-s/SentinelOps/commit/318c9a2696d2254041d6b34eb564b856c00d7130))
* observe response/resolution duration histograms in transition() ([07f5566](https://github.com/viceda-s/SentinelOps/commit/07f556693cd062f8755a9c35c06f25d62749ade4))
* operational tooling — backup.sh, healthcheck.sh, disk_cleanup playbook ([006614e](https://github.com/viceda-s/SentinelOps/commit/006614ed73e849b79183529f4a95624396bed41c))
* register disk_cleanup in IMPLEMENTED_PLAYBOOKS ([2797f6f](https://github.com/viceda-s/SentinelOps/commit/2797f6f6d68ab38e93809579ebb0cbcfc30a0c13))
* **response-engine:** add correlation_id and execution_id tracing primitives ([#61](https://github.com/viceda-s/SentinelOps/issues/61)) ([9273b03](https://github.com/viceda-s/SentinelOps/commit/9273b038a06a7e4e8646ffa963b8fb0b715f4e7f))
* **tests:** add diagnostics collection tests for container not found and API errors ([3d2bdc4](https://github.com/viceda-s/SentinelOps/commit/3d2bdc44b1ad13f5085a4da1427512058f2414f2))
* update .gitignore to exclude health/index.html ([8b17acd](https://github.com/viceda-s/SentinelOps/commit/8b17acd1fb90c0768cbffc6dfba8093828a2b9b9))
* update database role creation script to use environment variables for passwords ([e6dba6f](https://github.com/viceda-s/SentinelOps/commit/e6dba6f4588c2e1339a301c5d6cf473180f71966))
* update docker-compose and nginx configuration for health reporting and add health page ([cc687fc](https://github.com/viceda-s/SentinelOps/commit/cc687fc1f86271df45e1bbcc39467a954c80f99d))
* update legend formats in Grafana dashboard for improved clarity ([0c8ac05](https://github.com/viceda-s/SentinelOps/commit/0c8ac058eeb5585d0df606e1aea6dc031a416314))
* update README to reflect completion of incident reporting and enhancements in Phase 2 ([e0f54dc](https://github.com/viceda-s/SentinelOps/commit/e0f54dc39dca21fdcb94d467c595c13f43932c99))
* wire disk_cleanup into worker dispatch, CMDB, and worker mounts ([30a7f4b](https://github.com/viceda-s/SentinelOps/commit/30a7f4bbc606dca78b6dd84b6d1566b3c1969a80))


### Bug Fixes

* add docstring to counter_value function for clarity ([3693f27](https://github.com/viceda-s/SentinelOps/commit/3693f2756c6da39571ac43642c6c56286b522503))
* add node-exporter, cadvisor, report-generator to healthcheck.sh ([9ebcacb](https://github.com/viceda-s/SentinelOps/commit/9ebcacbc3b76f4e9226293fc9b5009c428663e10))
* add shellcheck directive for .env sourcing in test script ([62ff6d3](https://github.com/viceda-s/SentinelOps/commit/62ff6d307a811b6c5896db471c5341b5c26bf689))
* address code review findings (SLA logging, collector ownership docs, typo) ([a376bab](https://github.com/viceda-s/SentinelOps/commit/a376bab550cb265606e1e112b57af05aaeaa23b7))
* capture incident transition result and prevent healthcheck script short-circuiting ([c4ed7cf](https://github.com/viceda-s/SentinelOps/commit/c4ed7cfa866e691ff6b5245dfe7ae93144ea836d))
* check Prometheus's own scrape status for node-exporter/cadvisor instead of loopback ([b7c912c](https://github.com/viceda-s/SentinelOps/commit/b7c912c6239d0892d296dff7112d0b524b4cc3f3))
* **ci:** add postgresql-client to jenkins-agent Dockerfile for database support ([3a76a0c](https://github.com/viceda-s/SentinelOps/commit/3a76a0c71b1708d045f0114288d0c841d3ff7af3))
* **ci:** install Python toolchain + shellcheck on jenkins-agent, use venv for pip-managed tools ([a057276](https://github.com/viceda-s/SentinelOps/commit/a0572766bb6b19b9739b0934b0ab8bbec02a3293))
* **ci:** persist Trivy's vulnerability DB in a named volume across scans ([6915395](https://github.com/viceda-s/SentinelOps/commit/69153955cfb1745f87d419e5e36170d12063ed91))
* **ci:** preserve existing environment variables when sourcing .env.test in init_test_db.sh ([df589a1](https://github.com/viceda-s/SentinelOps/commit/df589a1f4635ea9b226689ad14c70226248ee2db))
* **ci:** resolve sonar-scanner via tool step instead of relying on PATH injection ([085c3c2](https://github.com/viceda-s/SentinelOps/commit/085c3c226509a5929b3a1bd1279c948098fb8008))
* **ci:** run smee-client as a persistent docker-compose service ([fc7c597](https://github.com/viceda-s/SentinelOps/commit/fc7c5971b06ff4f0d2b060890c3ba78d1f8d9563))
* **ci:** simplify command paths in Jenkinsfile for pip, yamllint, and ruff ([7d8449b](https://github.com/viceda-s/SentinelOps/commit/7d8449b314d7487934fca5be90166ad566170320))
* **ci:** switch first-party images to python:3.14-alpine to clear Debian util-linux CVEs ([ae92644](https://github.com/viceda-s/SentinelOps/commit/ae92644cbbe03220ec2140996d52cc6ea8f926b9))
* **ci:** update Jenkinsfile to set COMPOSE_PROJECT_NAME and modify cleanup command ([2d6b4cf](https://github.com/viceda-s/SentinelOps/commit/2d6b4cfaeb9d09237a09432e1540cfdd07658e57))
* **ci:** use usernamePassword binding for github-pat in Release Please stage ([6756604](https://github.com/viceda-s/SentinelOps/commit/67566046990cc5798597d4d6c027e6dcfed76150))
* **ci:** use usernamePassword binding for github-pat in Release Please stage ([639b999](https://github.com/viceda-s/SentinelOps/commit/639b99916a36d24b40885bb8fa6a036a17072911))
* **ci:** wait for postgres healthcheck before running init_test_db.sh ([4296c76](https://github.com/viceda-s/SentinelOps/commit/4296c76f2bb5382e55bc4102fa2af78e9a5ba5bc))
* commit SLA breach writes independently, revert phase1.json ([7c4a167](https://github.com/viceda-s/SentinelOps/commit/7c4a1677db1334cf9abf970051dadbcf4ed5c102))
* correct typo in comment for required defaults in make_incident fixture ([337da5c](https://github.com/viceda-s/SentinelOps/commit/337da5c8adb12a1dc40a6e09a71f3efa64b64020))
* reject BACKUP_RETENTION values below 1 before running ([d009ab5](https://github.com/viceda-s/SentinelOps/commit/d009ab5e8d1f5133ae8a709075af71e970469aa1))
* remove /hostfs mount from worker, no longer needed by disk_cleanup ([2e5d479](https://github.com/viceda-s/SentinelOps/commit/2e5d4790e4219e5aa14b575e5ce61689c504a8e5))
* replace disk_cleanup's /hostfs re-check with a scoped Prometheus query ([bb4af88](https://github.com/viceda-s/SentinelOps/commit/bb4af88d134ab9504751910dd712da0535791092))
* **response-engine:** size docker-health verify timeout to healthcheck interval ([#60](https://github.com/viceda-s/SentinelOps/issues/60)) ([fd73e22](https://github.com/viceda-s/SentinelOps/commit/fd73e226976b8886f9a217564e23246190518e03))
* route DiskPressure-&gt;disk_cleanup to node-exporter, document /hostfs Docker Desktop limitation ([aac668e](https://github.com/viceda-s/SentinelOps/commit/aac668ede49708c157a04567354d2b52d76277b0))
* run worker under an init process so it can be signaled correctly ([d8eb00f](https://github.com/viceda-s/SentinelOps/commit/d8eb00f7c360bdce274c5a92fd221d3e62fc151a))
* **security:** bind Flask dev servers to localhost instead of all interfaces ([bf810a2](https://github.com/viceda-s/SentinelOps/commit/bf810a245f1c195d9bf780770e9f6e3938a386f9))
* split disk_cleanup's OSError handling by failure site ([5ef4b2c](https://github.com/viceda-s/SentinelOps/commit/5ef4b2cb0700c2f74b9cb703cc8cec63fec77209))
* **tests:** restore correlation_id tests dropped during main merge, fix stale call assertion ([eeda167](https://github.com/viceda-s/SentinelOps/commit/eeda167f92bd3cf2d36a7a8024fd14c2e158c2db))
* validate_cmdb.py rejects the 'none' playbook sentinel it's documented to accept ([7ad671d](https://github.com/viceda-s/SentinelOps/commit/7ad671dd9dc52bf24de0379ee08ba62891ffeb19))


### Documentation

* add ADR-012 and update ROADMAP for Jenkins CI/CD migration ([#76](https://github.com/viceda-s/SentinelOps/issues/76)) ([fb0d2ed](https://github.com/viceda-s/SentinelOps/commit/fb0d2eda84277dbd988e03fcdc151e2583651c0e))
* add ADR-013 for Release Please versioning automation ([f0cb866](https://github.com/viceda-s/SentinelOps/commit/f0cb866044f960b68b34582f15fba6ca136dec0c))
* **audit:** perform repository-wide PEP 257 Python docstring and comment audit ([a54ea86](https://github.com/viceda-s/SentinelOps/commit/a54ea86888da805804f13f1baec95a7105b7f0c1))
* correct DESIGN.md's Prometheus-independence claim and disk_cleanup description ([b8c6b19](https://github.com/viceda-s/SentinelOps/commit/b8c6b195a3bdaa5f19ed9f8cb8b159ce4866a3b7))
* document backup.sh, healthcheck.sh, and chaos fill/reset ([afb5465](https://github.com/viceda-s/SentinelOps/commit/afb5465a33ee7a2cc2c0265b2aab872cf5b68069))
* document self-http's localhost-only probe scope, fix column alignment ([a5ad668](https://github.com/viceda-s/SentinelOps/commit/a5ad6683ee4b9f18bea0f8e9c2b762d1dc5296ce))
* list backup.sh under Operational Tooling in README ([1c68359](https://github.com/viceda-s/SentinelOps/commit/1c68359fcc148fc2b6adbdec1c632301ef763d4c))
* Phase 2 documentation reconciliation and codebase audit (Issue [#8](https://github.com/viceda-s/SentinelOps/issues/8)) ([39323cc](https://github.com/viceda-s/SentinelOps/commit/39323cc4f74978b6f5dd77132715fa1a9cefc48e))
* **phase2:** add Phase 2 operational runbooks and ADRs 009-011 ([2a4f4f7](https://github.com/viceda-s/SentinelOps/commit/2a4f4f7d74f85bb1465666047e23b731c7406fc2))
* **reconciliation:** reconcile README, DESIGN.md, and implementation findings for Phase 2 ([e0dd656](https://github.com/viceda-s/SentinelOps/commit/e0dd656b2dbd8a75d8d6d53c84dcd6c5b3d6108d))
* update README to reflect completion of Phase 2 operational visibility features ([90b23c2](https://github.com/viceda-s/SentinelOps/commit/90b23c2846db4abe8dee7f1e231058f0165f3f37))

## [1.3.0] - 2026-09-20

### Added

- Stood up Jenkins as the primary, required CI/CD pipeline (`Jenkinsfile`, `jenkins`/`jenkins-agent` services in `docker-compose.yml`): config validation, build/test with coverage, a SonarQube Cloud quality gate, first-party container builds, a Trivy vulnerability scan, and a manually-triggered E2E chaos stage. `.github/workflows/quality-gate.yml` is retained as a slimmed, non-required lint-and-unit-test backstop. Recorded in ADR-012.

### Changed

- Reconciled `README.md` and `ROADMAP.md` with the Jenkins CI/CD migration.

## [1.2.3] - 2026-09-19

### Added

- Wired in `pytest-cov` coverage measurement and reporting, scoped to `automation/` via `[tool.coverage.*]` in `pyproject.toml`.

## [1.2.2] - 2026-09-07

### Added

- Added `correlation_id` and `execution_id` tracing primitives to `automation/response_engine`, threading a stable identifier through an incident's full lifecycle and each individual remediation attempt.

## [1.2.1] - 2026-08-09

### Added

- Introduced `automation/response_engine/config.py` with immutable configuration dataclasses (`DatabaseSettings`, `PrometheusSettings`, `DiagnosticsSettings`, `CMDBSettings`, `AlertmanagerSettings`) for centralized environment variable management.
- Implemented centralized event sequence generation in `automation/response_engine/events.py` using PostgreSQL row-level locking (`SELECT ... FOR UPDATE`) to enforce strictly monotonic event sequence numbers across concurrent operations.

### Changed

- Decomposed `automation/response_engine/handlers.py` into dedicated helper functions (`_reconcile_duplicate_alert`, `_create_new_incident_from_alert`) for improved alert processing modularity and maintainability.
- Decoupled `CMDB_PATH` resolution across scripts (`validate_cmdb.py`, `close_incident.py`, `health_page.py`) to support both containerized execution and local CLI/test invocations.
- Added explicit database connection type hints (`psycopg2.extensions.connection`) across all response engine modules.
- Reconciled `README.md` and `docs/DESIGN.md` with post-Phase 1.2 architectural refactorings.

## [1.2.0] - 2026-08-08

### Added

- Shipped Phase 1.1.2 operational runbooks: `maintenance-windows.md`, `incident-closure-and-reports.md`, `backup-and-disaster-recovery.md`, `disk-cleanup.md`.
- Added Architecture Decision Records ADR-009 (Maintenance Window Alertmanager Suppression), ADR-010 (SLA Breach Calculation and Metrics), and ADR-011 (Decoupled Report Generation and Health Dashboard).
- Recorded Phase 1.1.2 implementation findings 11–13 in `docs/implementation-findings.md` covering maintenance deduplication, `clock_timestamp()` SLA intervals, and atomic health page file publication.
- Performed a repository-wide Python docstring and comment audit establishing PEP 257 Google-style docstrings and explaining critical code invariants without altering application logic.

### Changed

- Updated `README.md` and `docs/DESIGN.md` to reflect Phase 1.2 completion.
- Reconciled `docs/adr/README.md` index table with Phase 1.2 ADR additions.

## [1.1] - 2026-08-01

### Changed

- Clarified that the webhook handler identifies services by Alertmanager's
  `job` label, not a `service` label that doesn't exist in practice.
- Documented `NEW → ESCALATED` as a valid incident transition, for
  services unknown to the CMDB that must escalate before any worker has
  claimed them.
- Reorganized the design's description of runbooks around operational
  response rather than alert type, matching how they were actually
  written; documented the CMDB's current per-service (not per-playbook)
  runbook mapping as a known limitation.
- Documented recovery verification as CMDB-driven metadata rather than
  hardcoded worker logic, and updated the CMDB example to include the
  verification configuration (`http`, `docker-health`, or `running`).
- Corrected config validation's alert-coverage check to reflect that
  coverage is defined by Prometheus scrape jobs, not by a `service` label
  on alert rules.
- Clarified incident deduplication semantics: an incident is open for
  fingerprint-based deduplication only while `NEW`, `ACKNOWLEDGED`,
  `IN_PROGRESS`, or `ESCALATED`; `RESOLVED` ends the dedup window.
- Documented that `docker-health` verification reads Docker's existing
  `HEALTHCHECK` status rather than triggering a fresh probe, and that
  remediation timing is recorded with real elapsed wall-clock time.
- Replaced the design's fixed `event`/`component` logging vocabulary with
  the schema actually implemented: `timestamp`, `level`, `logger`,
  `message`, optional `incident_reference`, optional `exception`, and a
  free-form `context` object.
- Clarified that `incident_events` records incident lifecycle only;
  remediation execution detail lives in `remediation_attempts` and the two
  are joined when reconstructing a full timeline.
- Documented that the remediation worker loads the CMDB once at startup
  and escalates incidents referencing a service missing from that
  snapshot. Changes to `cmdb/services.yaml` take effect only after the
  worker is restarted.
