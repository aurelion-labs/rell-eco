"""
Rell Web Dashboard — FastAPI Backend

Endpoints:
    GET  /                          → Serve the HTML dashboard
    GET  /api/profiles              → List available compliance profiles
    POST /api/upload                → Upload a data file to the intake folder
    POST /api/audit/run             → Run an audit cycle
    GET  /api/report/{id}           → Retrieve report JSON
    GET  /api/report/{id}/pdf       → Download report as PDF
"""
import sys
import uuid
import asyncio
from io import BytesIO
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from .gate import DemoGate, handle_login, login_page, _COOKIE
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Path setup — add rell-engine/ root so `import run_audit` works
# ---------------------------------------------------------------------------

RELL_ROOT = Path(__file__).parent.parent      # rell-engine/
sys.path.insert(0, str(RELL_ROOT))

import run_audit  # noqa: E402  (imports engine sub-modules via its own sys.path inserts)

# ---------------------------------------------------------------------------
# App init
# ---------------------------------------------------------------------------

app = FastAPI(title="Rell Audit Engine", version="0.1.0")
app.add_middleware(DemoGate)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# In-memory report store keyed by UUID report_id
_reports: dict = {}

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

from datetime import datetime, timezone  # noqa: E402

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "rell-engine",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def show_login():
    return login_page()


@app.post("/login")
async def do_login(request: Request):
    return await handle_login(request)


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(_COOKIE)
    return resp


@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Serve the single-page dashboard."""
    return (_STATIC_DIR / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------


@app.get("/api/profiles")
async def list_profiles():
    """Return all available compliance profiles with metadata."""
    import json
    profiles = []
    for p in sorted(run_audit.PROFILES_DIR.rglob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            p_type = data.get("type", "compliance")
            if p_type == "internal":
                continue   # housekeeping profiles — not shown in the UI
            profiles.append({
                "id":           data.get("profile_id", p.stem),
                "type":         p_type,
                "standard":     data.get("standard", ""),
                "jurisdiction": data.get("jurisdiction", ""),
                "obligations":  len(data.get("obligations", [])),
                "version":      data.get("version", ""),
            })
        except Exception:
            pass
    return {"profiles": profiles}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload a data file to the appropriate intake folder.
    .txt  → data/audit/intake/txt/
    .xlsx / .csv → data/audit/intake/excel/
    """
    filename = file.filename or "upload.dat"
    ext = Path(filename).suffix.lower()
    dest_dir = run_audit.EXCEL_INTAKE if ext in (".xlsx", ".csv") else run_audit.FLATFILE_INTAKE
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    dest.write_bytes(await file.read())
    return {"saved": filename, "path": str(dest), "intake_folder": str(dest_dir)}


class AuditRequest(BaseModel):
    profile_id: str
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None


class WorkloadRequest(BaseModel):
    filename: Optional[str] = None   # specific filename in intake, or None = auto-detect


@app.post("/api/workload/run")
async def run_workload_endpoint(req: WorkloadRequest):
    """
    Run a workload scan against a Workload Tracker .xlsx in the intake folder.
    If filename is omitted the most-recently-uploaded workload file is used.
    """
    from workload_engine import WorkloadAuditEngine

    # Locate the workbook
    intake = run_audit.EXCEL_INTAKE
    if req.filename:
        workbook_path = intake / req.filename
        if not workbook_path.exists():
            raise HTTPException(status_code=404, detail=f"File '{req.filename}' not found in intake folder.")
    else:
        candidates = sorted(
            list(intake.glob("*.xlsx")) + list(intake.glob("*.csv")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise HTTPException(status_code=404, detail="No workbook files found in intake folder. Upload one first.")
        workbook_path = candidates[0]

    scoring_config = run_audit.SCORING_CONFIG
    reports_path   = run_audit.FLATFILE_REPORTS

    engine = WorkloadAuditEngine(
        scoring_config_path=str(scoring_config) if scoring_config.exists() else None,
        reports_path=str(reports_path),
    )

    loop = asyncio.get_event_loop()
    try:
        report = await loop.run_in_executor(
            None,
            lambda: engine.scan_workbook(str(workbook_path)),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Workload scan error: {exc}")

    report_id = str(uuid.uuid4())
    _reports[report_id] = report
    return {"report_id": report_id, "report": report}


@app.post("/api/audit/run")
async def run_audit_endpoint(req: AuditRequest):
    """
    Run a full audit cycle with the specified profile.
    Returns a report_id and the full report dict.
    """
    profile = run_audit.load_profile(req.profile_id)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail=f"Profile '{req.profile_id}' not found. "
                   f"Run GET /api/profiles to see available options.",
        )

    loop = asyncio.get_event_loop()
    try:
        report = await loop.run_in_executor(
            None,
            lambda: run_audit.run(
                profile=profile,
                verbose=False,
                llm_provider=req.llm_provider or None,
                llm_model=req.llm_model or None,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Audit engine error: {exc}")

    report_id = str(uuid.uuid4())
    _reports[report_id] = report
    return {"report_id": report_id, "report": report}


@app.get("/api/report/{report_id}")
async def get_report(report_id: str):
    """Retrieve a previously generated report by ID."""
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    return report


@app.get("/api/report/{report_id}/pdf")
async def get_report_pdf(report_id: str):
    """
    Generate and download a compliance audit PDF for a previously generated report.
    Requires reportlab: pip install reportlab
    """
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    from .pdf_export import generate_pdf  # lazy import

    loop = asyncio.get_event_loop()
    try:
        pdf_bytes = await loop.run_in_executor(None, lambda: generate_pdf(report))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")

    filename = f"rell_audit_{report_id[:8]}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/report/{report_id}/workload-pdf")
async def get_workload_pdf(report_id: str):
    """
    Generate and download a workload distribution PDF for a previously generated workload report.
    """
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    from .pdf_export import generate_workload_pdf  # lazy import

    loop = asyncio.get_event_loop()
    try:
        pdf_bytes = await loop.run_in_executor(None, lambda: generate_workload_pdf(report))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Workload PDF generation failed: {exc}")

    safe_name = report.get("filename", "workload").replace(" ", "_").replace(".xlsx", "")
    filename  = f"rell_workload_{safe_name}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
