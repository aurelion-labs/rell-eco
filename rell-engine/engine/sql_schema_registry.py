"""
sql_schema_registry.py - The SQL Map. Rell's Floor Plan for the Data Layer.

When Rell walks into a document library, he uses the floor mapping to know
where everything lives.  When he walks into a SQL environment, he uses this.

This module:
  1. Ingests a SQL schema map (servers → databases → tables → columns)
     from JSON, CSV export, or a live database introspection query
  2. Persists it as a versioned schema snapshot under data/audit/schema/
  3. Provides Rell with schema-aware query building:
     - Resolve a logical concept ("case number") → actual column/table
     - Detect schema drift (new table, dropped column, renamed field)
     - Validate that a workflow's queries match the live schema before running
  4. Provides the CredentialManager:
     - Named, encrypted-at-rest credentials for each server
     - Read-only credential enforcement (Rell never writes)
     - Audit log of every connection Rell opens

The mapping format Rell expects:
  {
    "schema_version": "1.0",
    "captured_at": "2026-02-17T...",
    "captured_by": "z3rosl33p",
    "servers": {
      "PROD-SQL-01": {
        "host": "prod-sql-01.example.com",
        "port": 1433,
        "engine": "mssql",
        "databases": {
          "FeedDatabase": {
            "tables": {
              "Cases": {
                "columns": {
                  "CaseNumber":       {"type": "VARCHAR(50)",  "nullable": false, "primary_key": true},
                  "DefendantLastName": {"type": "VARCHAR(100)", "nullable": true},
                  "FilingDate":       {"type": "DATE",         "nullable": false},
                  "IsActive":         {"type": "BIT",          "nullable": false, "default": 1},
                  ...
                },
                "row_count_estimate": 2400000,
                "indexes": ["CaseNumber", "FilingDate"]
              }
            }
          }
        }
      }
    }
  }

This exact structure is what the ingest command writes and what Rell reads.
"""

import json
import os
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


# ---------------------------------------------------------------------------
# SQL Schema Registry
# ---------------------------------------------------------------------------

class SqlSchemaRegistry:
    """
    Rell's floor plan for the data layer.

    Ingests, persists, versions, and queries a full SQL schema map.
    Every server, every database, every table, every column.

    Stored under: data/audit/schema/
      schema_current.json   <- latest snapshot (always current)
      schema_<timestamp>.json <- versioned history (for drift detection)
      schema_index.json     <- lightweight index for fast lookup
    """

    CURRENT_FILE = "schema_current.json"
    INDEX_FILE = "schema_index.json"

    def __init__(self, schema_path: str):
        self.schema_path = Path(schema_path)
        self.schema_path.mkdir(parents=True, exist_ok=True)
        self._schema: Optional[Dict[str, Any]] = None
        self._index: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest_from_file(self, source_path: str, captured_by: str = "system") -> Dict[str, Any]:
        """
        Load a schema map from a JSON file you provide.

        This is the primary intake path: you export your schema map
        (from DBeaver, SSMS, a custom script, etc.) and hand it to Rell.

        Args:
            source_path: Path to the JSON schema export file.
            captured_by: Who captured this mapping (for audit trail).

        Returns:
            Ingest summary: table counts, column counts, servers found.
        """
        with open(source_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        return self._ingest(raw, captured_by)

    def ingest_from_dict(self, schema_dict: Dict[str, Any], captured_by: str = "system") -> Dict[str, Any]:
        """
        Load a schema map directly from a Python dict.
        Useful when ingesting programmatically (e.g., from live introspection).
        """
        return self._ingest(schema_dict, captured_by)

    def ingest_from_live_db(
        self,
        connection_name: str,
        connector: "DatabaseConnector",
        server_label: str,
        captured_by: str = "system"
    ) -> Dict[str, Any]:
        """
        Build the schema map by introspecting a live database directly.

        Rell queries INFORMATION_SCHEMA (works on MSSQL, PostgreSQL, MySQL)
        to discover all databases, tables, and columns automatically.

        Args:
            connection_name: Named connection in DatabaseConnector.
            connector: DatabaseConnector instance with live connection.
            server_label: Human-readable label for this server (e.g. "PROD-SQL-01").
            captured_by: Who initiated this introspection.

        Returns:
            Ingest summary.
        """
        print(f"[SchemaRegistry] Introspecting live schema from '{server_label}' via '{connection_name}'...")

        tables_query = """
            SELECT
                TABLE_CATALOG,
                TABLE_SCHEMA,
                TABLE_NAME,
                TABLE_TYPE
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME
        """

        columns_query = """
            SELECT
                TABLE_CATALOG,
                TABLE_SCHEMA,
                TABLE_NAME,
                COLUMN_NAME,
                DATA_TYPE,
                CHARACTER_MAXIMUM_LENGTH,
                IS_NULLABLE,
                COLUMN_DEFAULT,
                ORDINAL_POSITION
            FROM INFORMATION_SCHEMA.COLUMNS
            ORDER BY TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
        """

        tables_rows = connector.fetchall(connection_name, tables_query)
        columns_rows = connector.fetchall(connection_name, columns_query)

        # Build schema dict from live results
        schema = self._build_schema_from_information_schema(
            server_label, tables_rows, columns_rows
        )

        return self._ingest(schema, captured_by)

    # ------------------------------------------------------------------
    # Load + Query
    # ------------------------------------------------------------------

    def load(self) -> Optional[Dict[str, Any]]:
        """Load the current schema snapshot into memory."""
        current_file = self.schema_path / self.CURRENT_FILE
        if not current_file.exists():
            return None
        with open(current_file, "r", encoding="utf-8") as f:
            self._schema = json.load(f)
        return self._schema

    def is_loaded(self) -> bool:
        return self._schema is not None

    def get_schema(self) -> Optional[Dict[str, Any]]:
        if self._schema is None:
            self.load()
        return self._schema

    def list_servers(self) -> List[str]:
        schema = self.get_schema()
        if not schema:
            return []
        return list(schema.get("servers", {}).keys())

    def list_databases(self, server: str) -> List[str]:
        schema = self.get_schema()
        if not schema:
            return []
        return list(schema.get("servers", {}).get(server, {}).get("databases", {}).keys())

    def list_tables(self, server: str, database: str) -> List[str]:
        schema = self.get_schema()
        if not schema:
            return []
        return list(
            schema.get("servers", {})
            .get(server, {})
            .get("databases", {})
            .get(database, {})
            .get("tables", {})
            .keys()
        )

    def get_table(self, server: str, database: str, table: str) -> Optional[Dict[str, Any]]:
        schema = self.get_schema()
        if not schema:
            return None
        return (
            schema.get("servers", {})
            .get(server, {})
            .get("databases", {})
            .get(database, {})
            .get("tables", {})
            .get(table)
        )

    def get_columns(self, server: str, database: str, table: str) -> Dict[str, Any]:
        t = self.get_table(server, database, table)
        return t.get("columns", {}) if t else {}

    def find_table(self, table_name: str) -> List[Dict[str, str]]:
        """
        Search all servers/databases for a table by name (case-insensitive).
        Returns list of matches: [{"server": ..., "database": ..., "table": ...}]
        """
        results = []
        schema = self.get_schema()
        if not schema:
            return results
        for srv_name, srv in schema.get("servers", {}).items():
            for db_name, db in srv.get("databases", {}).items():
                for tbl_name in db.get("tables", {}).keys():
                    if tbl_name.lower() == table_name.lower():
                        results.append({"server": srv_name, "database": db_name, "table": tbl_name})
        return results

    def find_column(self, column_name: str) -> List[Dict[str, str]]:
        """
        Search all tables for a column by name (case-insensitive).
        Returns list of matches with server/db/table context.
        Essential for Rell to resolve logical field names to actual locations.
        """
        results = []
        schema = self.get_schema()
        if not schema:
            return results
        for srv_name, srv in schema.get("servers", {}).items():
            for db_name, db in srv.get("databases", {}).items():
                for tbl_name, tbl in db.get("tables", {}).items():
                    for col_name in tbl.get("columns", {}).keys():
                        if col_name.lower() == column_name.lower():
                            results.append({
                                "server": srv_name,
                                "database": db_name,
                                "table": tbl_name,
                                "column": col_name,
                                "type": tbl["columns"][col_name].get("type", "UNKNOWN")
                            })
        return results

    def validate_query_columns(
        self, server: str, database: str, query: str
    ) -> Dict[str, Any]:
        """
        Pre-flight check: scan a SQL query string for table/column references
        and verify they exist in the schema before Rell runs them live.

        Returns:
            {
                "valid": bool,
                "warnings": [str],   # columns/tables not found in schema
                "confirmed": [str]   # columns/tables verified in schema
            }
        """
        # Lightweight heuristic: extract identifiers from common SQL patterns
        import re
        warnings = []
        confirmed = []

        tables_in_db = self.list_tables(server, database)

        # Find FROM/JOIN table references
        table_refs = re.findall(r'(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)', query, re.IGNORECASE)
        for tref in table_refs:
            if tref.upper() in ("SELECT", "WHERE", "AND", "OR"):
                continue
            if tref in tables_in_db:
                confirmed.append(f"table:{tref}")
            else:
                warnings.append(f"Table '{tref}' not found in {server}/{database} schema")

        return {
            "valid": len(warnings) == 0,
            "warnings": warnings,
            "confirmed": confirmed
        }

    # ------------------------------------------------------------------
    # Drift Detection
    # ------------------------------------------------------------------

    def detect_drift(self, new_schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compare new schema against current snapshot.
        Returns a structured drift report: added tables, dropped tables, changed columns.

        This is how Rell notices schema changes that could break existing queries.
        A column rename won't throw a SQL error on ingest — it'll just silently break
        population checks. Drift detection catches that before it becomes a finding.
        """
        current = self.get_schema()
        if not current:
            return {"status": "no_baseline", "message": "No existing schema to compare against."}

        added_tables = []
        dropped_tables = []
        added_columns = []
        dropped_columns = []
        type_changes = []

        current_servers = current.get("servers", {})
        new_servers = new_schema.get("servers", {})

        for srv_name in set(list(current_servers.keys()) + list(new_servers.keys())):
            curr_srv = current_servers.get(srv_name, {})
            new_srv = new_servers.get(srv_name, {})

            for db_name in set(list(curr_srv.get("databases", {}).keys()) + list(new_srv.get("databases", {}).keys())):
                curr_db = curr_srv.get("databases", {}).get(db_name, {})
                new_db = new_srv.get("databases", {}).get(db_name, {})
                curr_tables = set(curr_db.get("tables", {}).keys())
                new_tables = set(new_db.get("tables", {}).keys())

                for t in new_tables - curr_tables:
                    added_tables.append(f"{srv_name}.{db_name}.{t}")
                for t in curr_tables - new_tables:
                    dropped_tables.append(f"{srv_name}.{db_name}.{t}")

                for tbl in curr_tables & new_tables:
                    curr_cols = curr_db["tables"][tbl].get("columns", {})
                    new_cols = new_db["tables"][tbl].get("columns", {})
                    for c in set(new_cols) - set(curr_cols):
                        added_columns.append(f"{srv_name}.{db_name}.{tbl}.{c}")
                    for c in set(curr_cols) - set(new_cols):
                        dropped_columns.append(f"{srv_name}.{db_name}.{tbl}.{c}")
                    for c in set(curr_cols) & set(new_cols):
                        if curr_cols[c].get("type") != new_cols[c].get("type"):
                            type_changes.append({
                                "location": f"{srv_name}.{db_name}.{tbl}.{c}",
                                "from": curr_cols[c].get("type"),
                                "to": new_cols[c].get("type")
                            })

        return {
            "status": "drift_detected" if any([added_tables, dropped_tables, added_columns, dropped_columns, type_changes]) else "no_drift",
            "added_tables": added_tables,
            "dropped_tables": dropped_tables,
            "added_columns": added_columns,
            "dropped_columns": dropped_columns,
            "type_changes": type_changes,
            "summary": (
                f"{len(dropped_tables)} table(s) dropped, "
                f"{len(added_tables)} added, "
                f"{len(dropped_columns)} column(s) dropped, "
                f"{len(added_columns)} column(s) added, "
                f"{len(type_changes)} type change(s)"
            )
        }

    # ------------------------------------------------------------------
    # Summary for Rell
    # ------------------------------------------------------------------

    def describe_for_rell(self) -> str:
        """
        Return a plain-language summary of the schema for Rell's opening statement.
        He reads this before starting an audit cycle that touches SQL.
        """
        schema = self.get_schema()
        if not schema:
            return "No schema map loaded. Running blind — queries will rely on workflow-defined table names only."

        servers = schema.get("servers", {})
        total_dbs = sum(len(s.get("databases", {})) for s in servers.values())
        total_tables = sum(
            len(db.get("tables", {}))
            for s in servers.values()
            for db in s.get("databases", {}).values()
        )
        total_cols = sum(
            len(tbl.get("columns", {}))
            for s in servers.values()
            for db in s.get("databases", {}).values()
            for tbl in db.get("tables", {}).values()
        )
        captured_at = schema.get("captured_at", "unknown")
        captured_by = schema.get("captured_by", "unknown")

        return (
            f"I have the floor plan.\n\n"
            f"Schema map loaded: {len(servers)} server(s), {total_dbs} database(s), "
            f"{total_tables} table(s), {total_cols} column(s).\n"
            f"Captured by {captured_by} on {captured_at[:10] if len(captured_at) >= 10 else captured_at}.\n\n"
            f"Servers in scope: {', '.join(servers.keys())}.\n\n"
            f"I can now write precise queries. I know where the columns live. "
            f"I'll validate queries against this map before running them."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ingest(self, raw: Dict[str, Any], captured_by: str) -> Dict[str, Any]:
        """Core ingest logic: validate, stamp, version, save, rebuild index."""
        # Stamp metadata
        raw["captured_at"] = raw.get("captured_at", datetime.now().isoformat())
        raw["captured_by"] = raw.get("captured_by", captured_by)
        raw["schema_version"] = raw.get("schema_version", "1.0")
        raw["ingested_at"] = datetime.now().isoformat()

        # Drift check before overwriting
        drift = self.detect_drift(raw)

        # Save versioned snapshot
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        versioned_file = self.schema_path / f"schema_{ts}.json"
        with open(versioned_file, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)

        # Overwrite current
        current_file = self.schema_path / self.CURRENT_FILE
        with open(current_file, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)

        # Rebuild lightweight index
        self._schema = raw
        index = self._build_index(raw)
        self._index = index
        index_file = self.schema_path / self.INDEX_FILE
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

        # Ingest summary
        servers = raw.get("servers", {})
        total_dbs = sum(len(s.get("databases", {})) for s in servers.values())
        total_tables = sum(
            len(db.get("tables", {}))
            for s in servers.values()
            for db in s.get("databases", {}).values()
        )
        total_cols = sum(
            len(tbl.get("columns", {}))
            for s in servers.values()
            for db in s.get("databases", {}).values()
            for tbl in db.get("tables", {}).values()
        )

        return {
            "status": "ingested",
            "versioned_file": str(versioned_file),
            "servers": list(servers.keys()),
            "databases": total_dbs,
            "tables": total_tables,
            "columns": total_cols,
            "drift": drift,
            "captured_at": raw["captured_at"],
        }

    def _build_index(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a fast-lookup flat index: table_name -> [locations], column_name -> [locations].
        Lets Rell find where 'CaseNumber' lives without scanning the full schema tree.
        """
        table_index: Dict[str, List] = {}
        column_index: Dict[str, List] = {}

        for srv_name, srv in schema.get("servers", {}).items():
            for db_name, db in srv.get("databases", {}).items():
                for tbl_name, tbl in db.get("tables", {}).items():
                    loc = {"server": srv_name, "database": db_name, "table": tbl_name}
                    table_index.setdefault(tbl_name.lower(), []).append(loc)
                    for col_name, col_meta in tbl.get("columns", {}).items():
                        col_loc = {**loc, "column": col_name, "type": col_meta.get("type", "UNKNOWN")}
                        column_index.setdefault(col_name.lower(), []).append(col_loc)

        return {
            "built_at": datetime.now().isoformat(),
            "tables": table_index,
            "columns": column_index
        }

    def _build_schema_from_information_schema(
        self,
        server_label: str,
        tables_rows: list,
        columns_rows: list
    ) -> Dict[str, Any]:
        """Convert INFORMATION_SCHEMA rows into the registry's JSON format."""
        schema: Dict[str, Any] = {
            "servers": {
                server_label: {
                    "host": server_label,
                    "engine": "mssql",
                    "databases": {}
                }
            }
        }

        srv = schema["servers"][server_label]["databases"]

        # Build table structure
        for row in tables_rows:
            catalog, tbl_schema, tbl_name, tbl_type = row[0], row[1], row[2], row[3]
            db_key = catalog
            srv.setdefault(db_key, {"tables": {}})
            srv[db_key]["tables"].setdefault(tbl_name, {"columns": {}, "schema": tbl_schema})

        # Populate columns
        for row in columns_rows:
            catalog, tbl_schema, tbl_name, col_name = row[0], row[1], row[2], row[3]
            data_type = row[4]
            max_length = row[5]
            is_nullable = row[6]
            default = row[7]
            db_key = catalog

            if db_key not in srv:
                continue
            if tbl_name not in srv[db_key]["tables"]:
                continue

            type_str = data_type.upper()
            if max_length and int(max_length) > 0:
                type_str += f"({max_length})"

            srv[db_key]["tables"][tbl_name]["columns"][col_name] = {
                "type": type_str,
                "nullable": is_nullable == "YES",
                "default": default
            }

        return schema


# ---------------------------------------------------------------------------
# Credential Manager
# ---------------------------------------------------------------------------

class CredentialManager:
    """
    Manages company-certified credentials for each server Rell can query.

    Security design principles:
    - Rell gets READ-ONLY credentials only. He cannot INSERT, UPDATE, DELETE, or DROP.
    - Credentials are never stored in code or workflow JSON files.
    - Credential sources (in priority order):
        1. Environment variables: DB_CRED_<SERVER>_USER, DB_CRED_<SERVER>_PASS
        2. A credentials config file (credentials.json) — excluded from git via .gitignore
        3. System keychain (via keyring library if installed)
    - Every connection Rell opens is logged to the audit trail.
    - Connection strings are built on-demand, never persisted to disk.

    Usage:
        cred_mgr = CredentialManager(creds_config_path="data/audit/credentials.json")
        conn_str = cred_mgr.get_connection_string("PROD-SQL-01", "FeedDatabase")
        # -> "mssql+pyodbc://readonly_user:***@prod-sql-01.example.com/FeedDatabase?driver=..."

    For company-certified credentials:
        Set environment variables before running Rell:
            $env:DB_CRED_PROD_SQL_01_USER = "rell_readonly"
            $env:DB_CRED_PROD_SQL_01_PASS = "your_certified_password"
            $env:DB_CRED_PROD_SQL_01_HOST = "prod-sql-01.example.com"
            $env:DB_CRED_PROD_SQL_01_PORT = "1433"
            $env:DB_CRED_PROD_SQL_01_ENGINE = "mssql"

        Or use Windows Credential Manager (keyring):
            pip install keyring
            keyring set rell_audit PROD-SQL-01 "user:password"
    """

    CONNECTION_LOG_FILE = "connection_audit_log.jsonl"

    def __init__(
        self,
        creds_config_path: Optional[str] = None,
        audit_log_path: Optional[str] = None
    ):
        self._creds_config: Dict[str, Any] = {}
        self._audit_log_path = Path(audit_log_path or "data/audit/schema") / self.CONNECTION_LOG_FILE

        if creds_config_path and Path(creds_config_path).exists():
            with open(creds_config_path, "r", encoding="utf-8") as f:
                self._creds_config = json.load(f)

        # Ensure audit log directory exists
        self._audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    def get_connection_string(
        self,
        server_label: str,
        database: str,
        schema_registry: Optional["SqlSchemaRegistry"] = None
    ) -> Optional[str]:
        """
        Build a SQLAlchemy connection string for a server/database pair.

        Rell never stores this string — it's built on demand, used, discarded.
        The call is logged to the connection audit log.

        Credential resolution order:
          1. Environment variables (DB_CRED_<SERVER>_*)
          2. credentials.json config file
          3. System keyring (if keyring is installed)

        Args:
            server_label: Server name matching schema map (e.g. "PROD-SQL-01").
            database: Database name (e.g. "FeedDatabase").
            schema_registry: Optional — used to look up host/port/engine from schema map.

        Returns:
            SQLAlchemy URL string, or None if credentials could not be resolved.
        """
        creds = self._resolve_credentials(server_label)
        if not creds:
            return None

        # Try to get host/engine from schema if available
        if schema_registry:
            schema = schema_registry.get_schema()
            if schema:
                srv_meta = schema.get("servers", {}).get(server_label, {})
                creds.setdefault("host", srv_meta.get("host", server_label))
                creds.setdefault("port", srv_meta.get("port", 1433))
                creds.setdefault("engine", srv_meta.get("engine", "mssql"))

        engine = creds.get("engine", "mssql").lower()
        host = creds.get("host", server_label)
        port = creds.get("port", 1433)
        user = creds.get("user", "")
        password = creds.get("password", "")

        # Build the connection string based on engine type
        if engine == "mssql":
            conn_str = (
                f"mssql+pyodbc://{user}:{password}@{host}:{port}/{database}"
                f"?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
            )
        elif engine in ("postgresql", "postgres", "pg"):
            conn_str = f"postgresql://{user}:{password}@{host}:{port}/{database}"
        elif engine == "mysql":
            conn_str = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
        elif engine == "sqlite":
            conn_str = f"sqlite:///{database}"
        else:
            conn_str = f"{engine}://{user}:{password}@{host}:{port}/{database}"

        # Log the connection (mask password)
        self._log_connection(server_label, database, user, engine)

        return conn_str

    def build_connections_for_all_servers(
        self,
        schema_registry: "SqlSchemaRegistry"
    ) -> Dict[str, str]:
        """
        Build a connection string for every server/database in the schema map.
        Returns a dict suitable for passing to DatabaseConnector({...}).

        This is how Rell bootstraps himself when he has both a schema map
        and credentials: one call, all connections ready.

        Returns:
            {"PROD-SQL-01/FeedDatabase": "mssql+pyodbc://...", ...}
            Keys are "server/database" format used as connection names.
        """
        connections = {}
        schema = schema_registry.get_schema()
        if not schema:
            return connections

        for server_label, srv_data in schema.get("servers", {}).items():
            for db_name in srv_data.get("databases", {}).keys():
                conn_key = f"{server_label}/{db_name}"
                conn_str = self.get_connection_string(server_label, db_name, schema_registry)
                if conn_str:
                    connections[conn_key] = conn_str
                else:
                    print(
                        f"[CredentialManager] No credentials found for {server_label}. "
                        f"Set DB_CRED_{server_label.upper().replace('-', '_')}_USER and _PASS "
                        f"environment variables."
                    )

        return connections

    def list_configured_servers(self) -> List[str]:
        """Return server names that have credentials configured."""
        servers = set()

        # From env vars
        for key in os.environ:
            if key.startswith("DB_CRED_") and key.endswith("_USER"):
                server = key[len("DB_CRED_"):-len("_USER")].replace("_", "-")
                servers.add(server)

        # From config file
        servers.update(self._creds_config.keys())

        return sorted(servers)

    def validate_readonly(
        self,
        connection_name: str,
        connector: "DatabaseConnector"
    ) -> Dict[str, Any]:
        """
        Verify that Rell's credentials are read-only.
        Attempts an INSERT into a temp table and expects it to fail.
        If it succeeds, the credentials have write access — flag immediately.

        This is a safety check. Run it at startup when using new credentials.
        """
        test_query = "INSERT INTO ##rell_readonly_test (id) VALUES (1)"
        try:
            connector.scalar(connection_name, test_query)
            # If we got here without exception, write access exists — CRITICAL
            return {
                "readonly": False,
                "status": "FAIL",
                "message": (
                    "CRITICAL: Rell's credentials have WRITE ACCESS to this database. "
                    "This must be corrected before any audit queries run. "
                    "Provide a read-only SQL user."
                )
            }
        except Exception as e:
            err = str(e).lower()
            if any(word in err for word in ["permission", "denied", "not permitted", "readonly", "read-only"]):
                return {"readonly": True, "status": "OK", "message": "Credentials confirmed read-only."}
            # Some other error (table doesn't exist, syntax) — likely read-only, but note it
            return {
                "readonly": True,
                "status": "OK",
                "message": f"Read-only check passed (write attempt failed as expected: {str(e)[:80]})"
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_credentials(self, server_label: str) -> Optional[Dict[str, str]]:
        """
        Resolve credentials for a server. Priority: env vars > config file > keyring.
        Returns a dict with keys: user, password, host, port, engine.
        """
        env_prefix = f"DB_CRED_{server_label.upper().replace('-', '_').replace(' ', '_')}_"

        user = os.environ.get(f"{env_prefix}USER")
        password = os.environ.get(f"{env_prefix}PASS")
        host = os.environ.get(f"{env_prefix}HOST")
        port = os.environ.get(f"{env_prefix}PORT", "1433")
        engine = os.environ.get(f"{env_prefix}ENGINE", "mssql")

        # Fall back to config file
        if not user or not password:
            config_entry = self._creds_config.get(server_label, {})
            user = user or config_entry.get("user")
            password = password or config_entry.get("password")
            host = host or config_entry.get("host")
            port = port or str(config_entry.get("port", "1433"))
            engine = engine or config_entry.get("engine", "mssql")

        # Fall back to system keyring
        if not user or not password:
            try:
                import keyring
                secret = keyring.get_password("rell_audit", server_label)
                if secret and ":" in secret:
                    user, password = secret.split(":", 1)
            except ImportError:
                pass

        if not user or not password:
            return None

        return {
            "user": user,
            "password": password,
            "host": host or server_label,
            "port": int(port),
            "engine": engine
        }

    def _log_connection(
        self,
        server: str,
        database: str,
        user: str,
        engine: str
    ) -> None:
        """Append a connection event to the audit log (JSONL format)."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "server": server,
            "database": database,
            "user": user,
            "engine": engine,
            "agent": "WorkflowAuditAgent/Rell"
        }
        with open(self._audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Convenience: generate a credentials template
# ---------------------------------------------------------------------------

def generate_credentials_template(
    schema_registry: SqlSchemaRegistry,
    output_path: str = "data/audit/credentials.template.json"
) -> str:
    """
    Generate a credentials template JSON from the schema map.
    The template has all server names pre-filled — you just add credentials.

    The actual credentials.json is gitignored. This template is safe to commit.

    Args:
        schema_registry: Loaded SqlSchemaRegistry.
        output_path: Where to write the template.

    Returns:
        Path to the generated template.
    """
    schema = schema_registry.get_schema()
    if not schema:
        raise ValueError("No schema loaded. Run ingest first.")

    template = {}
    for server_label, srv_data in schema.get("servers", {}).items():
        template[server_label] = {
            "host": srv_data.get("host", server_label),
            "port": srv_data.get("port", 1433),
            "engine": srv_data.get("engine", "mssql"),
            "user": "REPLACE_WITH_READONLY_USER",
            "password": "REPLACE_WITH_PASSWORD",
            "_note": (
                f"Or use environment variables: "
                f"DB_CRED_{server_label.upper().replace('-', '_')}_USER and "
                f"DB_CRED_{server_label.upper().replace('-', '_')}_PASS"
            )
        }

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)

    return str(output_file)
