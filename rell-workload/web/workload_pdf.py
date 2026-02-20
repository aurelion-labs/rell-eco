"""
Rell Workload PDF Export

Generates a workload distribution PDF suitable for management review.
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

PAGE_W, PAGE_H = A4
CONTENT_W = PAGE_W - 4 * cm


def _on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(HexColor('#999999'))
    canvas.drawString(2 * cm, 1.2 * cm, 'RELL WORKLOAD TRACKER — CONFIDENTIAL')
    canvas.drawRightString(PAGE_W - 2 * cm, 1.2 * cm, f'Page {doc.page}')
    canvas.restoreState()


def _s(name: str, base, **kw) -> ParagraphStyle:
    return ParagraphStyle(name, parent=base, **kw)


# ---------------------------------------------------------------------------
# Workload load status palette
# ---------------------------------------------------------------------------

_WL_STATUS_COLOR = {
    "OVERLOADED":  HexColor("#CC0000"),
    "BALANCED":    HexColor("#1a7a3e"),
    "UNDERLOADED": HexColor("#AA8800"),
    "UNKNOWN":     HexColor("#555555"),
    "NOTE":        HexColor("#888888"),
}
_WL_STATUS_BG = {
    "OVERLOADED":  HexColor("#FFF5F5"),
    "BALANCED":    HexColor("#F0FFF4"),
    "UNDERLOADED": HexColor("#FDFDF0"),
    "UNKNOWN":     HexColor("#F8F8F8"),
    "NOTE":        HexColor("#F4F4F4"),
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


# ---------------------------------------------------------------------------
# Workload PDF
# ---------------------------------------------------------------------------

def generate_workload_pdf(report: dict) -> bytes:
    """
    Build a workload distribution PDF from a WorkloadAuditEngine report dict.
    Returns raw PDF bytes.

    Pages:
        1  — Cover (source file, date, headline stats)
        2  — Rell's Assessment (per-team narrative)
        3+ — One page per team (US DA / PH DA / DQS) as analyst tables
             + Unassigned Feeds section (if any)
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.2 * cm,
        title="Rell Workload Report",
    )

    base_normal = getSampleStyleSheet()["Normal"]

    s_wordmark   = _s("WL_Wm",   base_normal, fontName="Helvetica-Bold",    fontSize=46, textColor=HexColor("#0d1117"), spaceAfter=6)
    s_subtitle   = _s("WL_Sub",  base_normal, fontName="Helvetica",         fontSize=14, textColor=HexColor("#666666"), spaceAfter=24)
    s_section    = _s("WL_Sec",  base_normal, fontName="Helvetica-Bold",    fontSize=12, spaceBefore=14, spaceAfter=8,  textColor=HexColor("#0d1117"))
    s_meta       = _s("WL_Met",  base_normal, fontName="Helvetica",         fontSize=10, spaceAfter=5,   textColor=HexColor("#333333"))
    s_body       = _s("WL_Bod",  base_normal, fontName="Helvetica",         fontSize=9,  spaceAfter=4,   leading=14, textColor=HexColor("#333333"))
    s_thead      = _s("WL_TH",   base_normal, fontName="Helvetica-Bold",    fontSize=8,  spaceAfter=2,   textColor=colors.white)
    s_tbody      = _s("WL_TB",   base_normal, fontName="Helvetica",         fontSize=8,  spaceAfter=2,   leading=12, textColor=HexColor("#333333"))
    s_tagrow     = _s("WL_Tag",  base_normal, fontName="Helvetica-Oblique", fontSize=8,  textColor=HexColor("#888888"))
    s_disclaimer = _s("WL_Dis",  base_normal, fontName="Helvetica-Oblique", fontSize=8,  textColor=HexColor("#999999"), spaceAfter=4)

    filename       = report.get("filename", "Unknown")
    scanned_at     = report.get("scanned_at", "")[:19]
    team_stats     = report.get("team_stats", {})
    total_pts      = team_stats.get("total_team_points", 0)
    total_analysts = team_stats.get("analyst_count", 0)
    total_feeds    = team_stats.get("feed_count", 0)
    unassigned     = report.get("unassigned_feeds", [])
    warnings       = report.get("validation_warnings", [])
    rell_text      = report.get("rell_assessment", "")

    try:
        date_str = datetime.fromisoformat(scanned_at).strftime("%B %d, %Y at %H:%M")
    except Exception:
        date_str = scanned_at

    elements: List[Any] = []

    # ====================================================================
    # PAGE 1 — COVER
    # ====================================================================
    elements.append(Spacer(1, 2 * cm))
    elements.append(Paragraph("RELL", s_wordmark))
    elements.append(Paragraph("WORKLOAD DISTRIBUTION REPORT", s_subtitle))
    elements.append(HRFlowable(width="100%", thickness=2, color=HexColor("#0d1117"), spaceAfter=24))

    for label, value in [
        ("Source File",      filename),
        ("Generated",        date_str),
        ("Total Analysts",   str(total_analysts)),
        ("Total Feeds",      str(total_feeds)),
        ("Total Points",     f"{total_pts:.2f}"),
        ("Unassigned Feeds", str(len(unassigned))),
    ]:
        elements.append(Paragraph(f"<b>{label}:</b>  {value}", s_meta))

    elements.append(Spacer(1, 1.5 * cm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=8))
    elements.append(Paragraph(
        "This report was generated by Rell Autonomous Audit Engine for internal management use only. "
        "Workload figures are derived from the submitted Excel workbook and reflect feed assignments "
        "at time of scan.",
        s_disclaimer,
    ))

    # ====================================================================
    # PAGE 2 — RELL'S ASSESSMENT
    # ====================================================================
    elements.append(PageBreak())
    elements.append(Paragraph("RELL'S ASSESSMENT", s_section))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#dddddd"), spaceAfter=12))

    if rell_text:
        for line in rell_text.split("\n"):
            stripped = line.strip()
            if not stripped:
                elements.append(Spacer(1, 0.2 * cm))
                continue
            # Lines starting with ** are team-level headers in the per-team narrative
            if stripped.startswith("**") and stripped.endswith("."):
                clean = stripped.replace("**", "")
                team_hdr, rest = (clean.split(" — ", 1) + [""])[:2]
                elements.append(Spacer(1, 0.15 * cm))
                elements.append(Paragraph(f"<b>{team_hdr}</b>", s_meta))
                if rest:
                    elements.append(Paragraph(rest, s_body))
            elif stripped.startswith("**"):
                clean = stripped.replace("**", "")
                elements.append(Spacer(1, 0.15 * cm))
                elements.append(Paragraph(f"<b>{clean}</b>", s_meta))
            else:
                elements.append(Paragraph(stripped, s_body))
    else:
        elements.append(Paragraph("No assessment available.", s_body))

    # ====================================================================
    # TEAM TABLES — one page per team
    # ====================================================================
    team_configs = [
        ("US DATA ANALYST WORKLOAD",        "Manager: Kiara & Josefina", "us_da_summaries", "us_da_team_stats"),
        ("PHILIPPINES DA WORKLOAD",          "Manager: Auie",             "ph_da_summaries", "ph_da_team_stats"),
        ("DATA QUALITY SPECIALIST WORKLOAD", "",                           "dqs_summaries",   "dqs_team_stats"),
    ]

    col_widths = [
        CONTENT_W * 0.28,   # Analyst name
        CONTENT_W * 0.12,   # Primary pts
        CONTENT_W * 0.11,   # Backup pts
        CONTENT_W * 0.11,   # Total pts
        CONTENT_W * 0.08,   # Feed count
        CONTENT_W * 0.15,   # Status
        CONTENT_W * 0.15,   # Dev vs Avg
    ]

    for team_title, manager_line, sum_key, stats_key in team_configs:
        summaries = report.get(sum_key, {})
        stats     = report.get(stats_key, {})
        if not summaries:
            continue

        elements.append(PageBreak())
        elements.append(Paragraph(team_title, s_section))
        if manager_line:
            elements.append(Paragraph(manager_line, s_meta))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#dddddd"), spaceAfter=8))

        n_active   = stats.get("analyst_count", 0)
        avg        = stats.get("average_points_per_analyst", 0)
        n_feeds    = stats.get("feed_count", 0)
        elements.append(Paragraph(
            f"<b>{n_active}</b> active analysts  ·  avg <b>{avg:.2f} pts</b>  ·  <b>{n_feeds}</b> feeds assigned",
            s_meta,
        ))
        elements.append(Spacer(1, 0.3 * cm))

        # Table header row
        hdr = ["Analyst", "Primary", "Backup", "Total", "Feeds", "Status", "Dev vs Avg"]
        tbl_data = [hdr]
        row_styles: list = []

        active_rows = [(a, s) for a, s in summaries.items() if not s.get("display_tag")]
        tagged_rows = [(a, s) for a, s in summaries.items() if s.get("display_tag")]
        active_rows.sort(key=lambda x: -x[1].get("total_points", 0))

        ri = 1  # row index (0 = header)

        for analyst, s in active_rows:
            status    = s.get("load_status", "UNKNOWN")
            prim      = s.get("primary_points", 0)
            bkp       = s.get("backup_points", 0)
            total     = s.get("total_points", 0)
            feeds     = s.get("feed_count", 0)
            dev       = s.get("deviation_from_avg_pct")
            dev_str   = (f"+{dev:.1f}%" if dev > 0 else f"{dev:.1f}%") if dev is not None else "n/a"
            bg        = _WL_STATUS_BG.get(status, colors.white)
            status_c  = _WL_STATUS_COLOR.get(status, HexColor("#555555"))
            row_styles += [
                ("BACKGROUND", (0, ri), (-1, ri), bg),
                ("TEXTCOLOR",  (5, ri), (5, ri),  status_c),
                ("FONTNAME",   (5, ri), (5, ri),  "Helvetica-Bold"),
            ]
            tbl_data.append([
                analyst,
                f"{prim:.1f}", f"{bkp:.1f}", f"{total:.1f}",
                str(feeds), status, dev_str,
            ])
            ri += 1

        if tagged_rows:
            # Dotted separator row
            tbl_data.append(["· " * 20, "", "", "", "", "", ""])
            row_styles += [
                ("BACKGROUND", (0, ri), (-1, ri), HexColor("#F0F0F0")),
                ("TEXTCOLOR",  (0, ri), (-1, ri), HexColor("#AAAAAA")),
            ]
            ri += 1

            for analyst, s in tagged_rows:
                tag   = s.get("display_tag", "")
                prim  = s.get("primary_points", 0)
                bkp   = s.get("backup_points", 0)
                total = s.get("total_points", 0)
                feeds = s.get("feed_count", 0)
                row_styles += [
                    ("BACKGROUND", (0, ri), (-1, ri), HexColor("#F8F8F8")),
                    ("TEXTCOLOR",  (0, ri), (-1, ri), HexColor("#888888")),
                    ("FONTNAME",   (0, ri), (-1, ri), "Helvetica-Oblique"),
                ]
                tbl_data.append([
                    analyst,
                    f"{prim:.1f}", f"{bkp:.1f}", f"{total:.1f}",
                    str(feeds), f"[{tag}]", "—",
                ])
                ri += 1

        tbl = Table(tbl_data, colWidths=col_widths)
        base_style = [
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("BACKGROUND",    (0, 0), (-1, 0),  HexColor("#0d1117")),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
            ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#cccccc")),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ] + row_styles
        tbl.setStyle(TableStyle(base_style))
        elements.append(tbl)

    # ====================================================================
    # UNASSIGNED FEEDS (if any)
    # ====================================================================
    if unassigned:
        elements.append(PageBreak())
        elements.append(Paragraph("UNASSIGNED FEEDS", s_section))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#dddddd"), spaceAfter=12))
        elements.append(Paragraph(
            f"{len(unassigned)} feed{'s have' if len(unassigned) != 1 else ' has'} no assigned analyst. "
            "These represent orphaned work and should be assigned before the next review cycle.",
            s_body,
        ))
        elements.append(Spacer(1, 0.3 * cm))

        ua_data = [["Feed Name", "Points", "Row"]]
        for ua in unassigned:
            ua_data.append([
                ua.get("feed_name", "?"),
                f"{ua.get('workload_points', 0):.2f}",
                str(ua.get("row", "?")),
            ])
        ua_tbl = Table(ua_data, colWidths=[CONTENT_W * 0.6, CONTENT_W * 0.2, CONTENT_W * 0.2])
        ua_tbl.setStyle(TableStyle([
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("BACKGROUND",    (0, 0), (-1, 0),  HexColor("#0d1117")),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
            ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#cccccc")),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(ua_tbl)

    # Validation warnings footnote
    if warnings:
        elements.append(Spacer(1, 0.5 * cm))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#dddddd"), spaceAfter=6))
        elements.append(Paragraph(
            f"<b>Note:</b> {len(warnings)} score validation "
            f"discrepanc{'ies were' if len(warnings) != 1 else 'y was'} found. "
            "Review the full JSON report for details.",
            s_disclaimer,
        ))

    doc.build(elements, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
