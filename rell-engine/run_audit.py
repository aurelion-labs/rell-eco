"""
run_audit.py - Rell Autonomous Audit Engine — Entry Point

Usage:
    # Scan a single pipe-delimited flat file
    python run_audit.py --scan-file path/to/data.txt
    python run_audit.py --scan-file path/to/data.txt --feed-label MY_FEED

    # Sweep all .txt files in the intake folder
    python run_audit.py --scan-intake
    python run_audit.py --scan-intake path/to/custom/intake/
    python run_audit.py --scan-intake --archive

    # Scan an Excel or CSV workload tracker
    python run_audit.py --scan-workload
    python run_audit.py --scan-workload path/to/workload.xlsx

    # Ingest a SQL schema map (JSON export)
    python run_audit.py --ingest-schema path/to/schema_export.json
    python run_audit.py --schema-describe

    # Validate database credentials are read-only before live audits
    python run_audit.py --validate-creds

    # Run a full workflow audit cycle
    python run_audit.py
    python run_audit.py --workflow my_workflow_name

    # LLM-enhanced assessments (optional)
    python run_audit.py --llm openai
    python run_audit.py --llm openai --model gpt-4o
    python run_audit.py --llm ollama

    # Load a compliance profile
    python run_audit.py --profile gdpr-eu
    python run_audit.py --profile ccpa-california

Credential setup (environment variables):
    DB_CRED_<SERVER>_USER   = "rell_readonly"
    DB_CRED_<SERVER>_PASS   = "your_password"
    DB_CRED_<SERVER>_HOST   = "server.hostname.com"
    DB_CRED_<SERVER>_PORT   = "1433"
    DB_CRED_<SERVER>_ENGINE = "mssql"

    Replace <SERVER> with your server label (dashes -> underscores, uppercase).
    Example: PROD-SQL-01 -> DB_CRED_PROD_SQL_01_USER

Outputs:
    data/audit/memory/reports/   <- Markdown + JSON audit reports
    data/audit/memory/finding_logs/
    data/audit/memory/cycle_logs/
    data/audit/schema/           <- Schema maps and drift logs

See OPERATOR_GUIDE.md for full documentation.
"""

import sys
import json
import argparse
from pathlib import Path

# Resolve paths relative to this file
ENGINE_DIR         = Path(__file__).parent / "engine"
DATA_DIR           = Path(__file__).parent / "data" / "audit"
MEMORY_DIR         = DATA_DIR / "memory"
SCHEMA_DIR         = DATA_DIR / "schema"
CREDS_FILE         = DATA_DIR / "credentials.json"
ANOMALY_DIR        = DATA_DIR / "anomaly_patterns"
FLATFILE_INTAKE    = DATA_DIR / "intake" / "txt"
EXCEL_INTAKE       = DATA_DIR / "intake" / "excel"
FLATFILE_REPORTS   = MEMORY_DIR / "reports"
WORKLOAD_DIR       = DATA_DIR / "workload"
SCORING_CONFIG     = WORKLOAD_DIR / "scoring_config.json"
PROFILES_DIR       = Path(__file__).parent / "profiles"

# Add engine to Python path
sys.path.insert(0, str(ENGINE_DIR))

from audit_engine import AuditEngine          # noqa: E402
from audit_agent import WorkflowAuditAgent    # noqa: E402


# ---------------------------------------------------------------------------
# Profile loader
# ---------------------------------------------------------------------------

def load_profile(profile_id: str) -> dict:
    """
    Load a compliance profile by ID.
    Looks in: ./profiles/<category>/<profile_id>.json
    Falls back to searching all subdirectories.
    """
    # Search all profile directories
    for candidate in PROFILES_DIR.rglob(f"{profile_id}.json"):
        with open(candidate, "r", encoding="utf-8") as f:
            profile = json.load(f)
        print(f"[Profile] Loaded: {profile.get('standard', profile_id)} ({candidate.relative_to(PROFILES_DIR)})")
        return profile

    print(f"[Profile] Profile '{profile_id}' not found in {PROFILES_DIR}")
    print(f"  Available: run 'python run_audit.py --list-profiles' to see options")
    return {}


def cmd_list_profiles() -> None:
    """List all available profiles."""
    profiles = list(PROFILES_DIR.rglob("*.json"))
    if not profiles:
        print(f"No profiles found in {PROFILES_DIR}")
        print("Install rell-profiles or add profile JSON files to the profiles/ directory.")
        return

    print("Available profiles:")
    for p in sorted(profiles):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            pid = data.get("profile_id", p.stem)
            standard = data.get("standard", "")
            jurisdiction = data.get("jurisdiction", "")
            print(f"  {pid:<28} {standard} ({jurisdiction})")
        except Exception:
            print(f"  {p.stem}")


# ---------------------------------------------------------------------------
# Main audit run
# ---------------------------------------------------------------------------

def run(
    workflow_names=None,
    verbose=True,
    llm_provider=None,
    llm_api_key=None,
    llm_model=None,
    db_connections=None,
    creds_config_path=None,
    profile=None,
):
    """
    Run a full audit cycle.

    Args:
        workflow_names:    List of workflow names to run (None = all).
        verbose:           Print Rell's commentary to console.
        llm_provider:      "openai" | "claude" | "ollama" | None.
        llm_api_key:       API key string (or reads from env variable).
        llm_model:         Override default model (e.g. "gpt-4o").
        db_connections:    Dict of named SQLAlchemy connection strings.
        creds_config_path: Path to credentials.json.
        profile:           Profile dict from load_profile(), or None.

    Returns:
        Full report dict.
    """
    # Resolve credential config
    creds_path = creds_config_path or (str(CREDS_FILE) if CREDS_FILE.exists() else None)

    # Initialize engine
    engine = AuditEngine(
        data_path=str(DATA_DIR),
        memory_path=str(MEMORY_DIR),
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        db_connections=db_connections,
        schema_path=str(SCHEMA_DIR),
        creds_config_path=creds_path,
        compliance_profile=profile,
    )

    # Initialize Rell
    agent = WorkflowAuditAgent()
    if engine.schema_registry and engine.schema_registry.is_loaded():
        agent.orient_to_schema(engine.schema_registry)

    wf_display = workflow_names or ["all available workflows"]
    if verbose:
        print("=" * 70)
        print("RELL — AUTONOMOUS AUDIT ENGINE")
        print(f"Agent: {agent.name} — {agent.title}")
        mode = (
            f"LLM mode: {llm_provider}" + (f" ({llm_model})" if llm_model else "")
            if llm_provider else "mode: deterministic"
        )
        if profile:
            mode += f" | profile: {profile.get('profile_id', 'custom')}"
        print(f"Assessment {mode}")
        print("=" * 70)
        print()
        print(agent.begin_audit_session(wf_display))
        print()
        print("-" * 70)
        print()

    report = engine.run_audit_cycle(workflow_names=workflow_names)

    if verbose:
        _print_report(report, agent)

    return report


# ---------------------------------------------------------------------------
# Schema commands
# ---------------------------------------------------------------------------

def cmd_ingest_schema(source_path: str, captured_by: str = "operator") -> None:
    from sql_schema_registry import SqlSchemaRegistry, generate_credentials_template

    registry = SqlSchemaRegistry(str(SCHEMA_DIR))
    print(f"[Schema Ingest] Loading: {source_path}")
    result = registry.ingest_from_file(source_path, captured_by=captured_by)

    print()
    print("=" * 70)
    print("SCHEMA INGEST COMPLETE")
    print("=" * 70)
    print(f"Servers:   {', '.join(result['servers'])}")
    print(f"Databases: {result['databases']}")
    print(f"Tables:    {result['tables']}")
    print(f"Columns:   {result['columns']}")
    print(f"Captured:  {result['captured_at'][:19]}")
    print(f"Saved to:  {result['versioned_file']}")

    drift = result.get("drift", {})
    if drift.get("status") == "no_baseline":
        print("\nFirst schema ingested. No baseline to compare.")
    elif drift.get("status") == "no_drift":
        print("\nNo schema drift detected.")
    else:
        print("\nSCHEMA DRIFT DETECTED:")
        print(f"  {drift.get('summary', '')}")

    template_path = str(DATA_DIR / "credentials.template.json")
    generate_credentials_template(registry, template_path)
    print(f"\nCredentials template: {template_path}")

    agent = WorkflowAuditAgent()
    agent.orient_to_schema(registry)
    print()
    print(registry.describe_for_rell())


def cmd_schema_describe() -> None:
    from sql_schema_registry import SqlSchemaRegistry

    registry = SqlSchemaRegistry(str(SCHEMA_DIR))
    schema = registry.load()
    if not schema:
        print("No schema loaded. Run: python run_audit.py --ingest-schema <path>")
        return

    agent = WorkflowAuditAgent()
    agent.orient_to_schema(registry)
    print(registry.describe_for_rell())
    print()
    print("-" * 70)
    for srv_name, srv_data in schema.get("servers", {}).items():
        print(f"\nServer: {srv_name}  ({srv_data.get('engine','unknown')} @ {srv_data.get('host',srv_name)})")
        for db_name, db_data in srv_data.get("databases", {}).items():
            tables = db_data.get("tables", {})
            print(f"  Database: {db_name}  ({len(tables)} tables)")
            for tbl, tbl_data in tables.items():
                cols = len(tbl_data.get("columns", {}))
                rows = tbl_data.get("row_count_estimate")
                row_str = f"  ~{rows:,} rows" if rows else ""
                print(f"    {tbl}  ({cols} columns{row_str})")


# ---------------------------------------------------------------------------
# Flat file commands
# ---------------------------------------------------------------------------

def cmd_scan_file(filepath: str, feed_label: str = None) -> dict:
    from flatfile_parser import FlatFileAuditEngine

    audit = FlatFileAuditEngine(
        patterns_path=str(ANOMALY_DIR),
        reports_path=str(FLATFILE_REPORTS),
    )
    print()
    print("=" * 70)
    print("RELL — FLAT FILE AUDIT")
    print("=" * 70)
    print()
    report = audit.scan_file(filepath, feed_label=feed_label)

    print()
    print("RELL'S ASSESSMENT:")
    print()
    print(report.get("rell_assessment", ""))
    print()
    summary = report.get("summary", {})
    print(f"Records scanned : {summary.get('record_count', 0):,}")
    print(f"Findings        : {summary.get('finding_count', 0):,}")
    by_sev = summary.get("by_severity", {})
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        cnt = by_sev.get(sev, 0)
        if cnt:
            labels = {"CRITICAL": "[!!!]", "HIGH": "[!! ]", "MEDIUM": "[!  ]", "LOW": "[.  ]"}
            print(f"  {labels[sev]} {sev}: {cnt}")
    output_files = report.get("output_files", {})
    if output_files:
        print("\nReports written:")
        for path in output_files.values():
            print(f"  {path}")
    print()
    return report


def cmd_scan_intake(intake_path: str = None, archive: bool = False) -> list:
    from flatfile_parser import FlatFileAuditEngine

    intake = intake_path or str(FLATFILE_INTAKE)
    audit = FlatFileAuditEngine(
        patterns_path=str(ANOMALY_DIR),
        reports_path=str(FLATFILE_REPORTS),
    )
    print()
    print("=" * 70)
    print("RELL — FLAT FILE INTAKE SWEEP")
    print(f"Intake: {intake}")
    print("=" * 70)
    print()
    all_reports = audit.scan_intake_folder(intake, archive=archive)
    total_records  = sum(r.get("record_count", 0) for r in all_reports)
    total_findings = sum(r.get("finding_count", 0) for r in all_reports)
    print(f"\nFiles scanned   : {len(all_reports)}")
    print(f"Records total   : {total_records:,}")
    print(f"Findings total  : {total_findings:,}\n")
    return all_reports


# ---------------------------------------------------------------------------
# Workload commands
# ---------------------------------------------------------------------------

def cmd_scan_workload(
    workbook_path: str = None,
    sheet_name: str = None,
    incoming_feed: dict = None,
) -> dict:
    from workload_engine import WorkloadAuditEngine

    if not workbook_path:
        excel_files = list(EXCEL_INTAKE.glob("*.xlsx")) + list(EXCEL_INTAKE.glob("*.csv"))
        if not excel_files:
            print(f"No workbook files found in {EXCEL_INTAKE}")
            return {}
        workbook_path = str(excel_files[0])

    engine = WorkloadAuditEngine(
        scoring_config_path=str(SCORING_CONFIG),
        reports_path=str(FLATFILE_REPORTS),
    )
    print()
    print("=" * 70)
    print("RELL — WORKLOAD TRACKER AUDIT")
    print("=" * 70)
    print()
    report = engine.scan_workbook(workbook_path, sheet_name=sheet_name, incoming_feed=incoming_feed)

    print()
    print("RELL'S ASSESSMENT:")
    print()
    print(report.get("rell_assessment", ""))
    print()
    stats    = report.get("team_stats", {})
    summaries = report.get("analyst_summaries", {})
    print(f"Feeds scored    : {stats.get('feed_count', 0)}")
    print(f"Analysts        : {stats.get('analyst_count', 0)}")
    print(f"Team total pts  : {stats.get('total_team_points', 0):.2f}")
    print(f"Avg per analyst : {stats.get('average_points_per_analyst', 0):.2f}\n")
    for analyst, s in sorted(summaries.items(), key=lambda x: -x[1]["total_points"]):
        status = s.get("load_status", "UNKNOWN")
        lbl = {"OVERLOADED": "[!!!]", "UNDERLOADED": "[.  ]", "BALANCED": "[ + ]"}.get(status, "    ")
        dev = s.get("deviation_from_avg_pct", 0)
        dev_str = f"+{dev:.1f}%" if dev >= 0 else f"{dev:.1f}%"
        print(f"  {lbl} {analyst:<16} {s['total_points']:6.2f} pts  {s['feed_count']:3} feeds  ({dev_str} vs avg)")
    output_files = report.get("output_files", {})
    if output_files:
        print("\nReports written:")
        for path in output_files.values():
            print(f"  {path}")
    print()
    return report


# ---------------------------------------------------------------------------
# Credential validation
# ---------------------------------------------------------------------------

def cmd_validate_creds() -> None:
    from sql_schema_registry import SqlSchemaRegistry, CredentialManager

    registry = SqlSchemaRegistry(str(SCHEMA_DIR))
    registry.load()
    creds_path = str(CREDS_FILE) if CREDS_FILE.exists() else None
    cred_mgr = CredentialManager(creds_config_path=creds_path, audit_log_path=str(SCHEMA_DIR))

    print("=" * 70)
    print("CREDENTIAL VALIDATION")
    print("=" * 70)
    configured = cred_mgr.list_configured_servers()
    if not configured:
        print("No credentials found.")
        print("Set DB_CRED_<SERVER>_USER / _PASS env vars or create data/audit/credentials.json")
        return

    print(f"Credentials configured for: {configured}\n")
    if not registry.is_loaded():
        print("Schema not loaded — run --ingest-schema first, then --validate-creds.")
        return

    connections = cred_mgr.build_connections_for_all_servers(registry)
    from audit_engine import DatabaseConnector
    connector = DatabaseConnector(connections)
    print("Testing connections (read-only check):\n")
    for conn_name in connections:
        test = connector.test_connection(conn_name)
        if test["status"] == "ok":
            ro = cred_mgr.validate_readonly(conn_name, connector)
            status_str = "[OK - READ ONLY]" if ro["readonly"] else "[FAIL - HAS WRITE ACCESS]"
            print(f"  {conn_name}: {status_str}")
            if not ro["readonly"]:
                print(f"    !! {ro['message']}")
        else:
            print(f"  {conn_name}: [CONNECTION FAILED] {test.get('error','')[:80]}")
    print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_report(report: dict, agent: WorkflowAuditAgent):
    summary  = report.get("summary", {})
    findings = report.get("findings", [])
    cycle    = report.get("cycle", 0)
    print(f"CYCLE {cycle} COMPLETE")
    print(f"Workflows audited: {', '.join(report.get('workflows_audited', []))}")
    print(f"Total findings:    {summary.get('total_findings', 0)}\n")
    by_sev = summary.get("by_severity", {})
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
        cnt = by_sev.get(sev, 0)
        if cnt:
            lbl = {"CRITICAL": "[!!!]", "HIGH": "[!! ]", "MEDIUM": "[!  ]", "LOW": "[.  ]", "INFO": "[   ]"}
            print(f"  {lbl.get(sev,'    ')} {sev}: {cnt}")
    print()
    print("-" * 70)
    print()
    print("RELL'S ASSESSMENT:\n")
    print(report.get("rell_opening", ""))
    print()
    if findings:
        print("-" * 70)
        print(f"\nFINDINGS ({len(findings)}):\n")
        for finding in findings:
            print(agent.interpret_finding(finding))
            print()
    print("-" * 70)
    print()
    print(report.get("rell_closing", ""))
    print()
    print("-" * 70)
    print()
    for label, path in report.get("output_files", {}).items():
        print(f"  {label}: {path}")
    if report.get("output_files"):
        print()


def _load_kb(path):
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="rell",
        description="Rell — Autonomous Audit Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Operation modes
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scan-file",    metavar="PATH", help="Scan a single flat file")
    mode.add_argument("--scan-intake",  metavar="PATH", nargs="?", const=True, help="Sweep flat file intake folder")
    mode.add_argument("--scan-workload",metavar="PATH", nargs="?", const=True, help="Scan workload tracker")
    mode.add_argument("--ingest-schema",metavar="PATH", help="Ingest a SQL schema JSON export")
    mode.add_argument("--schema-describe", action="store_true", help="Show Rell's schema knowledge")
    mode.add_argument("--validate-creds",  action="store_true", help="Validate read-only DB credentials")
    mode.add_argument("--list-profiles",   action="store_true", help="List available compliance profiles")

    # Options
    parser.add_argument("--workflow",   metavar="NAME", help="Run a specific workflow only")
    parser.add_argument("--feed-label", metavar="LABEL", help="Label for flat file feed")
    parser.add_argument("--archive",    action="store_true", help="Archive processed intake files")
    parser.add_argument("--profile",    metavar="ID", help="Load a compliance profile (e.g. gdpr-eu)")
    parser.add_argument("--llm",        metavar="PROVIDER", help="LLM provider: openai | claude | ollama")
    parser.add_argument("--model",      metavar="NAME", help="Override LLM model name")
    parser.add_argument("--assign-feed",metavar="NAME", help="Register new incoming feed for workload scoring")
    parser.add_argument("--volume",     type=int, metavar="N", help="Feed volume for --assign-feed")
    parser.add_argument("--frequency",  metavar="FREQ", help="Feed frequency for --assign-feed")
    parser.add_argument("--time-minutes",type=int, metavar="N", help="Processing time for --assign-feed")
    parser.add_argument("--state",      metavar="ST", help="State code for --assign-feed")
    parser.add_argument("--db-conn",    metavar="KEY=DSN", help="Explicit DB connection string for schema ingest")
    parser.add_argument("--captured-by",metavar="USER", default="operator", help="Operator name for schema ingest")

    args = parser.parse_args()

    # Load profile if requested
    profile = None
    if args.profile:
        profile = load_profile(args.profile)

    if args.list_profiles:
        cmd_list_profiles()

    elif args.scan_file:
        cmd_scan_file(args.scan_file, feed_label=args.feed_label)

    elif args.scan_intake is not None:
        path = args.scan_intake if isinstance(args.scan_intake, str) else None
        cmd_scan_intake(intake_path=path, archive=args.archive)

    elif args.scan_workload is not None:
        path = args.scan_workload if isinstance(args.scan_workload, str) else None
        incoming = None
        if args.assign_feed:
            incoming = {
                "feed_name": args.assign_feed,
                "volume": args.volume,
                "frequency": args.frequency,
                "processing_time_minutes": args.time_minutes,
                "state": args.state,
            }
        cmd_scan_workload(workbook_path=path, incoming_feed=incoming)

    elif args.ingest_schema:
        cmd_ingest_schema(args.ingest_schema, captured_by=args.captured_by)

    elif args.schema_describe:
        cmd_schema_describe()

    elif args.validate_creds:
        cmd_validate_creds()

    else:
        # Default: full audit cycle
        workflow_names = [args.workflow] if args.workflow else None
        run(
            workflow_names=workflow_names,
            llm_provider=args.llm,
            llm_model=args.model,
            profile=profile,
        )


if __name__ == "__main__":
    main()
