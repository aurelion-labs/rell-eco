"""
run_web.py — Launch the Rell Web Dashboard

Usage:
    python run_web.py
    python run_web.py --port 8080
    python run_web.py --host 0.0.0.0   # expose on local network
    python run_web.py --reload          # auto-reload on code changes (dev mode)

Then open http://127.0.0.1:8000 in your browser.

Non-technical managers: this is the face of Rell.
Upload a data file, pick a profile, click Run Audit, export PDF.
"""
import sys
import argparse
from pathlib import Path

# Ensure rell-engine/ is on the Python path when run directly
sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(
        description="Rell Web Dashboard — audit interface for non-technical users",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--host",   default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1 — local only)")
    parser.add_argument("--port",   type=int, default=8000,
                        help="Port (default: 8000)")
    parser.add_argument("--reload", action="store_true",
                        help="Auto-reload when source files change (dev mode)")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed.")
        print("Run:  pip install uvicorn")
        sys.exit(1)

    print("=" * 60)
    print("RELL — WEB DASHBOARD")
    print(f"URL:    http://{args.host}:{args.port}")
    print("Open the URL above in your browser.")
    if args.host == "127.0.0.1":
        print("(Only accessible from this machine.)")
    else:
        print("(Accessible from other devices on your network.)")
    print("=" * 60)
    print()

    uvicorn.run(
        "web.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
