"""
Rell Workload Tracker — Server Launcher

Run this file to start the Workload Tracker web app.
The browser will open automatically at http://127.0.0.1:8000
"""
import sys
import time
import webbrowser
import threading
from pathlib import Path

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(ROOT / "engine"))

# ── Open browser after short delay ──────────────────────────────────────────
def _open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")

threading.Thread(target=_open_browser, daemon=True).start()

# ── Start server ─────────────────────────────────────────────────────────────
import uvicorn  # noqa: E402

if __name__ == "__main__":
    print("=" * 60)
    print("  RELL WORKLOAD TRACKER")
    print("  Starting at http://127.0.0.1:8000")
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    uvicorn.run(
        "workload_api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        app_dir=str(ROOT / "web"),
    )
