from __future__ import annotations

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
