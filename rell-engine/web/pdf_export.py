"""
Rell PDF Export — reportlab compliance report generator.

Generates a clean, professional PDF audit report suitable for
presentation to legal, compliance, or board-level audiences.

Structure:
    Page 1  — Cover (RELL wordmark, profile, date, summary counts)
    Page 2  — Executive Summary (severity table, Rell's opening)
    Page 3+ — Detailed Findings (one block per finding, severity-coded)
              Rell's Closing Assessment

Usage:
    from web.pdf_export import generate_pdf
    pdf_bytes = generate_pdf(report_dict)
    with open("report.pdf", "wb") as f:
        f.write(pdf_bytes)
"""

from io import BytesIO
from datetime import datetime
from typing import Any, List

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    PageBreak,
    KeepTogether,
)

# ---------------------------------------------------------------------------
# Severity palette
# ---------------------------------------------------------------------------

_COLORS = {
    "CRITICAL": HexColor("#CC0000"),
    "HIGH":     HexColor("#CC5500"),
    "MEDIUM":   HexColor("#AA8800"),
    "LOW":      HexColor("#2255AA"),
    "INFO":     HexColor("#555555"),
}

_BG = {
    "CRITICAL": HexColor("#FFF5F5"),
    "HIGH":     HexColor("#FFF8F0"),
    "MEDIUM":   HexColor("#FDFDF0"),
    "LOW":      HexColor("#F0F5FF"),
    "INFO":     HexColor("#F8F8F8"),
}

_SEV_DESCS = {
    "CRITICAL": "Immediate regulatory risk. Requires urgent remediation.",
    "HIGH":     "Significant compliance gap. Address in current cycle.",
    "MEDIUM":   "Moderate risk. Include in next remediation sprint.",
    "LOW":      "Minor issue. Document and monitor.",
    "INFO":     "Informational. No immediate action required.",
}

PAGE_W, PAGE_H = A4
CONTENT_W = PAGE_W - 4 * cm   # usable text width with 2cm margins each side


# ---------------------------------------------------------------------------
# Page header/footer
# ---------------------------------------------------------------------------

def _on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(HexColor("#999999"))
    canvas.drawString(2 * cm, 1.2 * cm, "RELL AUDIT ENGINE — CONFIDENTIAL")
    canvas.drawRightString(PAGE_W - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Style factory
# ---------------------------------------------------------------------------

def _s(name: str, base, **kw) -> ParagraphStyle:
    """Create a named ParagraphStyle derived from base."""
    return ParagraphStyle(name, parent=base, **kw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_pdf(report: dict) -> bytes:
    """
    Build a compliance audit PDF from a run_audit report dict.
    Returns raw PDF bytes.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.2 * cm,
        title="Rell Audit Report",
    )

    base_normal = getSampleStyleSheet()["Normal"]

    # ── Styles ──────────────────────────────────────────────────────────────
    s_wordmark   = _s("Wordmark",  base_normal, fontName="Helvetica-Bold",    fontSize=46, textColor=HexColor("#0d1117"), spaceAfter=6)
    s_subtitle   = _s("Subtitle",  base_normal, fontName="Helvetica",         fontSize=14, textColor=HexColor("#666666"), spaceAfter=24)
    s_section    = _s("Section",   base_normal, fontName="Helvetica-Bold",    fontSize=12, spaceBefore=16, spaceAfter=8,  textColor=HexColor("#0d1117"))
    s_meta       = _s("Meta",      base_normal, fontName="Helvetica",         fontSize=10, spaceAfter=5,  textColor=HexColor("#333333"))
    s_body       = _s("Body",      base_normal, fontName="Helvetica",         fontSize=9,  spaceAfter=4,  leading=14, textColor=HexColor("#333333"))
    s_disclaimer = _s("Disc",      base_normal, fontName="Helvetica-Oblique", fontSize=8,  textColor=HexColor("#999999"), spaceAfter=4)
    s_fh         = _s("FH",        base_normal, fontName="Helvetica-Bold",    fontSize=10, spaceAfter=4,  textColor=HexColor("#0d1117"))
    s_fb         = _s("FB",        base_normal, fontName="Helvetica",         fontSize=9,  leading=13,    spaceAfter=4, textColor=HexColor("#333333"))
    s_fw         = _s("FW",        base_normal, fontName="Helvetica",         fontSize=8,  spaceAfter=4,  textColor=HexColor("#888888"))

    # ── Report data ─────────────────────────────────────────────────────────
    findings     = report.get("findings", [])
    summary      = report.get("summary", {})
    by_sev       = summary.get("by_severity", {})
    total        = summary.get("total_findings", len(findings))
    cycle        = report.get("cycle", "—")
    rell_opening = report.get("rell_opening", "")
    rell_closing = report.get("rell_closing", "")

    # Extract profile/standard from findings (most reliable source after a run)
    profile_id   = ""
    standard_str = ""
    for f in findings:
        profile_id   = profile_id   or f.get("profile_id", "")
        standard_str = standard_str or f.get("standard", "")
        if profile_id and standard_str:
            break

    ts = report.get("timestamp", datetime.now().isoformat())
    try:
        date_str = datetime.fromisoformat(ts).strftime("%B %d, %Y at %H:%M")
    except Exception:
        date_str = ts[:19]

    elements: List[Any] = []

    # ========================================================================
    # PAGE 1 — COVER
    # ========================================================================

    elements.append(Spacer(1, 2 * cm))
    elements.append(Paragraph("RELL", s_wordmark))
    elements.append(Paragraph("AUTONOMOUS AUDIT REPORT", s_subtitle))
    elements.append(HRFlowable(width="100%", thickness=2, color=HexColor("#0d1117"), spaceAfter=24))

    for label, value in [
        ("Profile",        profile_id or "N/A"),
        ("Standard",       standard_str or "N/A"),
        ("Generated",      date_str),
        ("Audit Cycle",    str(cycle)),
        ("Total Findings", str(total)),
    ]:
        elements.append(Paragraph(f"<b>{label}:</b>  {value}", s_meta))

    elements.append(Spacer(1, 1.5 * cm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=8))
    elements.append(Paragraph(
        "This report was generated by Rell Autonomous Audit Engine and is not legal advice. "
        "All findings should be reviewed with qualified compliance counsel before regulatory "
        "action is taken.",
        s_disclaimer,
    ))

    elements.append(PageBreak())

    # ========================================================================
    # PAGE 2 — EXECUTIVE SUMMARY
    # ========================================================================

    elements.append(Paragraph("EXECUTIVE SUMMARY", s_section))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#dddddd"), spaceAfter=12))

    if rell_opening:
        elements.append(Paragraph("<b>Rell's Opening Assessment</b>", s_meta))
        for line in rell_opening.split("\n"):
            if line.strip():
                elements.append(Paragraph(line.strip(), s_body))
        elements.append(Spacer(1, 0.5 * cm))

    # Severity summary table
    elements.append(Paragraph("<b>Findings by Severity</b>", s_meta))
    elements.append(Spacer(1, 0.15 * cm))

    tbl_data = [["Severity", "Count", "Description"]]
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
        cnt = by_sev.get(sev, 0)
        if cnt > 0 or sev in ("CRITICAL", "HIGH"):
            tbl_data.append([sev, str(cnt), _SEV_DESCS[sev]])

    col_w = [3.0 * cm, 1.8 * cm, CONTENT_W - 4.8 * cm]
    tbl = Table(tbl_data, colWidths=col_w)

    tbl_style_cmds = [
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("BACKGROUND",    (0, 0), (-1, 0),  HexColor("#0d1117")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("GRID",          (0, 0), (-1, -1), 0.4, HexColor("#cccccc")),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for ri, row in enumerate(tbl_data[1:], start=1):
        sev = row[0]
        clr = _COLORS.get(sev, HexColor("#555555"))
        bg  = _BG.get(sev, colors.white) if row[1] != "0" else colors.white
        tbl_style_cmds += [
            ("TEXTCOLOR", (0, ri), (0, ri), clr),
            ("FONTNAME",  (0, ri), (0, ri), "Helvetica-Bold"),
            ("BACKGROUND",(0, ri), (1, ri), bg),
        ]
    tbl.setStyle(TableStyle(tbl_style_cmds))
    elements.append(tbl)

    # ========================================================================
    # PAGE 3+ — DETAILED FINDINGS
    # ========================================================================

    if findings:
        elements.append(PageBreak())
        elements.append(Paragraph("DETAILED FINDINGS", s_section))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#dddddd"), spaceAfter=12))

        for idx, finding in enumerate(findings, 1):
            sev       = finding.get("severity", "INFO")
            bar_color = _COLORS.get(sev, HexColor("#555555"))
            bg_color  = _BG.get(sev, colors.white)

            article     = finding.get("article", "")
            title       = finding.get("title", "Untitled Finding")
            observation = finding.get("observation", "")
            fix         = finding.get("suggested_fix", "")
            workflow    = finding.get("workflow", "")

            header = (
                f"<b>{idx}. [{sev}]</b>   {article}   {title}"
                if article else
                f"<b>{idx}. [{sev}]</b>   {title}"
            )

            inner: List[Any] = [Paragraph(header, s_fh)]

            if workflow:
                inner.append(Paragraph(f"Workflow: {workflow}", s_fw))
                inner.append(Spacer(1, 0.08 * cm))

            if observation:
                inner.append(Paragraph(f"<b>Observation:</b>  {observation}", s_fb))

            if fix and fix not in ("Under investigation.", "Review obligation against current data practices."):
                inner.append(Paragraph(f"<b>Suggested Fix:</b>  {fix}", s_fb))

            finding_tbl = Table([[inner]], colWidths=[CONTENT_W])
            finding_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), bg_color),
                ("LEFTPADDING",   (0, 0), (-1, -1), 10),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
                ("TOPPADDING",    (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("BOX",           (0, 0), (-1, -1), 0.5, HexColor("#dddddd")),
                ("LINEBEFORE",    (0, 0), (0, -1),  4,   bar_color),
            ]))

            elements.append(KeepTogether(finding_tbl))
            elements.append(Spacer(1, 0.22 * cm))

    # Rell's closing
    if rell_closing:
        elements.append(Spacer(1, 0.5 * cm))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#dddddd"), spaceAfter=8))
        elements.append(Paragraph("<b>Rell's Closing Assessment</b>", s_meta))
        for line in rell_closing.split("\n"):
            if line.strip():
                elements.append(Paragraph(line.strip(), s_body))

    doc.build(elements, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
