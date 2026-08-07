"""
Section builders for the incident report.

Each function converts a portion of a ReportModel into ReportLab
flowables. These builders are pure and perform no I/O, making them easy
to reuse and test independently.
"""

from __future__ import annotations

from reportlab.platypus import (
    Flowable,
    ListFlowable,
    ListItem,
    Paragraph,
    Spacer,
    Table,
)

from ..report_model import ReportModel
from .formatting import (
    display,
    format_bool,
    format_duration,
    format_timestamp,
    key_value_table,
    label_value_table,
)
from .styles import (
    SECTION_SPACER_HEIGHT,
    TIMELINE_COL_WIDTHS,
    styles,
    timeline_table_style,
)


def build_header(model: ReportModel) -> list[Flowable]:
    return [
        Paragraph("SentinelOps", styles["ReportTitle"]),
        Paragraph("Incident Report", styles["ReportSubtitle"]),
        Paragraph(
            f"Reference: {model.incident['reference']}",
            styles["ReportSubtitle"],
        ),
        Spacer(1, 2 * SECTION_SPACER_HEIGHT),
    ]


def build_incident_information(model: ReportModel) -> list[Flowable]:
    incident = model.incident

    table = label_value_table(
        [
            ["Reference", display(incident["reference"])],
            ["Service", display(incident["service"])],
            ["Severity", display(incident["severity"])],
            ["Status", display(incident["status"])],
            ["Detected", format_timestamp(incident.get("detected_at"))],
            ["Resolved", format_timestamp(incident.get("resolved_at"))],
        ]
    )

    return [
        Paragraph("Incident Information", styles["SectionHeading"]),
        table,
        Spacer(1, SECTION_SPACER_HEIGHT),
    ]


def build_detection_details(model: ReportModel) -> list[Flowable]:
    incident = model.incident

    return [
        Paragraph("Detection Details", styles["SectionHeading"]),
        Paragraph(
            f"<b>Alert Name:</b> {display(incident['alert_name'])}",
            styles["ReportBody"],
        ),
        Paragraph("Labels", styles["SubHeading"]),
        key_value_table(incident["labels"]),
        Paragraph("Annotations", styles["SubHeading"]),
        key_value_table(incident["annotations"]),
        Spacer(1, SECTION_SPACER_HEIGHT),
    ]


def build_timeline(model: ReportModel) -> list[Flowable]:
    """
    Build the Timeline section of the incident report.

    The returned flowables intentionally remain flat. Pagination is
    applied by render_pdf(), allowing the section to be tested
    independently of PDF generation.
    """

    heading = Paragraph("Timeline", styles["SectionHeading"])

    if not model.timeline:
        body: list[Flowable] = [
            Paragraph("No timeline activity recorded.", styles["ReportBody"])
        ]
    else:
        rows = []
        for entry in model.timeline:
            if entry.kind == "event":
                description = entry.payload.get(
                    "message",
                    entry.payload.get("event_type", ""),
                )
            else:
                description = (
                    f"Ran {entry.payload['playbook']} "
                    f"(result: {entry.payload['result']})"
                )

            rows.append([format_timestamp(entry.occurred_at), description])

        timeline_table = Table(rows, colWidths=TIMELINE_COL_WIDTHS)
        timeline_table.setStyle(timeline_table_style(len(rows)))
        body = [timeline_table]

    elements: list[Flowable] = [heading, *body, Spacer(1, SECTION_SPACER_HEIGHT)]
    return elements


def build_actions_taken(model: ReportModel) -> list[Flowable]:
    actions = [entry for entry in model.timeline if entry.kind == "remediation_attempt"]

    if not actions:
        body: list[Flowable] = [
            Paragraph(
                "No remediation actions were executed.",
                styles["ReportBody"],
            )
        ]
    else:
        items = [
            ListItem(
                Paragraph(
                    f"{action.payload['playbook']} (attempt {action.payload['attempt_number']}) → {action.payload['result']}",
                    styles["ReportBody"],
                ),
                leftIndent=20,
            )
            for action in actions
        ]
        body = [
            Spacer(1, 3),
            ListFlowable(
                items,
                bulletType="bullet",
                start="•",
                leftIndent=20,
            ),
        ]

    elements: list[Flowable] = [
        Paragraph("Actions Taken", styles["SectionHeading"]),
        *body,
        Spacer(1, SECTION_SPACER_HEIGHT),
    ]
    return elements


def build_diagnostic_evidence(model: ReportModel) -> list[Flowable]:
    heading = Paragraph("Diagnostic Evidence", styles["SectionHeading"])
    body: list[Flowable] = [
        Paragraph("<b>Alert labels:</b> Included", styles["ReportBody"]),
    ]

    if model.diagnostics is None:
        body.append(
            Paragraph(
                f"<b>Collected diagnostics:</b> {model.diagnostics_unavailable_reason or 'Unavailable.'}",
                styles["ReportBody"],
            )
        )
    else:
        body.append(Paragraph("Collected diagnostics", styles["SubHeading"]))
        body.append(key_value_table(model.diagnostics))

    return [heading, *body, Spacer(1, SECTION_SPACER_HEIGHT)]


def build_recovery_sla(model: ReportModel) -> list[Flowable]:
    incident = model.incident

    recovery = None
    if (
        incident.get("detected_at") is not None
        and incident.get("resolved_at") is not None
    ):
        recovery = incident["resolved_at"] - incident["detected_at"]

    table = label_value_table(
        [
            ["Recovery time", format_duration(recovery)],
            [
                "Response SLA breached",
                format_bool(incident.get("sla_response_breached")),
            ],
            [
                "Resolution SLA breached",
                format_bool(incident.get("sla_resolution_breached")),
            ],
        ]
    )

    return [
        Paragraph("Recovery Time and SLA Outcome", styles["SectionHeading"]),
        table,
        Spacer(1, SECTION_SPACER_HEIGHT),
    ]


def build_root_cause_analysis(model: ReportModel) -> list[Flowable]:
    return [
        Paragraph("Root Cause Analysis", styles["SectionHeading"]),
        Paragraph(
            model.incident.get("root_cause_analysis") or "PENDING RCA",
            styles["RCABody"],
        ),
    ]
