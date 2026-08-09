# ADR-011: Decoupled Report Generation and Health Dashboard

**Status:** Accepted

## Context

Phase 2 introduced two operational reporting requirements:
1. A live system health dashboard displaying service status, active maintenance windows, and open incidents.
2. Formal PDF incident reports generated automatically upon incident closure for auditing and post-mortem analysis.

Rendering PDF reports using ReportLab and compiling Jinja2 HTML templates require specialized dependencies, file system storage, and CPU resources. Combining report generation into the primary remediation worker would inflate container dependencies, increase attack surface, and risk blocking automated incident remediation during heavy reporting scans.

## Decision

Report generation and health dashboard rendering are decoupled into a dedicated, isolated service (`report-generator`) running in its own container (`docker/report-generator/`).

1. **Dedicated Service Architecture**:
   - The `report-generator` container runs `automation/report_generator/report_generator.py` independently from the response engine worker and webhook handler.
   - Operates under a dedicated, restricted PostgreSQL role (`sentinelops_report_generator`) with read-only access to `incidents`, `incident_events`, `remediation_attempts`, and write access restricted to `incident_reports`.
2. **Atomic Health Page Publishing**:
   - `refresh_health_page()` queries database state and CMDB every 30 seconds, renders `health/index.html` via Jinja2, flushes data to `index.html.tmp`, issues `fsync()`, and atomically renames the file to `index.html`.
   - Ensures HTTP clients reading `/health/` via Nginx never observe partially-written or corrupted HTML files.
3. **Automated PDF Generation**:
   - `generate_pending_reports()` polls for incidents in `CLOSED` status lacking a corresponding row in `incident_reports`.
   - Assembles full incident timelines, diagnostic artifacts, and Root Cause Analysis (RCA) data into a ReportLab document, writes `reports/INC-*.pdf`, and inserts metadata into `incident_reports`.
4. **Nginx Web Serving**:
   - Nginx routes `/health/` to the static health HTML page and `/reports/` to generated PDF files in read-only volume mounts.

## Alternatives considered

* **Embed PDF generation directly into the main remediation worker.** Rejected because adding ReportLab and Jinja dependencies to the worker inflates image size, couples remediation loop timing with PDF generation, and increases security exposure.
* **Generate PDF reports synchronously upon HTTP request.** Rejected because ReportLab rendering takes hundreds of milliseconds and should not block web API responses.
* **Store PDF reports as bytea blobs in PostgreSQL.** Rejected because binary file serving is more efficiently handled by Nginx via static file mounts than streaming database blobs.

## Consequences

* The core remediation worker remains lightweight, fast, and completely independent of PDF rendering libraries.
* Dedicated database credentials (`sentinelops_report_generator`) enforce strict principal of least privilege boundaries.
* Atomic file publishing (`fsync()` + rename) guarantees clean web dashboard serving without race conditions.
* PDF report generation is automatic, resilient, and non-blocking: a rendering failure on one incident is logged and isolated without rolling back other reports or disrupting remediation.
