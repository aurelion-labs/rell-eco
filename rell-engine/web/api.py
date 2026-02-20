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

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
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

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# In-memory report store keyed by UUID report_id
_reports: dict = {}

# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def serve_index():
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
            profiles.append({
                "id":           data.get("profile_id", p.stem),
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
    Generate and download a PDF of a previously generated report.
    Requires reportlab: pip install reportlab
    """
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    from .pdf_export import generate_pdf  # lazy import — only needed when PDF is requested

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
