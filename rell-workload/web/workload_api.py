"""
Rell Workload Tracker — FastAPI Backend (Standalone)

Endpoints:
    GET  /                            → Serve the dashboard UI
    POST /api/upload                  → Upload a workload Excel file
    POST /api/workload/run            → Run a workload analysis
    GET  /api/report/{id}/workload-pdf → Download PDF report
"""
import sys
import uuid
import json
import asyncio
from io import BytesIO
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT       = Path(__file__).parent.parent           # rell-workload/
CONFIG_DIR = ROOT / "config"
INTAKE_DIR = ROOT / "data" / "intake"
ENGINE_DIR = ROOT / "engine"
STATIC_DIR = Path(__file__).parent / "static"

INTAKE_DIR.mkdir(parents=True, exist_ok=True)

# Add engine to path so workload_engine.py can import excel_parser
sys.path.insert(0, str(ENGINE_DIR))

from workload_engine import WorkloadAuditEngine  # noqa: E402

# ---------------------------------------------------------------------------
# Config loader — merge team-roster.json + scoring.json into engine format
# ---------------------------------------------------------------------------

def _load_engine_config() -> dict:
    """
    Reads config/team-roster.json (Josefina-editable) and config/scoring.json
    (admin-only) and merges them into the flat format WorkloadAuditEngine expects.
    Called fresh on each scan so config changes take effect without restarting.
    """
    roster_path  = CONFIG_DIR / "team-roster.json"
    scoring_path = CONFIG_DIR / "scoring.json"

    roster  = json.loads(roster_path.read_text(encoding="utf-8"))
    scoring = json.loads(scoring_path.read_text(encoding="utf-8"))

    # Strip admin comment keys from scoring (keys starting with _)
    weights = {k: v for k, v in scoring.items() if not k.startswith("_")}

    flags = roster.get("review_flags", {})

    return {
        **weights,
        "dqs_team":        roster.get("dqs_team",      {}).get("members", []),
        "other_teams":     roster.get("exclude_entirely", {}).get("members", []),
        "partial_data":    flags.get("partial_data",  {}).get("members", []),
        "departed":        flags.get("departed",       {}).get("members", []),
        "cross_collab":    flags.get("cross_collab",   {}).get("members", []),
        "other_roles":     flags.get("other_roles",    {}).get("members", []),
        "philippines_team": roster.get("ph_da_team",   {}).get("members", []),
        "name_aliases":    roster.get("name_aliases",  {}),
    }

# ---------------------------------------------------------------------------
# In-memory report store
# ---------------------------------------------------------------------------

_reports: dict = {}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Rell Workload Tracker", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Accept an uploaded Excel file and save it to the intake folder."""
    allowed = {".xlsx", ".csv"}
    suffix  = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Only .xlsx and .csv files are accepted. Got: {suffix}")

    dest = INTAKE_DIR / file.filename
    dest.write_bytes(await file.read())
    return {"saved": file.filename, "path": str(dest)}


# ---------------------------------------------------------------------------
# Workload scan
# ---------------------------------------------------------------------------

class WorkloadRequest(BaseModel):
    filename: Optional[str] = None   # specific filename, or None = auto-detect latest


@app.post("/api/workload/run")
async def run_workload(req: WorkloadRequest):
    """
    Run a workload analysis. Auto-detects the most-recently-uploaded Excel file
    if no filename is specified.
    """
    if req.filename:
        workbook_path = INTAKE_DIR / req.filename
        if not workbook_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"File '{req.filename}' not found. Upload it first.",
            )
    else:
        candidates = sorted(
            list(INTAKE_DIR.glob("*.xlsx")) + list(INTAKE_DIR.glob("*.csv")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise HTTPException(
                status_code=404,
                detail="No workbook files found. Drop an Excel file using the upload button first.",
            )
        workbook_path = candidates[0]

    # Reload config fresh on every scan (picks up any edits to team-roster.json)
    config = _load_engine_config()

    reports_dir = ROOT / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    engine = WorkloadAuditEngine(
        config=config,
        reports_path=str(reports_dir),
    )

    loop = asyncio.get_event_loop()
    try:
        report = await loop.run_in_executor(
            None, lambda: engine.scan_workbook(str(workbook_path))
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Workload scan error: {exc}")

    report_id = str(uuid.uuid4())
    _reports[report_id] = report
    return {"report_id": report_id, "report": report}


# ---------------------------------------------------------------------------
# Workload PDF
# ---------------------------------------------------------------------------

@app.get("/api/report/{report_id}/workload-pdf")
async def get_workload_pdf(report_id: str):
    """Download a PDF of the workload report."""
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found. Run the analysis first.")

    from workload_pdf import generate_workload_pdf  # noqa: E402  (lazy import)

    loop = asyncio.get_event_loop()
    try:
        pdf_bytes = await loop.run_in_executor(None, lambda: generate_workload_pdf(report))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")

    safe_name = report.get("filename", "workload").replace(" ", "_").replace(".xlsx", "")
    filename  = f"rell_workload_{safe_name}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
