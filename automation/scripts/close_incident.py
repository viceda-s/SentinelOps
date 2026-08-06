from __future__ import annotations

import argparse
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor

from automation.response_engine.state_machine import transition


def find_incident_by_reference(conn, reference):
    """
    Look up an incident by its human-readable reference.

    The caller owns the transaction.
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM incidents
            WHERE reference = %s
            """,
            (reference,),
        )

        return cur.fetchone()


def close_incident(conn, reference, rca_text):
    """
    Close a resolved incident.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback()
    """

    incident = find_incident_by_reference(conn, reference)

    if incident is None:
        raise ValueError(f"Incident '{reference}' not found")

    if incident["status"] != "RESOLVED":
        raise ValueError(
            f"Incident '{reference}' is in status '{incident['status']}'; expected 'RESOLVED'"
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE incidents
            SET root_cause_analysis = %s
            WHERE id = %s
            """,
            (
                rca_text,
                incident["id"],
            ),
        )

    incident["root_cause_analysis"] = rca_text

    return transition(conn, incident, "CLOSED", "operator", "Incident closed")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Close a resolved incident and record its RCA."
    )
    parser.add_argument("reference", help="Incident reference (e.g. INC-2026-001).")
    parser.add_argument("rca_file", help="Path to the root cause analysis text file.")
    args = parser.parse_args()

    with open(args.rca_file, encoding="utf-8") as f:
        rca_text = f.read().strip()

    # Defense in depth. close_incident.sh should already have removed comment lines and rejected an empty message before invoking this CLI.
    if not rca_text:
        print("error: RCA text is empty.", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "postgres"),
        user=os.environ["RESPONSE_ENGINE_DB_USER"],
        password=os.environ["RESPONSE_ENGINE_DB_PASSWORD"],
        cursor_factory=RealDictCursor,
    )

    try:
        incident = close_incident(conn, args.reference, rca_text)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

    print(
        f"{incident['reference']} closed. PDF will appear under `reports/` within a few seconds."
    )


if __name__ == "__main__":
    main()
