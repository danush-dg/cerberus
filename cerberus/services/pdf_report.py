from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def generate_audit_report(project_id: str, report_data: dict) -> bytes:
    """Generate a PDF audit report using reportlab only.

    INV-SEC2-03: no network calls, no GCP API calls, no file I/O.
    Returns bytes beginning with b'%PDF'.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    elements = []

    # -----------------------------------------------------------------------
    # 1. Header
    # -----------------------------------------------------------------------
    report_timestamp = report_data.get("report_timestamp") or datetime.utcnow().isoformat()
    pid = report_data.get("project_id") or project_id

    elements.append(Paragraph("Cerberus Audit Report", styles["Title"]))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph(f"Project: <b>{pid}</b>", styles["Normal"]))
    elements.append(Paragraph(f"Generated: {report_timestamp}", styles["Normal"]))
    elements.append(Spacer(1, 0.5 * cm))

    # -----------------------------------------------------------------------
    # 2. Executive summary table
    # -----------------------------------------------------------------------
    resources_scanned = report_data.get("resources_scanned") or 0
    security_flags = report_data.get("security_flags") or []
    iam_changes = report_data.get("iam_changes") or []

    elements.append(Paragraph("Executive Summary", styles["Heading2"]))
    summary_data = [
        ["Metric", "Value"],
        ["Resources Scanned", str(resources_scanned)],
        ["Security Flags Raised", str(len(security_flags))],
        ["IAM Changes", str(len(iam_changes))],
    ]
    summary_table = Table(summary_data, colWidths=[10 * cm, 6 * cm])
    summary_table.setStyle(_base_style())
    elements.append(summary_table)
    elements.append(Spacer(1, 0.5 * cm))

    # -----------------------------------------------------------------------
    # 3. IAM changes table
    # -----------------------------------------------------------------------
    elements.append(Paragraph("IAM Changes", styles["Heading2"]))
    if iam_changes:
        iam_rows = [["Identity", "Role", "Changed At", "Changed By"]]
        for row in iam_changes:
            iam_rows.append([
                str(row.get("identity") or "—"),
                str(row.get("role") or "—"),
                str(row.get("changed_at") or "—"),
                str(row.get("changed_by") or "—"),
            ])
        iam_table = Table(iam_rows, colWidths=[5 * cm, 5 * cm, 4 * cm, 4 * cm])
        iam_table.setStyle(_base_style())
        elements.append(iam_table)
    else:
        elements.append(Paragraph("No IAM changes recorded.", styles["Normal"]))
    elements.append(Spacer(1, 0.5 * cm))

    # -----------------------------------------------------------------------
    # 4. Security flags table
    # -----------------------------------------------------------------------
    elements.append(Paragraph("Security Flags", styles["Heading2"]))
    if security_flags:
        flag_rows = [["Flag Type", "Identity / Resource", "Detected At", "Detail"]]
        for flag in security_flags:
            flag_rows.append([
                str(flag.get("flag_type") or "—"),
                str(flag.get("identity_or_resource") or "—"),
                str(flag.get("detected_at") or "—"),
                str(flag.get("detail") or "—"),
            ])
        flag_table = Table(flag_rows, colWidths=[4 * cm, 5 * cm, 4 * cm, 5 * cm])
        flag_table.setStyle(_base_style())
        elements.append(flag_table)
    else:
        elements.append(Paragraph("No active security flags.", styles["Normal"]))
    elements.append(Spacer(1, 0.5 * cm))

    # -----------------------------------------------------------------------
    # 5. Idle resources table
    # -----------------------------------------------------------------------
    idle_resources = report_data.get("idle_resources") or []
    elements.append(Paragraph("Idle Resources", styles["Heading2"]))
    if idle_resources:
        idle_rows = [["Resource ID", "Type", "Last Activity", "Monthly Cost"]]
        for res in idle_resources:
            idle_rows.append([
                str(res.get("resource_id") or res.get("identity_or_resource") or "—"),
                str(res.get("resource_type") or "—"),
                str(res.get("last_activity") or "—"),
                str(res.get("monthly_cost") or res.get("detail") or "—"),
            ])
        idle_table = Table(idle_rows, colWidths=[5 * cm, 4 * cm, 4 * cm, 5 * cm])
        idle_table.setStyle(_base_style())
        elements.append(idle_table)
    else:
        elements.append(Paragraph("No idle resources detected.", styles["Normal"]))
    elements.append(Spacer(1, 1 * cm))

    # -----------------------------------------------------------------------
    # 6. Footer
    # -----------------------------------------------------------------------
    elements.append(Paragraph(
        "Generated by Cerberus — Agentic GCP Dev Environment Guardian",
        styles["Normal"],
    ))

    doc.build(elements)
    return buffer.getvalue()


def _base_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f77b4")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])
