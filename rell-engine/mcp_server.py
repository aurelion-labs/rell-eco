"""
mcp_server.py — RELL Compliance Engine MCP Server

Exposes RELL as a Model Context Protocol (MCP) tool server.
AI assistants (VS Code Copilot, Claude Desktop, Cursor) discover this
server and call RELL's audit tools without any HTTP client code.

Tools exposed
-------------
list_profiles()              List available compliance profiles
run_audit(profile_id)        Run a full audit cycle with the given profile
get_last_findings()          Return findings from the most recent audit run

Setup — VS Code Copilot (add to .vscode/mcp.json in this repo)
---------------------------------------------------------------
{
  "servers": {
    "rell-engine": {
      "type": "stdio",
      "command": "python",
      "args": ["${workspaceFolder}/rell-engine/mcp_server.py"]
    }
  }
}

Setup — Claude Desktop
----------------------
Add to ~/AppData/Roaming/Claude/claude_desktop_config.json:
{
  "mcpServers": {
    "rell-engine": {
      "command": "python",
      "args": ["C:/path/to/rell-engine/mcp_server.py"]
    }
  }
}

Usage in Copilot Chat
---------------------
"List all available compliance profiles"
"Run a GDPR audit on my data"
"What were the findings from the last audit?"

Requirements
------------
pip install mcp
(all other RELL deps already in requirements.txt)
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve paths relative to this file so the server works from any cwd
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
_ENGINE_DIR = _HERE / "engine"
_DATA_DIR = _HERE / "data" / "audit"
_PROFILES_DIR = _HERE / "profiles"
_REPORTS_DIR = _DATA_DIR / "memory" / "reports"

# Add engine directory to path so RELL modules are importable
sys.path.insert(0, str(_ENGINE_DIR))

# ---------------------------------------------------------------------------
# MCP server setup
# ---------------------------------------------------------------------------
from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP(
    "rell-engine",
    instructions=(
        "You have access to the RELL Compliance Audit Engine. "
        "Use list_profiles() to discover available regulations, then "
        "run_audit(profile_id) to audit datasets for compliance obligations. "
        "Use get_last_findings() to retrieve results from the previous run."
    ),
)


# ---------------------------------------------------------------------------
# Tool: list_profiles
# ---------------------------------------------------------------------------

@mcp.tool()
def list_profiles() -> str:
    """
    List all available RELL compliance profiles.

    Returns a JSON array. Each entry has:
      profile_id   Short ID used to invoke the profile (e.g. "gdpr-eu")
      standard     Full name of the regulation (e.g. "GDPR EU 2016/679")
      jurisdiction Where the regulation applies
      obligations  Number of audit checks bundled in the profile
    """
    results = []
    for path in sorted(_PROFILES_DIR.rglob("*.json")):
        if path.name == ".gitkeep":
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append({
                "profile_id": data.get("profile_id", path.stem),
                "standard": data.get("standard", ""),
                "jurisdiction": data.get("jurisdiction", ""),
                "obligations": len(data.get("obligations", [])),
            })
        except Exception as exc:
            results.append({"profile_id": path.stem, "error": str(exc)})

    if not results:
        return json.dumps({"message": "No profiles found. Check the profiles/ directory."})
    return json.dumps(results, indent=2)


# ---------------------------------------------------------------------------
# Tool: run_audit
# ---------------------------------------------------------------------------

@mcp.tool()
def run_audit(profile_id: str) -> str:
    """
    Run a RELL compliance audit using the specified profile.

    Scans all .txt files in data/audit/intake/txt/ against the selected
    compliance profile and returns a structured findings summary.

    Args:
        profile_id: The profile to audit against.
                    Use list_profiles() first to see all available options.
                    Examples: "gdpr-eu", "ccpa-ca"

    Returns:
        JSON summary with keys:
          profile       Profile ID, standard name, jurisdiction
          total         Total obligation findings raised
          critical      Count of CRITICAL severity findings
          high          Count of HIGH severity findings
          medium        Count of MEDIUM severity findings
          findings      Array of individual finding objects
          report_path   Path to the full Markdown report on disk
    """
    # Locate the profile JSON
    profile_dict: dict = {}
    for candidate in _PROFILES_DIR.rglob(f"{profile_id}.json"):
        with open(candidate, "r", encoding="utf-8") as f:
            profile_dict = json.load(f)
        break

    if not profile_dict:
        available = [p.stem for p in _PROFILES_DIR.rglob("*.json") if p.suffix == ".json"]
        return json.dumps({
            "error": f"Profile '{profile_id}' not found.",
            "available_profiles": available,
            "hint": "Call list_profiles() to see full details.",
        })

    # Ensure required directories exist
    (_DATA_DIR / "intake" / "txt").mkdir(parents=True, exist_ok=True)
    (_DATA_DIR / "memory" / "reports").mkdir(parents=True, exist_ok=True)

    # Import engine (lazy — only when a tool is called)
    from audit_engine import AuditEngine  # noqa: E402

    engine_obj = AuditEngine(
        data_path=str(_DATA_DIR),
        memory_path=str(_DATA_DIR / "memory"),
        llm_provider=None,
        compliance_profile=profile_dict,
    )

    # Suppress print() calls so they don't corrupt the MCP stdio channel
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            report = engine_obj.run_audit_cycle()
    except Exception as exc:
        return json.dumps({"error": f"Audit failed: {exc}", "details": buf.getvalue()})

    findings = report.get("findings", [])
    summary = {
        "profile": {
            "id": profile_id,
            "standard": profile_dict.get("standard", profile_id),
            "jurisdiction": profile_dict.get("jurisdiction", ""),
        },
        "total": len(findings),
        "critical": sum(1 for f in findings if f.get("severity") == "CRITICAL"),
        "high": sum(1 for f in findings if f.get("severity") == "HIGH"),
        "medium": sum(1 for f in findings if f.get("severity") == "MEDIUM"),
        "findings": findings,
        "report_path": report.get("output_files", {}).get("markdown_report", ""),
    }
    return json.dumps(summary, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool: get_last_findings
# ---------------------------------------------------------------------------

@mcp.tool()
def get_last_findings() -> str:
    """
    Return the findings from the most recent RELL audit run.

    Reads the latest JSON report from data/audit/memory/reports/.
    Returns an informative message if no audit has been run yet.

    Returns:
        JSON with keys:
          report_file     Filename of the report (for reference)
          cycle           Audit cycle number
          total_findings  Total number of findings
          critical / high / medium   Counts by severity
          findings        Full findings array
    """
    if not _REPORTS_DIR.exists() or not list(_REPORTS_DIR.glob("*.json")):
        return json.dumps({
            "message": "No audit reports found yet.",
            "hint": "Run run_audit(profile_id) to generate a report.",
        })

    latest = sorted(_REPORTS_DIR.glob("*.json"))[-1]
    with open(latest, "r", encoding="utf-8") as f:
        data = json.load(f)

    findings = data.get("findings", [])
    return json.dumps({
        "report_file": latest.name,
        "cycle": data.get("cycle", 1),
        "total_findings": len(findings),
        "critical": sum(1 for f in findings if f.get("severity") == "CRITICAL"),
        "high": sum(1 for f in findings if f.get("severity") == "HIGH"),
        "medium": sum(1 for f in findings if f.get("severity") == "MEDIUM"),
        "findings": findings,
    }, indent=2, default=str)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
