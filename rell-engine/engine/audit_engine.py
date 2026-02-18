"""
audit_engine.py - Autonomous Workflow Audit Engine

The same simulation loop that drives Stonecrest forward—repurposed to drive
workflow audits forward.  Instead of regions and factions, we have workflows
and systems.  Instead of Seraphine's death, we have inconsistencies that need
to be named.

Rell's voice still runs the analysis.  The library is still the source.
The world just changed.

Architecture mirrors simulate.py:
  1. Load workflow state
  2. Check inconsistency triggers
  3. Evaluate system behaviors
  4. Calculate findings
  5. Update audit memory
  6. Advance audit cycle
  7. Save state + write reports
"""

import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Audit State Manager
# ---------------------------------------------------------------------------

class AuditStateManager:
    """
    Manages workflow definitions, system state, and audit flags.
    Mirrors StateManager from the Stonecrest engine.

    data_path/
      workflows/   <- workflow definition JSON files
      systems/     <- system/process state JSON files
      state/       <- overall audit world state
    """

    def __init__(self, data_path: str):
        self.data_path = Path(data_path)
        self.workflows_path = self.data_path / "workflows"
        self.systems_path = self.data_path / "systems"
        self.state_path = self.data_path / "state"

        # Auto-create directories so first run doesn't crash
        for p in [self.workflows_path, self.systems_path, self.state_path]:
            p.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Audit World State
    # ------------------------------------------------------------------

    def load_audit_state(self) -> Dict[str, Any]:
        """Load the current audit world state (or bootstrap a fresh one)."""
        state_file = self.state_path / "audit_state.json"
        if not state_file.exists():
            return self._bootstrap_state()
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_audit_state(self, state: Dict[str, Any]) -> None:
        state_file = self.state_path / "audit_state.json"
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def _bootstrap_state(self) -> Dict[str, Any]:
        """Create a fresh audit world state."""
        return {
            "cycle": 1,
            "started": datetime.now().isoformat(),
            "last_run": None,
            "global_flags": {},
            "systems": {},
            "summary": {
                "total_cycles": 0,
                "total_findings": 0,
                "open_findings": 0,
                "resolved_findings": 0
            }
        }

    def advance_cycle(self, state: Dict[str, Any]) -> None:
        state["cycle"] = state.get("cycle", 0) + 1
        state["last_run"] = datetime.now().isoformat()
        state["summary"]["total_cycles"] = state["cycle"]

    # ------------------------------------------------------------------
    # Workflow Definitions
    # ------------------------------------------------------------------

    def load_workflow(self, workflow_name: str) -> Dict[str, Any]:
        """Load a workflow definition JSON."""
        wf_file = self.workflows_path / f"{workflow_name}.json"
        if not wf_file.exists():
            raise FileNotFoundError(
                f"Workflow definition not found: {wf_file}\n"
                f"Create it under {self.workflows_path}"
            )
        with open(wf_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_all_workflows(self) -> Dict[str, Dict[str, Any]]:
        """Load all workflow definitions."""
        workflows = {}
        for wf_file in self.workflows_path.glob("*.json"):
            with open(wf_file, "r", encoding="utf-8") as f:
                wf = json.load(f)
                workflows[wf_file.stem] = wf
        return workflows

    # ------------------------------------------------------------------
    # System State
    # ------------------------------------------------------------------

    def load_system(self, system_name: str) -> Dict[str, Any]:
        """Load current state snapshot of a system/process."""
        sys_file = self.systems_path / f"{system_name}.json"
        if not sys_file.exists():
            return {"name": system_name, "status": "unknown", "flags": {}, "metrics": {}}
        with open(sys_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_system(self, system: Dict[str, Any]) -> None:
        name = system.get("name", "unnamed").lower().replace(" ", "_")
        sys_file = self.systems_path / f"{name}.json"
        with open(sys_file, "w", encoding="utf-8") as f:
            json.dump(system, f, indent=2, ensure_ascii=False)

    def calculate_system_health(self, system: Dict[str, Any]) -> float:
        """
        Return a 0.0–1.0 health score for a system.
        Mirrors calculate_region_stability in the Stonecrest engine.
        """
        metrics = system.get("metrics", {})
        if not metrics:
            return 1.0  # Unknown = assume healthy until proven otherwise

        scores = []
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                # Normalize: assume values are 0-100 percentage-style unless flagged
                scores.append(min(max(float(value) / 100.0, 0.0), 1.0))

        return sum(scores) / len(scores) if scores else 1.0


# ---------------------------------------------------------------------------
# Audit Memory Manager
# ---------------------------------------------------------------------------

class AuditMemoryManager:
    """
    Persists audit findings, Rell's observations, and world logs.
    Mirrors MemoryManager from the Stonecrest engine.

    base_path/
      finding_logs/   <- per-workflow finding journals
      cycle_logs/     <- per-cycle world summary logs
      reports/        <- final markdown + JSON reports
    """

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.finding_logs_path = self.base_path / "finding_logs"
        self.cycle_logs_path = self.base_path / "cycle_logs"
        self.reports_path = self.base_path / "reports"

        for p in [self.finding_logs_path, self.cycle_logs_path, self.reports_path]:
            p.mkdir(parents=True, exist_ok=True)

    def append_finding(self, workflow_name: str, finding: Dict[str, Any]) -> None:
        """Log a finding to the workflow's finding journal."""
        journal = self.finding_logs_path / f"{workflow_name}_findings.md"
        entry = self._format_finding_entry(finding)
        with open(journal, "a", encoding="utf-8") as f:
            f.write(entry)

    def append_cycle_log(self, cycle: int, entry: str) -> None:
        """Log a cycle summary."""
        log_path = self.cycle_logs_path / f"cycle_{cycle:04d}_log.md"
        if not log_path.exists():
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"# Audit Cycle {cycle} Log\n\n")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{entry}\n")

    def write_markdown_report(self, cycle: int, report: Dict[str, Any]) -> Path:
        """Write a full markdown audit report."""
        report_path = self.reports_path / f"audit_report_cycle_{cycle:04d}.md"
        content = self._format_markdown_report(report)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)
        return report_path

    def write_json_report(self, cycle: int, report: Dict[str, Any]) -> Path:
        """Write a structured JSON audit report."""
        json_path = self.reports_path / f"audit_report_cycle_{cycle:04d}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return json_path

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_finding_entry(self, finding: Dict[str, Any]) -> str:
        severity = finding.get("severity", "INFO")
        icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}.get(severity, "⚪")
        return (
            f"\n---\n\n"
            f"### {icon} [{severity}] {finding.get('title', 'Untitled Finding')}\n\n"
            f"**Workflow:** {finding.get('workflow', 'Unknown')}  \n"
            f"**Step:** {finding.get('step', 'N/A')}  \n"
            f"**Detected:** {finding.get('timestamp', datetime.now().isoformat())}  \n\n"
            f"**Observation:**  \n{finding.get('observation', '')}\n\n"
            f"**Rell's Assessment:**  \n{finding.get('rell_assessment', '')}\n\n"
            f"**Suggested Fix:**  \n{finding.get('suggested_fix', 'No suggestion yet.')}\n\n"
            f"**Status:** {finding.get('status', 'OPEN')}\n"
        )

    def _format_markdown_report(self, report: Dict[str, Any]) -> str:
        cycle = report.get("cycle", 0)
        ts = report.get("timestamp", datetime.now().isoformat())
        findings = report.get("findings", [])
        summary = report.get("summary", {})

        lines = [
            f"# Audit Report — Cycle {cycle}",
            f"",
            f"**Generated:** {ts}  ",
            f"**Workflows Audited:** {summary.get('workflows_audited', 0)}  ",
            f"**Total Findings:** {len(findings)}  ",
            f"**Critical:** {sum(1 for f in findings if f.get('severity') == 'CRITICAL')}  ",
            f"**High:** {sum(1 for f in findings if f.get('severity') == 'HIGH')}  ",
            f"**Medium:** {sum(1 for f in findings if f.get('severity') == 'MEDIUM')}  ",
            f"",
            f"---",
            f"",
            f"## Rell's Opening Observation",
            f"",
            f"{report.get('rell_opening', '')}",
            f"",
            f"---",
            f"",
            f"## Findings",
            f"",
        ]

        if not findings:
            lines.append("*No inconsistencies detected this cycle.*")
        else:
            for i, finding in enumerate(findings, 1):
                severity = finding.get("severity", "INFO")
                icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}.get(severity, "⚪")
                lines += [
                    f"### {i}. {icon} [{severity}] {finding.get('title', 'Untitled')}",
                    f"",
                    f"**Workflow:** `{finding.get('workflow', 'Unknown')}`  ",
                    f"**Step:** `{finding.get('step', 'N/A')}`  ",
                    f"",
                    f"**Observation:**  ",
                    f"{finding.get('observation', '')}",
                    f"",
                    f"**Rell's Assessment:**  ",
                    f"{finding.get('rell_assessment', '')}",
                    f"",
                    f"**Suggested Fix:**  ",
                    f"{finding.get('suggested_fix', 'Under investigation.')}",
                    f"",
                    f"**Status:** `{finding.get('status', 'OPEN')}`",
                    f"",
                    f"---",
                    f"",
                ]

        lines += [
            f"## Rell's Closing Observation",
            f"",
            f"{report.get('rell_closing', '')}",
            f"",
        ]

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Audit Trigger Checker
# ---------------------------------------------------------------------------

class AuditTriggerChecker:
    """
    Evaluates whether a workflow step has an inconsistency.
    Mirrors _check_trigger_conditions from simulate.py.

    Built-in trigger types (extensible):
      missing_field     - required field absent in system state
      value_below       - metric below threshold
      value_above       - metric above threshold
      flag_not_set      - expected global flag not present
      flag_set          - unexpected global flag present
      stale_data        - last_updated older than max_age_days
      cross_ref_missing - referenced file/record not found
    """

    def check(
        self,
        trigger: Dict[str, Any],
        system_state: Dict[str, Any],
        audit_state: Dict[str, Any],
        knowledge_base: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Return True when an inconsistency IS detected (trigger fires).
        """
        trigger_type = trigger.get("type")

        if trigger_type == "missing_field":
            field = trigger.get("field")
            return not system_state.get(field)

        if trigger_type == "value_below":
            field = trigger.get("field")
            threshold = trigger.get("threshold", 0)
            value = self._nested_get(system_state, field)
            return isinstance(value, (int, float)) and value < threshold

        if trigger_type == "value_above":
            field = trigger.get("field")
            threshold = trigger.get("threshold", 100)
            value = self._nested_get(system_state, field)
            return isinstance(value, (int, float)) and value > threshold

        if trigger_type == "flag_not_set":
            flag = trigger.get("flag")
            return not audit_state.get("global_flags", {}).get(flag, False)

        if trigger_type == "flag_set":
            flag = trigger.get("flag")
            return audit_state.get("global_flags", {}).get(flag, False)

        if trigger_type == "stale_data":
            field = trigger.get("field", "last_updated")
            max_age_days = trigger.get("max_age_days", 30)
            value = self._nested_get(system_state, field)
            if not value:
                return True  # No timestamp = stale by definition
            try:
                last_updated = datetime.fromisoformat(str(value))
                age = (datetime.now() - last_updated).days
                return age > max_age_days
            except (ValueError, TypeError):
                return True  # Unparseable date = treat as stale

        if trigger_type == "cross_ref_missing":
            ref_path = trigger.get("ref_path")
            if not ref_path:
                return False
            return not Path(ref_path).exists()

        if trigger_type in ("sql_query", "sql_field_population"):
            # SQL triggers require a DatabaseConnector injected at check time.
            # The connector is passed via knowledge_base["_db_connector"] by AuditEngine.
            connector = (knowledge_base or {}).get("_db_connector")
            if connector is None:
                # No connector configured — skip silently (don't false-fire)
                return False
            return self._check_sql_trigger(trigger, connector)

        # Unknown trigger type — log but don't fire
        return False

    def _check_sql_trigger(
        self,
        trigger: Dict[str, Any],
        connector: "DatabaseConnector"
    ) -> bool:
        """
        Execute SQL-based triggers.

        sql_query trigger keys:
          connection    - named connection key (matches DatabaseConnector config)
          query         - SQL to execute; must return a single scalar value
          expected_min  - (optional) fire if result < expected_min
          expected_max  - (optional) fire if result > expected_max
          expected_eq   - (optional) fire if result != expected_eq

        sql_field_population trigger keys:
          connection       - named connection key
          query            - SQL returning (field_name, populated_count, total_count)
          threshold_pct    - fire if population_pct < threshold_pct (default 90)
          escalate_pct     - secondary threshold for HIGH vs MEDIUM severity override
        """
        trigger_type = trigger.get("type")
        connection_name = trigger.get("connection", "default")

        try:
            if trigger_type == "sql_query":
                result = connector.scalar(connection_name, trigger["query"])
                if result is None:
                    return trigger.get("fire_on_null", False)

                expected_min = trigger.get("expected_min")
                expected_max = trigger.get("expected_max")
                expected_eq = trigger.get("expected_eq")

                if expected_min is not None and float(result) < float(expected_min):
                    trigger["_sql_result"] = result
                    trigger["_sql_direction"] = "below_min"
                    return True
                if expected_max is not None and float(result) > float(expected_max):
                    trigger["_sql_result"] = result
                    trigger["_sql_direction"] = "above_max"
                    return True
                if expected_eq is not None and result != expected_eq:
                    trigger["_sql_result"] = result
                    trigger["_sql_direction"] = "not_equal"
                    return True
                return False

            if trigger_type == "sql_field_population":
                # Query must return rows of (field_name, populated_count, total_count)
                rows = connector.fetchall(connection_name, trigger["query"])
                threshold = float(trigger.get("threshold_pct", 90.0))
                violations = []
                for row in rows:
                    field_name, populated, total = row[0], row[1], row[2]
                    if total == 0:
                        continue
                    pct = (populated / total) * 100.0
                    if pct < threshold:
                        violations.append({
                            "field": field_name,
                            "populated": populated,
                            "total": total,
                            "pct": round(pct, 2)
                        })
                if violations:
                    trigger["_population_violations"] = violations
                    return True
                return False

        except Exception as e:
            # Surface DB errors as findings so they don't silently disappear
            trigger["_sql_error"] = str(e)
            return trigger.get("fire_on_error", True)

        return False

    @staticmethod
    def _nested_get(d: Dict, key: str, default=None):
        """Dot-notation nested dict access: 'metrics.completion_rate'"""
        if not key:
            return default
        parts = key.split(".")
        current = d
        for part in parts:
            if not isinstance(current, dict):
                return default
            current = current.get(part)
        return current if current is not None else default


# ---------------------------------------------------------------------------
# Database Connector
# ---------------------------------------------------------------------------

class DatabaseConnector:
    """
    Thin database abstraction layer for SQL-based audit triggers.

    Supports any database accessible via SQLAlchemy connection strings,
    including SQL Server (pyodbc), PostgreSQL (psycopg2), MySQL, SQLite,
    and any other SQLAlchemy-compatible backend.

    Configuration:
        Pass a dict of named connections to __init__:
        {
            "default": "mssql+pyodbc://user:pass@server/db?driver=ODBC+Driver+17+for+SQL+Server",
            "feed_db": "postgresql://user:pass@host:5432/feed_database",
            "local":   "sqlite:///path/to/local.db"
        }

        Or load connection strings from environment variables by prefixing
        connection names with DB_CONN_:
            DB_CONN_DEFAULT=mssql+pyodbc://...
            DB_CONN_FEED_DB=postgresql://...

    The connector is injected into AuditTriggerChecker via the knowledge_base
    dict under the key "_db_connector". AuditEngine handles this automatically
    when connections are provided at initialization.

    Usage in workflow trigger definitions:
        {
            "type": "sql_query",
            "connection": "feed_db",
            "query": "SELECT COUNT(*) FROM Cases WHERE FilingDate >= DATEADD(day,-7,GETDATE())",
            "expected_min": 100,
            ...
        }
    """

    def __init__(self, connections: Optional[Dict[str, str]] = None):
        """
        Args:
            connections: Dict mapping connection name -> SQLAlchemy URL string.
                         If None, loads from DB_CONN_* environment variables.
        """
        self._connections = {}
        self._engines = {}

        # Load from argument
        if connections:
            self._connections.update(connections)

        # Also load from environment (DB_CONN_NAME=url)
        for key, value in os.environ.items():
            if key.startswith("DB_CONN_"):
                name = key[len("DB_CONN_"):].lower()
                if name not in self._connections:
                    self._connections[name] = value

    def has_connections(self) -> bool:
        return bool(self._connections)

    def _get_engine(self, connection_name: str):
        """Lazy-initialize SQLAlchemy engine for a named connection."""
        if connection_name not in self._engines:
            url = self._connections.get(connection_name)
            if not url:
                raise ValueError(
                    f"No connection string configured for '{connection_name}'. "
                    f"Available: {list(self._connections.keys())}. "
                    f"Set DB_CONN_{connection_name.upper()}=<sqlalchemy_url> or pass connections dict."
                )
            try:
                from sqlalchemy import create_engine
                self._engines[connection_name] = create_engine(url)
            except ImportError:
                raise ImportError(
                    "SQLAlchemy is required for SQL audit triggers. "
                    "Install it with: pip install sqlalchemy\n"
                    "For SQL Server: pip install sqlalchemy pyodbc\n"
                    "For PostgreSQL: pip install sqlalchemy psycopg2-binary\n"
                    "For MySQL:      pip install sqlalchemy pymysql"
                )
        return self._engines[connection_name]

    def scalar(self, connection_name: str, query: str, params: Optional[Dict] = None):
        """
        Execute a query and return a single scalar value.
        Ideal for COUNT(*), SUM(), AVG(), MAX() queries.

        Example:
            connector.scalar("feed_db", "SELECT COUNT(*) FROM Cases WHERE IsActive=1")
        """
        from sqlalchemy import text
        engine = self._get_engine(connection_name)
        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            row = result.fetchone()
            return row[0] if row else None

    def fetchall(self, connection_name: str, query: str, params: Optional[Dict] = None) -> list:
        """
        Execute a query and return all rows as a list of tuples.
        Used for field population checks and multi-row analysis.

        Example:
            connector.fetchall("feed_db",
                "SELECT 'DefendantFirstName', SUM(CASE WHEN DefendantFirstName IS NOT NULL THEN 1 ELSE 0 END), COUNT(*) FROM Cases")
        """
        from sqlalchemy import text
        engine = self._get_engine(connection_name)
        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            return result.fetchall()

    def fetchone(self, connection_name: str, query: str, params: Optional[Dict] = None):
        """
        Execute a query and return the first row.

        Example:
            connector.fetchone("feed_db", "SELECT TOP 1 * FROM Cases WHERE CaseNumber = :cn", {"cn": "2024CV001"})
        """
        from sqlalchemy import text
        engine = self._get_engine(connection_name)
        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            return result.fetchone()

    def test_connection(self, connection_name: str) -> Dict[str, Any]:
        """
        Test that a named connection is reachable. Returns a status dict.
        Safe to call at audit startup to surface config problems early.
        """
        try:
            result = self.scalar(connection_name, "SELECT 1")
            return {"connection": connection_name, "status": "ok", "test_result": result}
        except Exception as e:
            return {"connection": connection_name, "status": "error", "error": str(e)}

    def close_all(self):
        """Dispose all active engine connections."""
        for engine in self._engines.values():
            engine.dispose()
        self._engines.clear()


# ---------------------------------------------------------------------------
# Core Audit Engine
# ---------------------------------------------------------------------------

class AuditEngine:
    """
    The autonomous workflow audit simulation engine.

    Direct parallel to SimulationEngine in simulate.py.
    Same 7-step loop, different domain.

    data_path         -> workflow definitions + system state
    memory_path       -> finding logs + cycle logs + reports
    knowledge_base_path -> optional path to Memory Engine knowledge graph JSON
    llm_provider      -> "openai" | "claude" | "ollama" | None (uses deterministic fallback)
    llm_api_key       -> API key string, or None to read from environment variable
                         openai  -> OPENAI_API_KEY
                         claude  -> ANTHROPIC_API_KEY
                         ollama  -> no key needed
    llm_model         -> override default model (e.g. "gpt-4o", "claude-3-5-sonnet-20241022")
    db_connections    -> explicit dict of named SQLAlchemy connection strings, or None
                         to auto-load from DB_CONN_* environment variables
    schema_path       -> path to data/audit/schema/ directory for SQL schema map
                         If None, defaults to <data_path>/schema/
    creds_config_path -> path to credentials.json for server credentials
                         If None, reads exclusively from DB_CRED_* environment variables
    """

    def __init__(
        self,
        data_path: str,
        memory_path: str,
        knowledge_base_path: Optional[str] = None,
        llm_provider: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_model: Optional[str] = None,
        db_connections: Optional[Dict[str, str]] = None,
        schema_path: Optional[str] = None,
        creds_config_path: Optional[str] = None,
    ):
        self.state_manager = AuditStateManager(data_path)
        self.memory_manager = AuditMemoryManager(memory_path)
        self.trigger_checker = AuditTriggerChecker()
        self.knowledge_base = self._load_knowledge_base(knowledge_base_path)
        self.llm_responder = self._init_llm(llm_provider, llm_api_key, llm_model)

        # SQL Schema Registry — Rell's floor plan for the data layer
        _schema_dir = schema_path or str(Path(data_path) / "schema")
        self.schema_registry = self._init_schema_registry(_schema_dir)

        # Credential Manager — company-certified read-only credentials
        self.cred_manager = self._init_cred_manager(creds_config_path, _schema_dir)

        # SQL connector — built from explicit dict, schema+creds, or env vars
        self.db_connector = self._init_db_with_schema(
            db_connections, self.schema_registry, self.cred_manager
        )

        # Inject connector into knowledge_base so trigger checker can reach it
        if self.db_connector is not None:
            if self.knowledge_base is None:
                self.knowledge_base = {}
            self.knowledge_base["_db_connector"] = self.db_connector

        # Inject schema registry into knowledge_base for query validation
        if self.schema_registry is not None:
            if self.knowledge_base is None:
                self.knowledge_base = {}
            self.knowledge_base["_schema_registry"] = self.schema_registry

    def run_audit_cycle(self, workflow_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Execute one full audit cycle.

        Mirrors simulate_step() in simulate.py:
          1. Load audit state + workflows
          2. Check inconsistency triggers
          3. Evaluate system behaviors
          4. Calculate findings
          5. Update audit memory
          6. Advance cycle
          7. Save state + write reports

        Args:
            workflow_names: Specific workflows to audit. If None, audits all.

        Returns:
            Full audit report dict (also written to disk as MD + JSON).
        """

        # 1. Load current state
        audit_state = self.state_manager.load_audit_state()
        cycle = audit_state.get("cycle", 1)

        if workflow_names:
            workflows = {n: self.state_manager.load_workflow(n) for n in workflow_names}
        else:
            workflows = self.state_manager.load_all_workflows()

        all_findings: List[Dict[str, Any]] = []

        # 2. Process each workflow
        for wf_name, workflow in workflows.items():
            wf_findings = self._audit_workflow(wf_name, workflow, audit_state)
            all_findings.extend(wf_findings)

            # 3. Log findings to per-workflow journal
            for finding in wf_findings:
                self.memory_manager.append_finding(wf_name, finding)

        # 4. Update audit state summary
        audit_state["summary"]["total_findings"] = (
            audit_state["summary"].get("total_findings", 0) + len(all_findings)
        )
        audit_state["summary"]["open_findings"] = (
            audit_state["summary"].get("open_findings", 0) +
            sum(1 for f in all_findings if f.get("status") == "OPEN")
        )

        # 5. Build complete report
        report = self._build_report(cycle, audit_state, workflows, all_findings)

        # 6. Advance cycle
        self.state_manager.advance_cycle(audit_state)

        # 7. Save state + write reports
        self.state_manager.save_audit_state(audit_state)
        md_path = self.memory_manager.write_markdown_report(cycle, report)
        json_path = self.memory_manager.write_json_report(cycle, report)

        # 8. Write cycle log entry
        cycle_entry = self._create_cycle_log_entry(cycle, all_findings, report)
        self.memory_manager.append_cycle_log(cycle, cycle_entry)

        report["output_files"] = {
            "markdown_report": str(md_path),
            "json_report": str(json_path)
        }

        return report

    # ------------------------------------------------------------------
    # Internal: LLM initializer
    # ------------------------------------------------------------------

    @staticmethod
    def _init_llm(
        provider: Optional[str],
        api_key: Optional[str],
        model: Optional[str]
    ):
        """
        Initialize a RellResponder for LLM-powered assessments.
        Returns None if no provider specified — engine falls back to
        deterministic template-based assessments.
        """
        if not provider:
            return None

        # Resolve API key from env if not explicitly passed
        if api_key is None:
            env_keys = {
                "openai": "OPENAI_API_KEY",
                "claude": "ANTHROPIC_API_KEY",
                "ollama": None,
            }
            env_var = env_keys.get(provider)
            if env_var:
                api_key = os.getenv(env_var)
                if not api_key:
                    print(
                        f"[AuditEngine] LLM provider '{provider}' selected but "
                        f"{env_var} is not set. Falling back to template assessments."
                    )
                    return None

        try:
            # Import here so the file doesn't hard-require these packages
            import sys
            from pathlib import Path
            engine_dir = Path(__file__).parent
            if str(engine_dir) not in sys.path:
                sys.path.insert(0, str(engine_dir))

            from llm_integration import RellResponder

            kwargs = {"api_key": api_key}
            if model:
                kwargs["model"] = model
            if provider == "ollama" and model:
                kwargs["model"] = model

            responder = RellResponder(provider=provider, **kwargs)
            print(f"[AuditEngine] LLM mode active: {provider}" + (f" ({model})" if model else ""))
            return responder

        except ImportError as e:
            print(f"[AuditEngine] LLM dependency missing ({e}). Falling back to template assessments.")
            return None
        except Exception as e:
            print(f"[AuditEngine] LLM init failed ({e}). Falling back to template assessments.")
            return None

    # ------------------------------------------------------------------
    # Internal: Database connector initializer
    # ------------------------------------------------------------------

    @staticmethod
    def _init_db(
        connections: Optional[Dict[str, str]]
    ) -> Optional["DatabaseConnector"]:
        """
        Initialize DatabaseConnector for SQL-based audit triggers.

        Connection strings can come from:
          1. The 'db_connections' argument to AuditEngine.__init__()
          2. Environment variables: DB_CONN_<NAME>=<sqlalchemy_url>

        If neither is provided, returns None — SQL triggers silently skip.

        Examples:
            {
                "default": "mssql+pyodbc://user:pass@server/db?driver=ODBC+Driver+17+for+SQL+Server",
                "feed_db": "postgresql://user:pass@host:5432/feeds",
                "local":   "sqlite:///data/local_test.db"
            }
        """
        connector = DatabaseConnector(connections)
        if connector.has_connections():
            print(f"[AuditEngine] SQL mode active: {list(connector._connections.keys())} connections configured.")
            return connector

        # Check if any DB_CONN_ env vars exist even if no explicit dict passed
        env_conns = {
            k[8:].lower(): v
            for k, v in os.environ.items()
            if k.startswith("DB_CONN_")
        }
        if env_conns:
            connector2 = DatabaseConnector(env_conns)
            print(f"[AuditEngine] SQL mode active (from env): {list(env_conns.keys())} connections configured.")
            return connector2

        return None

    # ------------------------------------------------------------------
    # Internal: Schema Registry + Credential Manager initializers
    # ------------------------------------------------------------------

    @staticmethod
    def _init_schema_registry(schema_path: str) -> Optional["SqlSchemaRegistry"]:
        """
        Load the SQL schema registry from disk if a snapshot exists.
        If no schema has been ingested yet, returns a blank (but ready) registry.
        The schema is ingested separately via `python run_audit.py --ingest-schema`.
        """
        try:
            import sys
            from pathlib import Path as _Path
            engine_dir = _Path(__file__).parent
            if str(engine_dir) not in sys.path:
                sys.path.insert(0, str(engine_dir))

            from sql_schema_registry import SqlSchemaRegistry

            registry = SqlSchemaRegistry(schema_path)
            schema = registry.load()
            if schema:
                servers = list(schema.get("servers", {}).keys())
                total_tables = sum(
                    len(db.get("tables", {}))
                    for s in schema.get("servers", {}).values()
                    for db in s.get("databases", {}).values()
                )
                print(f"[AuditEngine] Schema map loaded: {len(servers)} server(s), {total_tables} table(s): {servers}")
            else:
                print(
                    "[AuditEngine] No schema map found. "
                    "Run `python run_audit.py --ingest-schema <path>` to load your SQL mapping."
                )
            return registry

        except ImportError as e:
            print(f"[AuditEngine] sql_schema_registry not available ({e}). Schema validation disabled.")
            return None
        except Exception as e:
            print(f"[AuditEngine] Schema registry init error ({e}). Continuing without schema map.")
            return None

    @staticmethod
    def _init_cred_manager(
        creds_config_path: Optional[str],
        schema_path: str
    ) -> Optional["CredentialManager"]:
        """
        Initialize the CredentialManager for company-certified credentials.
        Reads DB_CRED_* environment variables automatically.
        """
        try:
            import sys
            from pathlib import Path as _Path
            engine_dir = _Path(__file__).parent
            if str(engine_dir) not in sys.path:
                sys.path.insert(0, str(engine_dir))

            from sql_schema_registry import CredentialManager

            audit_log_path = str(_Path(schema_path))
            mgr = CredentialManager(
                creds_config_path=creds_config_path,
                audit_log_path=audit_log_path
            )
            configured = mgr.list_configured_servers()
            if configured:
                print(f"[AuditEngine] Credentials configured for: {configured}")
            return mgr

        except ImportError:
            return None
        except Exception as e:
            print(f"[AuditEngine] CredentialManager init error ({e}).")
            return None

    @staticmethod
    def _init_db_with_schema(
        explicit_connections: Optional[Dict[str, str]],
        schema_registry: Optional["SqlSchemaRegistry"],
        cred_manager: Optional["CredentialManager"]
    ) -> Optional[DatabaseConnector]:
        """
        Build a DatabaseConnector from the best available source:

        Priority:
          1. Explicit db_connections dict (always wins — caller knows best)
          2. CredentialManager + SchemaRegistry (auto-builds all connections from map + creds)
          3. DB_CONN_* environment variables
          4. None — SQL triggers silently skip

        This is how Rell's autonomous SQL querying works:
        Given a schema map (which servers/DBs exist) and credentials (how to connect),
        he can reach any server in scope without manual connection string configuration.
        """
        # 1. Explicit connections
        if explicit_connections:
            connector = DatabaseConnector(explicit_connections)
            print(f"[AuditEngine] SQL mode active (explicit): {list(explicit_connections.keys())}")
            return connector

        # 2. Schema + credentials auto-build
        if schema_registry and cred_manager:
            try:
                connections = cred_manager.build_connections_for_all_servers(schema_registry)
                if connections:
                    connector = DatabaseConnector(connections)
                    print(
                        f"[AuditEngine] SQL mode active (schema+creds): "
                        f"{list(connections.keys())}"
                    )
                    return connector
            except Exception as e:
                print(f"[AuditEngine] Schema+creds connection build failed ({e}). Trying env vars.")

        # 3. DB_CONN_* env vars
        env_conns = {
            k[8:].lower(): v
            for k, v in os.environ.items()
            if k.startswith("DB_CONN_")
        }
        if env_conns:
            connector = DatabaseConnector(env_conns)
            print(f"[AuditEngine] SQL mode active (from env): {list(env_conns.keys())}")
            return connector

        return None

    # ------------------------------------------------------------------
    # Internal: Per-workflow audit
    # ------------------------------------------------------------------

    def _audit_workflow(
        self,
        wf_name: str,
        workflow: Dict[str, Any],
        audit_state: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Audit a single workflow. Returns list of findings."""
        findings = []
        steps = workflow.get("steps", [])

        for step in steps:
            step_name = step.get("name", "Unnamed Step")
            system_name = step.get("system", "unknown")
            triggers = step.get("audit_triggers", [])

            # Load current system state for this step
            system_state = self.state_manager.load_system(system_name)

            for trigger in triggers:
                fired = self.trigger_checker.check(
                    trigger, system_state, audit_state, self.knowledge_base
                )

                if fired:
                    finding = self._build_finding(
                        workflow_name=wf_name,
                        step_name=step_name,
                        trigger=trigger,
                        system_state=system_state,
                        workflow=workflow
                    )
                    findings.append(finding)

                    # Set global flags if trigger specifies
                    if trigger.get("set_flag_on_fire"):
                        audit_state["global_flags"][trigger["set_flag_on_fire"]] = True

        return findings

    def _build_finding(
        self,
        workflow_name: str,
        step_name: str,
        trigger: Dict[str, Any],
        system_state: Dict[str, Any],
        workflow: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build a structured finding with Rell's assessment."""
        severity = trigger.get("severity", "MEDIUM")
        title = trigger.get("finding_title", f"Inconsistency in {step_name}")
        observation = trigger.get("observation", self._auto_observation(trigger, system_state))
        suggested_fix = trigger.get("suggested_fix", "No suggested fix defined. Manual review required.")
        rell_assessment = self._generate_rell_assessment(trigger, system_state, workflow)

        return {
            "workflow": workflow_name,
            "step": step_name,
            "trigger_type": trigger.get("type"),
            "severity": severity,
            "title": title,
            "observation": observation,
            "rell_assessment": rell_assessment,
            "suggested_fix": suggested_fix,
            "status": "OPEN",
            "timestamp": datetime.now().isoformat(),
            "system_snapshot": {
                "name": system_state.get("name"),
                "status": system_state.get("status"),
                "flags": system_state.get("flags", {})
            }
        }

    def _auto_observation(self, trigger: Dict[str, Any], system_state: Dict[str, Any]) -> str:
        """Generate a default observation when none is provided in workflow definition."""
        t_type = trigger.get("type")
        if t_type == "missing_field":
            return f"Required field `{trigger.get('field')}` is absent from system state."
        if t_type == "value_below":
            field = trigger.get("field")
            val = AuditTriggerChecker._nested_get(system_state, field)
            threshold = trigger.get("threshold")
            return f"Field `{field}` is {val} — below the required threshold of {threshold}."
        if t_type == "value_above":
            field = trigger.get("field")
            val = AuditTriggerChecker._nested_get(system_state, field)
            threshold = trigger.get("threshold")
            return f"Field `{field}` is {val} — above the maximum threshold of {threshold}."
        if t_type == "stale_data":
            field = trigger.get("field", "last_updated")
            val = AuditTriggerChecker._nested_get(system_state, field)
            return f"Field `{field}` has value `{val}` — data appears stale or timestamp is missing."
        if t_type == "cross_ref_missing":
            return f"Referenced resource `{trigger.get('ref_path')}` does not exist."
        if t_type == "flag_not_set":
            return f"Expected flag `{trigger.get('flag')}` has not been set — a required process may not have run."
        if t_type == "sql_query":
            if trigger.get("_sql_error"):
                return f"SQL query failed: {trigger['_sql_error']}"
            result = trigger.get("_sql_result", "N/A")
            direction = trigger.get("_sql_direction", "threshold_breach")
            query_name = trigger.get("finding_title", "SQL check")
            expected_min = trigger.get("expected_min")
            expected_max = trigger.get("expected_max")
            if direction == "below_min":
                return f"SQL query returned {result} — below expected minimum of {expected_min}. ({query_name})"
            if direction == "above_max":
                return f"SQL query returned {result} — above expected maximum of {expected_max}. ({query_name})"
            return f"SQL query returned {result} — does not match expected value. ({query_name})"
        if t_type == "sql_field_population":
            if trigger.get("_sql_error"):
                return f"Field population SQL query failed: {trigger['_sql_error']}"
            violations = trigger.get("_population_violations", [])
            threshold = trigger.get("threshold_pct", 90.0)
            lines = [f"Field population below {threshold}% threshold:"]
            for v in violations[:5]:  # Cap at 5 for readability
                lines.append(f"  - `{v['field']}`: {v['pct']}% populated ({v['populated']:,} / {v['total']:,} records)")
            if len(violations) > 5:
                lines.append(f"  - ...and {len(violations) - 5} more fields")
            return "\n".join(lines)
        return "Inconsistency detected — see trigger definition for details."

    def _generate_rell_assessment(
        self,
        trigger: Dict[str, Any],
        system_state: Dict[str, Any],
        workflow: Dict[str, Any]
    ) -> str:
        """
        Generate Rell's scholarly assessment of the finding.

        Priority order:
          1. Workflow-defined rell_assessment_template (always wins — author knows best)
          2. LLM-generated assessment (if llm_responder is active)
          3. Deterministic pattern-based fallback (always available, no API needed)
        """
        # 1. Workflow-defined template always takes priority
        rell_template = trigger.get("rell_assessment_template")
        if rell_template:
            return rell_template

        # 2. LLM-generated assessment when a provider is configured
        if self.llm_responder:
            llm_result = self._llm_assessment(trigger, system_state, workflow)
            if llm_result:
                return llm_result

        # 3. Deterministic fallback — always available
        t_type = trigger.get("type")
        severity = trigger.get("severity", "MEDIUM")
        workflow_name = workflow.get("name", "this workflow")
        context = workflow.get("description", "")

        if severity == "CRITICAL":
            urgency = "This cannot wait. The system is failing at something fundamental."
        elif severity == "HIGH":
            urgency = "This deserves careful attention before the next operational cycle."
        elif severity == "MEDIUM":
            urgency = "I would not call this an emergency, but patterns like this compound over time."
        else:
            urgency = "Worth noting. Small inconsistencies are often early signals of larger ones."

        if t_type == "missing_field":
            reasoning = (
                f"When I encounter a gap in documentation or state tracking—a field that should be there "
                f"but isn't—I've learned not to assume it's merely a bookkeeping error. In {workflow_name}, "
                f"this absence means something downstream may be operating on incomplete information. "
                f"{urgency}"
            )
        elif t_type in ("value_below", "value_above"):
            reasoning = (
                f"The numbers in {workflow_name} are speaking clearly, if we are willing to listen. "
                f"A metric drifting out of expected range is the system asking for attention. "
                f"I've seen councils ignore such signals until the problem became a crisis. "
                f"{urgency}"
            )
        elif t_type == "stale_data":
            reasoning = (
                f"A library whose records are never updated becomes a library about the past, "
                f"not the present. In {workflow_name}, stale data creates the same problem — "
                f"decisions made on outdated information. "
                f"{urgency}"
            )
        elif t_type == "cross_ref_missing":
            reasoning = (
                f"I've spent years maintaining cross-references in my library. A broken reference "
                f"doesn't just mean one thing is missing — it means the web of connections "
                f"around it is silently unreliable. In {workflow_name}: {urgency}"
            )
        elif t_type == "flag_not_set":
            reasoning = (
                f"A flag that should have been set was not. In {workflow_name}, this suggests "
                f"a process that was expected to complete has either not run or not communicated "
                f"its completion. Silence is not the same as absence of error. {urgency}"
            )
        else:
            reasoning = (
                f"Something in {workflow_name} is not behaving as documented. "
                f"I hold these observations carefully — not every inconsistency is catastrophic, "
                f"but none should be dismissed without understanding. {urgency}"
            )

        if context:
            reasoning += f"\n\n*Workflow context: {context}*"

        return reasoning

    def _llm_assessment(
        self,
        trigger: Dict[str, Any],
        system_state: Dict[str, Any],
        workflow: Dict[str, Any]
    ) -> Optional[str]:
        """
        Call the LLM to generate Rell's assessment of a finding.

        Builds a focused prompt containing:
          - Rell's full audit agent system prompt (persona + instructions)
          - Workflow context (name, description, step)
          - The specific finding (trigger type, observation, system state)
          - Any relevant knowledge base entries

        Returns the LLM response string, or None on failure.
        """
        try:
            from audit_agent import WorkflowAuditAgent
            agent = WorkflowAuditAgent(knowledge_base=self.knowledge_base)
            system_prompt = agent.get_system_prompt()

            # Build the context block Rell "reads" before responding
            wf_name = workflow.get("name", "unknown workflow")
            wf_desc = workflow.get("description", "")
            t_type = trigger.get("type", "unknown")
            severity = trigger.get("severity", "MEDIUM")
            observation = trigger.get(
                "observation",
                self._auto_observation(trigger, system_state)
            )
            suggested_fix = trigger.get("suggested_fix", "")

            # Pull any relevant knowledge base context
            kb_hint = ""
            if self.knowledge_base:
                nodes = self.knowledge_base.get("nodes", [])
                concepts = {
                    "missing_field": ["documentation", "data quality"],
                    "stale_data": ["refresh", "maintenance", "data freshness"],
                    "cross_ref_missing": ["cross-reference", "file management"],
                    "value_below": ["metrics", "thresholds"],
                    "value_above": ["metrics", "thresholds"],
                    "flag_not_set": ["process completion", "workflow flags"],
                }.get(t_type, [])
                for concept in concepts:
                    for node in nodes:
                        label = node.get("label", node.get("id", ""))
                        if label and concept.lower() in str(node).lower():
                            floor = node.get("floor", "")
                            kb_hint = f"Relevant library entry: {label}" + (
                                f" (Floor {floor})" if floor else ""
                            )
                            break
                    if kb_hint:
                        break

            context = (
                f"## Current Finding\n\n"
                f"**Workflow:** {wf_name}\n"
                f"**Workflow description:** {wf_desc}\n"
                f"**Trigger type:** {t_type}\n"
                f"**Severity:** {severity}\n"
                f"**Observation:** {observation}\n"
                + (f"**Suggested fix defined:** {suggested_fix}\n" if suggested_fix else "")
                + (f"\n**Library context:** {kb_hint}\n" if kb_hint else "")
                + f"\n**System state summary:**\n"
                + f"- Name: {system_state.get('name', 'unknown')}\n"
                + f"- Status: {system_state.get('status', 'unknown')}\n"
                + f"- Last updated: {system_state.get('last_updated', 'unknown')}\n"
                + f"- Notes: {system_state.get('notes', '')}\n"
            )

            user_message = (
                f"Provide your assessment of this finding. "
                f"Be specific, honest about severity, and speak in your voice. "
                f"2-4 sentences. Do not restate the observation — go deeper."
            )

            return self.llm_responder.get_rell_response(system_prompt, context, user_message)

        except Exception as e:
            print(f"[AuditEngine] LLM assessment failed ({e}), using template fallback.")
            return None

    # ------------------------------------------------------------------
    # Internal: Report building
    # ------------------------------------------------------------------

    def _build_report(
        self,
        cycle: int,
        audit_state: Dict[str, Any],
        workflows: Dict[str, Any],
        findings: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Assemble the full audit report."""
        critical_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        high_count = sum(1 for f in findings if f.get("severity") == "HIGH")

        return {
            "cycle": cycle,
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "workflows_audited": len(workflows),
                "total_findings": len(findings),
                "by_severity": {
                    "CRITICAL": critical_count,
                    "HIGH": high_count,
                    "MEDIUM": sum(1 for f in findings if f.get("severity") == "MEDIUM"),
                    "LOW": sum(1 for f in findings if f.get("severity") == "LOW"),
                    "INFO": sum(1 for f in findings if f.get("severity") == "INFO"),
                }
            },
            "rell_opening": self._rell_opening(cycle, findings, workflows),
            "rell_closing": self._rell_closing(findings, critical_count, high_count),
            "findings": findings,
            "workflows_audited": list(workflows.keys()),
            "audit_state_snapshot": {
                "global_flags": audit_state.get("global_flags", {}),
                "open_findings": audit_state["summary"].get("open_findings", 0)
            }
        }

    def _rell_opening(
        self,
        cycle: int,
        findings: List[Dict[str, Any]],
        workflows: Dict[str, Any]
    ) -> str:
        wf_list = ", ".join(workflows.keys()) or "no workflows defined yet"
        count = len(findings)

        if count == 0:
            return (
                f"Cycle {cycle}. I've walked through the workflows — {wf_list} — "
                f"and found nothing that disturbs the equilibrium today. "
                f"I do not mistake this silence for permanent stability. "
                f"I will return."
            )
        elif count <= 3:
            return (
                f"Cycle {cycle}. I've reviewed {wf_list}. "
                f"There are {count} inconsistencies that deserve attention. "
                f"None of them are beyond repair — but they are the kind of things "
                f"that compound quietly if left unaddressed. Let us name them."
            )
        else:
            return (
                f"Cycle {cycle}. I reviewed {wf_list} and found {count} inconsistencies. "
                f"I will be honest with you: this is more than I'd like. "
                f"When I see this many signals at once, I've learned to look for the "
                f"underlying pattern — the common thread that ties them. "
                f"I've documented each one below."
            )

    def _rell_closing(
        self,
        findings: List[Dict[str, Any]],
        critical_count: int,
        high_count: int
    ) -> str:
        if critical_count > 0:
            return (
                f"I'll be direct: there {'are' if critical_count > 1 else 'is'} "
                f"{critical_count} critical {'findings' if critical_count > 1 else 'finding'} "
                f"that cannot wait. The others matter too — but start there. "
                f"A system under strain in its critical paths will eventually fail at the worst moment. "
                f"Do not let it."
            )
        elif high_count > 0:
            return (
                f"No critical failures this cycle — that's worth acknowledging. "
                f"But {high_count} high-severity {'findings' if high_count > 1 else 'finding'} "
                f"remain open. High severity doesn't mean the building is on fire. "
                f"It means we can see the smoke. Address these before the next cycle."
            )
        elif findings:
            return (
                f"Medium and low findings only this cycle. The system is largely sound. "
                f"Review the suggestions at your own pace — but do review them. "
                f"Small inconsistencies are how large ones start."
            )
        else:
            return (
                f"A clean cycle. The work done to address previous findings is showing. "
                f"Document what's working so we can replicate it elsewhere."
            )

    def _create_cycle_log_entry(
        self,
        cycle: int,
        findings: List[Dict[str, Any]],
        report: Dict[str, Any]
    ) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        return (
            f"### Cycle {cycle} — {ts}\n\n"
            f"**Workflows:** {', '.join(report.get('workflows_audited', []))}\n"
            f"**Total Findings:** {len(findings)}\n"
            f"**By Severity:** "
            + " | ".join(
                f"{k}: {v}"
                for k, v in report.get("summary", {}).get("by_severity", {}).items()
                if v > 0
            )
            + "\n"
        )

    # ------------------------------------------------------------------
    # Knowledge base loader
    # ------------------------------------------------------------------

    @staticmethod
    def _load_knowledge_base(path: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Load the Memory Engine knowledge graph for context-aware assessments.
        Points at AAAI_KNOWLEDGE_GRAPH.json in the Memory_Engine folder.
        """
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"[AuditEngine] Knowledge base not found at {path} — proceeding without it.")
            return None


# ---------------------------------------------------------------------------
# Convenience runner (mirrors run_simulation_step)
# ---------------------------------------------------------------------------

def run_audit_cycle(
    data_path: str,
    memory_path: str,
    knowledge_base_path: Optional[str] = None,
    workflow_names: Optional[List[str]] = None,
    llm_provider: Optional[str] = None,
    llm_api_key: Optional[str] = None,
    llm_model: Optional[str] = None,
    db_connections: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Run one audit cycle (convenience function).

    Args:
        data_path: Root path for workflow definitions + system state.
        memory_path: Root path for finding logs + reports.
        knowledge_base_path: Optional path to AAAI_KNOWLEDGE_GRAPH.json.
        workflow_names: Specific workflows to audit (None = all).
        llm_provider: "openai" | "claude" | "ollama" | None (deterministic fallback).
        llm_api_key: API key. If None, reads from OPENAI_API_KEY / ANTHROPIC_API_KEY env vars.
        llm_model: Override default model (e.g. "gpt-4o", "claude-3-5-sonnet-20241022").
        db_connections: Dict of named SQLAlchemy connection strings for SQL triggers.
                        Example: {"feed_db": "mssql+pyodbc://user:pass@server/db?driver=ODBC+Driver+17+for+SQL+Server"}
                        If None, reads DB_CONN_* environment variables.

    Returns:
        Full audit report dict.
    """
    engine = AuditEngine(
        data_path,
        memory_path,
        knowledge_base_path,
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        db_connections=db_connections,
    )
    return engine.run_audit_cycle(workflow_names)
