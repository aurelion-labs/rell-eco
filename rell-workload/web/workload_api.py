"""
Rell Workload Tracker — FastAPI Backend (Standalone)

Endpoints:
    GET  /login                       → Login page
    POST /login                       → Validate password, set session cookie
    GET  /                            → Serve the dashboard UI  (auth required)
    POST /api/upload                  → Upload a workload Excel file
    POST /api/workload/run            → Run a workload analysis
    GET  /api/report/{id}/workload-pdf → Download PDF report

Environment variables (set via `fly secrets set`):
    APP_PASSWORD   — password Josefina uses to log in
    SECRET_KEY     — random hex string used to sign session cookies (generate once)
"""
import os
import sys
import uuid
import json
import secrets
import asyncio
from io import BytesIO
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

# ---------------------------------------------------------------------------
# Auth config
# ---------------------------------------------------------------------------

_SECRET_KEY   = os.environ.get("SECRET_KEY", secrets.token_hex(32))
_APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

_signer        = TimestampSigner(_SECRET_KEY)
_COOKIE        = "rell_session"
_SESSION_AGE   = 8 * 3600   # seconds — re-login after 8 hours idle
_SECURE_COOKIE = bool(_APP_PASSWORD)  # True on fly.io (HTTPS), False in local dev

# Routes that are always public (no cookie required)
_PUBLIC_PATHS  = {"/login"}


def _is_authenticated(request: Request) -> bool:
    token = request.cookies.get(_COOKIE)
    if not token:
        return False
    try:
        _signer.unsign(token, max_age=_SESSION_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)
        if not _is_authenticated(request):
            return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Login page HTML (self-contained, no external dependencies)
# ---------------------------------------------------------------------------

_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Rell Workload — Sign In</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #0f1117;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .card {
      background: #1a1d27;
      border: 1px solid #2a2d3a;
      border-radius: 12px;
      padding: 40px 36px 36px;
      width: 360px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }
    .wordmark {
      font-size: 22px;
      font-weight: 700;
      color: #fff;
      letter-spacing: -0.5px;
      margin-bottom: 4px;
    }
    .wordmark span { color: #6c8ef5; }
    .subtitle {
      font-size: 13px;
      color: #6b7280;
      margin-bottom: 32px;
    }
    label {
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: #9ca3af;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 8px;
    }
    input[type="password"] {
      width: 100%;
      padding: 10px 14px;
      background: #0f1117;
      border: 1px solid #2a2d3a;
      border-radius: 8px;
      color: #e5e7eb;
      font-size: 15px;
      outline: none;
      transition: border-color 0.15s;
    }
    input[type="password"]:focus { border-color: #6c8ef5; }
    .error {
      margin-top: 12px;
      font-size: 13px;
      color: #f87171;
      display: {error_display};
    }
    button {
      margin-top: 24px;
      width: 100%;
      padding: 11px;
      background: #6c8ef5;
      color: #fff;
      border: none;
      border-radius: 8px;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
    }
    button:hover { background: #5a7de8; }
    button:active { background: #4d70d4; }
  </style>
</head>
<body>
  <div class="card">
    <div class="wordmark">rell<span>.</span>workload</div>
    <div class="subtitle">Feed Assignment Tracker</div>

    <form method="POST" action="/login" autocomplete="on">
      <label for="password">Access Password</label>
      <input type="password" id="password" name="password" placeholder="Enter password" autofocus />
      <div class="error">{error_msg}</div>
      <button type="submit">Sign In</button>
    </form>
  </div>
</body>
</html>"""

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
app.add_middleware(_AuthMiddleware)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return _LOGIN_HTML.replace("{error_display}", "none").replace("{error_msg}", "")


@app.post("/login")
async def login_submit(password: str = Form(...)):
    if not _APP_PASSWORD:
        raise HTTPException(status_code=500, detail="APP_PASSWORD is not configured on the server.")
    if not secrets.compare_digest(password, _APP_PASSWORD):
        html = _LOGIN_HTML.replace("{error_display}", "block").replace("{error_msg}", "Incorrect password. Try again.")
        return HTMLResponse(html, status_code=401)
    token = _signer.sign("ok").decode()
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(_COOKIE, token, httponly=True, samesite="lax", max_age=_SESSION_AGE, secure=_SECURE_COOKIE)
    return resp


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

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
