from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

import psycopg2
import yaml
from psycopg2.extras import RealDictCursor

from .health_page import query_health_state, render_health_page
from .pdf import write_pdf_and_record
from .report_model import build_report_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEALTH_PAGE_REFRESH_SECONDS = int(os.environ.get("HEALTH_PAGE_REFRESH_SECONDS", "30"))
PDF_SCAN_SECONDS = int(os.environ.get("PDF_SCAN_SECONDS", "5"))
HEALTH_DIR = Path(os.environ.get("HEALTH_DIR", "/app/health"))
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", "/app/reports"))
CMDB_PATH = Path(os.environ.get("CMDB_PATH", "/app/cmdb/services.yaml"))

_running = True


def get_connection():
    """
    Create a database connection for a single scheduled task.
    """
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.environ["REPORT_GENERATOR_DB_USER"],
        password=os.environ["REPORT_GENERATOR_DB_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
        cursor_factory=RealDictCursor,
    )


def load_cmdb() -> dict:
    """
    Load the CMDB from disk.
    """
    with CMDB_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def refresh_health_page(conn, cmdb: dict) -> None:
    """
    Render and atomically publish the health page.

    HTML is written to a temporary file, flushed, fsynced, and atomically renamed so readers never observe a partially-written page.
    """

    HEALTH_DIR.mkdir(parents=True, exist_ok=True)

    html = render_health_page(query_health_state(conn, cmdb))

    final_path = HEALTH_DIR / "index.html"
    tmp_path = HEALTH_DIR / "index.html.tmp"

    with tmp_path.open("w", encoding="utf-8") as f:
        f.write(html)
        f.flush()
        os.fsync(f.fileno())

    tmp_path.replace(final_path)


def generate_pending_reports(conn) -> None:
    """
    Generate PDF reports for CLOSED incidents that do not yet have one.

    Each report is commited independently so one rendering failure does not roll back reports generated earlier in the same scan.
    """

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT incidents.id
            FROM incidents
            LEFT JOIN incident_reports
                ON incident_reports.incident_id = incidents.id
            WHERE incidents.status = 'CLOSED'
              AND incident_reports.incident_id IS NULL
            ORDER BY incidents.detected_at
            """
        )

        pending = cur.fetchall()

    for row in pending:
        try:
            model = build_report_model(conn, row["id"])
            write_pdf_and_record(conn, model, REPORTS_DIR)
            conn.commit()

            logger.info(
                "Generated incident report for %s",
                model.incident["reference"],
            )

        except Exception:
            conn.rollback()
            logger.exception(
                "Failed to generate report for incident %s.",
                row["id"],
            )


def _shutdown(signum, _frame):
    """Request a graceful shutdown."""

    global _running

    logger.info("Received signal %s. Shutting down...", signum)
    _running = False


def main() -> None:
    """Run the report generator."""

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    cmdb = load_cmdb()

    next_health_refresh = time.monotonic()
    next_pdf_file = time.monotonic()

    while _running:
        now = time.monotonic()

        if now >= next_health_refresh:
            conn = get_connection()
            try:
                refresh_health_page(conn, cmdb)
            except Exception:
                logger.exception("Failed to refresh health page.")
            finally:
                conn.close()

            next_health_refresh = now + HEALTH_PAGE_REFRESH_SECONDS

        if now >= next_pdf_file:
            conn = get_connection()
            try:
                generate_pending_reports(conn)
            finally:
                conn.close()

            next_pdf_file = now + PDF_SCAN_SECONDS

        time.sleep(1)


if __name__ == "__main__":
    main()
