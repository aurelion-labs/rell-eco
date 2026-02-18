"""
flatfile_parser.py - Flat File Parser and QA Engine for Pipe-Delimited Records

Rell's third audit domain, alongside file-system checks and SQL queries.

When traffic citation records, court data exports, or any other pipe-delimited
.txt files come in, this module does what a QA analyst does manually:
  1. Reads the file, maps columns from the header row
  2. Parses every record into a structured dict
  3. Runs anomaly detection patterns against each record
  4. Flags findings with record-level detail (row number, field values)
  5. Produces a JSON report per file — one file, one audit, one report

Anomaly patterns live in data/audit/anomaly_patterns/ as JSON files.
Add a new pattern by dropping a new JSON file — no code changes needed.

Example file format (pipe-delimited, header on line 1):
    casenumber|casestatus|defendantfirstname|defendantmiddlename|defendantlastname|...
    2025CR39429|DEFERRED|Steve||Lawton|...

Critical fields for traffic citations:
    casenumber, casestatus, defendantfirstname, defendantlastname,
    dob, casefiledate, dispositiondate, statute, statutedescription,
    dispositiondetail, judgefullname, comments,
    street, city, state, zip
"""

import json
import re
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Canonical field name normalizer
# ---------------------------------------------------------------------------

# Maps common variant column names -> canonical names Rell uses internally
# So "defendant_last_name", "DefendantLastName", "def_last" all resolve the same
_FIELD_ALIASES: Dict[str, str] = {
    # Case identifiers
    "casenumber": "casenumber",
    "case_number": "casenumber",
    "caseid": "casenumber",
    "case_id": "casenumber",

    # Status
    "casestatus": "casestatus",
    "case_status": "casestatus",
    "status": "casestatus",

    # Defendant name
    "defendantfirstname": "defendantfirstname",
    "defendant_first_name": "defendantfirstname",
    "firstname": "defendantfirstname",
    "first_name": "defendantfirstname",

    "defendantmiddlename": "defendantmiddlename",
    "defendant_middle_name": "defendantmiddlename",
    "middlename": "defendantmiddlename",

    "defendantlastname": "defendantlastname",
    "defendant_last_name": "defendantlastname",
    "lastname": "defendantlastname",
    "last_name": "defendantlastname",

    # DOB
    "dob": "dob",
    "dateofbirth": "dob",
    "date_of_birth": "dob",
    "birthdate": "dob",

    # Dates
    "casefiledate": "casefiledate",
    "case_file_date": "casefiledate",
    "filedate": "casefiledate",
    "file_date": "casefiledate",
    "filingdate": "casefiledate",
    "filing_date": "casefiledate",

    "dispositiondate": "dispositiondate",
    "disposition_date": "dispositiondate",
    "dispdate": "dispositiondate",
    "disp_date": "dispositiondate",

    # Charges
    "statute": "statute",
    "statutecode": "statute",
    "statute_code": "statute",

    "statutedescription": "statutedescription",
    "statute_description": "statutedescription",
    "chargedescription": "statutedescription",
    "charge_description": "statutedescription",

    # Disposition
    "dispositiondetail": "dispositiondetail",
    "disposition_detail": "dispositiondetail",
    "disposition": "dispositiondetail",

    # Judge
    "judgefullname": "judgefullname",
    "judge_full_name": "judgefullname",
    "judge": "judgefullname",
    "judgename": "judgefullname",

    # Comments
    "comments": "comments",
    "comment": "comments",
    "notes": "comments",

    # Address
    "street": "street",
    "streetaddress": "street",
    "street_address": "street",
    "address": "street",

    "city": "city",
    "state": "state",
    "statecode": "state",
    "zip": "zip",
    "zipcode": "zip",
    "zip_code": "zip",
    "postalcode": "zip",
}


def normalize_field(name: str) -> str:
    """Normalize a raw column header to the canonical field name."""
    return _FIELD_ALIASES.get(name.lower().strip().replace(" ", ""), name.lower().strip())


# ---------------------------------------------------------------------------
# Flat File Parser
# ---------------------------------------------------------------------------

class FlatFileParser:
    """
    Reads a pipe-delimited .txt file with a header row on line 1.
    Returns a list of record dicts with normalized field names.

    Also handles:
    - Extra whitespace around pipes
    - Missing trailing fields (short rows)
    - Empty string vs. genuinely missing fields
    - BOM characters in the header (common in Windows exports)
    - Multiple encodings (tries UTF-8, then latin-1)
    """

    DELIMITER = "|"

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.raw_headers: List[str] = []
        self.canonical_headers: List[str] = []
        self.records: List[Dict[str, str]] = []
        self.parse_errors: List[Dict[str, Any]] = []
        self.line_count = 0
        self.record_count = 0

    def parse(self) -> "FlatFileParser":
        """
        Read and parse the file. Returns self for chaining.
        Call .records for the parsed result after parsing.
        """
        content = self._read_file()
        lines = content.splitlines()

        if not lines:
            self.parse_errors.append({"error": "File is empty", "line": 0})
            return self

        # Line 1 = header row
        header_line = lines[0].lstrip("\ufeff")  # strip BOM
        self.raw_headers = [h.strip() for h in header_line.split(self.DELIMITER)]
        self.canonical_headers = [normalize_field(h) for h in self.raw_headers]
        self.line_count = len(lines)

        # Lines 2+ = records
        for i, line in enumerate(lines[1:], start=2):
            line = line.strip()
            if not line:
                continue  # skip blank lines

            fields = [f.strip() for f in line.split(self.DELIMITER)]

            # Pad short rows with empty strings
            while len(fields) < len(self.canonical_headers):
                fields.append("")

            record = {
                self.canonical_headers[j]: fields[j]
                for j in range(len(self.canonical_headers))
            }
            record["_row"] = i        # original line number for finding references
            record["_raw"] = line     # raw line for context in reports
            self.records.append(record)
            self.record_count += 1

        return self

    def _read_file(self) -> str:
        """Try UTF-8 first, fall back to latin-1 (common in court data exports)."""
        try:
            return self.filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return self.filepath.read_text(encoding="latin-1")

    def summary(self) -> Dict[str, Any]:
        return {
            "filepath": str(self.filepath),
            "filename": self.filepath.name,
            "line_count": self.line_count,
            "record_count": self.record_count,
            "fields_detected": self.canonical_headers,
            "raw_headers": self.raw_headers,
            "parse_errors": self.parse_errors,
        }


# ---------------------------------------------------------------------------
# Anomaly Pattern Definitions
# ---------------------------------------------------------------------------

class AnomalyPattern:
    """
    A single anomaly detection rule.

    Patterns are loaded from JSON files in data/audit/anomaly_patterns/.
    Each pattern defines:
      - id:          Unique identifier
      - name:        Human-readable name
      - description: What this anomaly means in practice
      - severity:    CRITICAL | HIGH | MEDIUM | LOW
      - check_type:  The kind of check (see supported types below)
      - fields:      Which field(s) to examine
      - parameters:  Check-specific thresholds and logic

    Supported check_types:
      placeholder_date     - field value is a known placeholder (e.g. 1900-01-01)
      missing_required     - field is empty or null for a critical field
      date_lag_exceeded    - days between two date fields exceeds threshold
      date_before_other    - date field A comes before date field B (shouldn't happen)
      future_date          - date field is in the future (usually an error)
      value_not_in_set     - field value not in an allowed set
      regex_mismatch       - field doesn't match expected pattern
      cross_field          - compound logic across multiple fields (Python expression)
    """

    def __init__(self, pattern_def: Dict[str, Any]):
        self.id = pattern_def["id"]
        self.name = pattern_def["name"]
        self.description = pattern_def.get("description", "")
        self.severity = pattern_def.get("severity", "MEDIUM")
        self.check_type = pattern_def["check_type"]
        self.fields = pattern_def.get("fields", [])
        self.parameters = pattern_def.get("parameters", {})
        self.rell_assessment = pattern_def.get("rell_assessment", "")
        self.suggested_fix = pattern_def.get("suggested_fix", "Manual review required.")

    def check(self, record: Dict[str, str], today: Optional[date] = None) -> Optional[Dict[str, Any]]:
        """
        Evaluate this pattern against a single record.
        Returns a finding dict if the anomaly fires, None if clean.
        """
        today = today or date.today()
        try:
            return self._dispatch(record, today)
        except Exception as e:
            # Don't let a bad record crash the whole scan
            return {
                "pattern_error": True,
                "pattern_id": self.id,
                "error": str(e),
                "row": record.get("_row"),
            }

    def _dispatch(self, r: Dict[str, str], today: date) -> Optional[Dict[str, Any]]:
        ct = self.check_type

        if ct == "placeholder_date":
            return self._check_placeholder_date(r)

        if ct == "missing_required":
            return self._check_missing_required(r)

        if ct == "date_lag_exceeded":
            return self._check_date_lag(r, today)

        if ct == "date_before_other":
            return self._check_date_order(r)

        if ct == "future_date":
            return self._check_future_date(r, today)

        if ct == "value_not_in_set":
            return self._check_value_set(r)

        if ct == "regex_mismatch":
            return self._check_regex(r)

        if ct == "cross_field":
            return self._check_cross_field(r, today)

        return None

    # ------------------------------------------------------------------
    # Individual check implementations
    # ------------------------------------------------------------------

    def _check_placeholder_date(self, r: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """
        Fire if any of the specified date fields contain a known placeholder value.
        Default placeholders: 1900-01-01, 1899-12-30, 9999-12-31, 01/01/1900, etc.
        """
        placeholders = self.parameters.get("placeholder_values", [
            "1900-01-01", "1899-12-30", "9999-12-31", "9999-01-01",
            "01/01/1900", "1/1/1900", "01-01-1900",
        ])
        for field in self.fields:
            val = r.get(field, "").strip()
            if val in placeholders:
                return self._make_finding(
                    r, field, val,
                    f"Field `{field}` contains placeholder date `{val}` — this is a system default, not a real date."
                )
        return None

    def _check_missing_required(self, r: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Fire if any required field is empty or whitespace-only."""
        for field in self.fields:
            val = r.get(field, "").strip()
            if not val:
                return self._make_finding(
                    r, field, val,
                    f"Required field `{field}` is empty. "
                    f"CaseNumber: {r.get('casenumber', 'UNKNOWN')}"
                )
        return None

    def _check_date_lag(self, r: Dict[str, str], today: date) -> Optional[Dict[str, Any]]:
        """
        Fire if (field_b - field_a) exceeds max_days, or if field_b is placeholder
        but field_a is older than expected_days_to_dispose.

        Example: casefiledate is 8 months ago, dispositiondate is 1900-01-01
        -> anomaly: case likely disposed but disposition not recorded.
        """
        field_a = self.parameters.get("from_field")   # earlier date (e.g. casefiledate)
        field_b = self.parameters.get("to_field")     # later date (e.g. dispositiondate)
        max_days = self.parameters.get("max_days", 180)
        placeholder_check = self.parameters.get("check_placeholder_with_age", False)
        placeholder_values = self.parameters.get("placeholder_values", ["1900-01-01"])

        date_a = _parse_date(r.get(field_a, ""))
        date_b_raw = r.get(field_b, "").strip()
        date_b = _parse_date(date_b_raw)

        if date_a is None:
            return None  # Can't assess without a start date

        # Case: disposition is a placeholder but the case is old enough that it should be disposed
        if placeholder_check and date_b_raw in placeholder_values:
            age_days = (today - date_a).days
            if age_days > max_days:
                return self._make_finding(
                    r, field_b, date_b_raw,
                    f"Case filed {age_days} days ago (on {date_a}) but `{field_b}` is placeholder `{date_b_raw}`. "
                    f"Expected disposition within {max_days} days for this case type."
                )
            return None

        # Case: both dates present, check elapsed time
        if date_b is not None:
            lag_days = (date_b - date_a).days
            if lag_days > max_days:
                return self._make_finding(
                    r, field_b, date_b_raw,
                    f"Lag between `{field_a}` ({date_a}) and `{field_b}` ({date_b}) "
                    f"is {lag_days} days — exceeds {max_days}-day threshold."
                )

        return None

    def _check_date_order(self, r: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Fire if field_a comes AFTER field_b (date ordering violation)."""
        field_a = self.parameters.get("earlier_field")
        field_b = self.parameters.get("later_field")

        date_a = _parse_date(r.get(field_a, ""))
        date_b = _parse_date(r.get(field_b, ""))

        if date_a is None or date_b is None:
            return None

        if date_a > date_b:
            return self._make_finding(
                r, field_a, str(date_a),
                f"`{field_a}` ({date_a}) is AFTER `{field_b}` ({date_b}) — this ordering is invalid."
            )
        return None

    def _check_future_date(self, r: Dict[str, str], today: date) -> Optional[Dict[str, Any]]:
        """Fire if a date field is in the future beyond an optional tolerance."""
        tolerance_days = self.parameters.get("tolerance_days", 0)
        for field in self.fields:
            val = r.get(field, "").strip()
            d = _parse_date(val)
            if d is not None and (d - today).days > tolerance_days:
                return self._make_finding(
                    r, field, val,
                    f"`{field}` ({d}) is {(d - today).days} days in the future. "
                    f"Likely a data entry error."
                )
        return None

    def _check_value_set(self, r: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Fire if field value is not in the allowed set."""
        allowed = [v.upper() for v in self.parameters.get("allowed_values", [])]
        case_sensitive = self.parameters.get("case_sensitive", False)

        for field in self.fields:
            val = r.get(field, "").strip()
            if not val:
                continue  # missing fields handled by missing_required pattern
            compare_val = val if case_sensitive else val.upper()
            if allowed and compare_val not in allowed:
                return self._make_finding(
                    r, field, val,
                    f"`{field}` value `{val}` is not in the allowed set: {allowed[:10]}"
                    + (" (partial list)" if len(allowed) > 10 else "")
                )
        return None

    def _check_regex(self, r: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Fire if field does not match the expected regex pattern."""
        pattern = self.parameters.get("pattern", "")
        if not pattern:
            return None
        for field in self.fields:
            val = r.get(field, "").strip()
            if val and not re.match(pattern, val, re.IGNORECASE):
                return self._make_finding(
                    r, field, val,
                    f"`{field}` value `{val}` does not match expected format `{pattern}`."
                )
        return None

    def _check_cross_field(self, r: Dict[str, str], today: date) -> Optional[Dict[str, Any]]:
        """
        Fire based on a combination of field conditions.
        Defined as a list of condition objects in parameters["conditions"].

        Operator: "AND" (default) or "OR"
        Each condition: {"field": "...", "check": "empty|not_empty|eq|ne|placeholder_date|..."}
        """
        conditions = self.parameters.get("conditions", [])
        operator = self.parameters.get("operator", "AND").upper()
        placeholders = ["1900-01-01", "1899-12-30", "9999-12-31"]

        results = []
        for cond in conditions:
            field = cond.get("field", "")
            check = cond.get("check", "")
            value = cond.get("value", "")
            val = r.get(field, "").strip()

            if check == "empty":
                results.append(not val)
            elif check == "not_empty":
                results.append(bool(val))
            elif check == "eq":
                results.append(val.lower() == str(value).lower())
            elif check == "ne":
                results.append(val.lower() != str(value).lower())
            elif check == "placeholder_date":
                results.append(val in placeholders)
            elif check == "not_placeholder_date":
                results.append(val not in placeholders and bool(val))
            elif check == "older_than_days":
                d = _parse_date(val)
                if d:
                    results.append((today - d).days > int(value))
                else:
                    results.append(False)
            else:
                results.append(False)

        fires = all(results) if operator == "AND" else any(results)
        if fires:
            involved_fields = [c.get("field") for c in conditions]
            involved_values = {f: r.get(f, "") for f in involved_fields}
            return self._make_finding(
                r, ", ".join(involved_fields), str(involved_values),
                self.description or f"Cross-field anomaly detected: {involved_values}"
            )
        return None

    # ------------------------------------------------------------------
    # Finding builder
    # ------------------------------------------------------------------

    def _make_finding(
        self, r: Dict[str, str], field: str, value: str, observation: str
    ) -> Dict[str, Any]:
        return {
            "pattern_id": self.id,
            "pattern_name": self.name,
            "severity": self.severity,
            "field": field,
            "value": value,
            "observation": observation,
            "rell_assessment": self.rell_assessment,
            "suggested_fix": self.suggested_fix,
            "casenumber": r.get("casenumber", "UNKNOWN"),
            "row": r.get("_row", "?"),
            "record_snapshot": {
                k: v for k, v in r.items()
                if not k.startswith("_") and v.strip()
            }
        }


# ---------------------------------------------------------------------------
# Anomaly Pattern Library
# ---------------------------------------------------------------------------

class AnomalyPatternLibrary:
    """
    Loads and manages all anomaly patterns from data/audit/anomaly_patterns/.
    Drop a new JSON file in that directory to add a pattern — no code changes.

    Pattern files can define one pattern (a single dict) or multiple (a list).
    """

    def __init__(self, patterns_path: str):
        self.patterns_path = Path(patterns_path)
        self.patterns: List[AnomalyPattern] = []
        self._loaded = False

    def load(self) -> "AnomalyPatternLibrary":
        """Load all pattern JSON files from the patterns directory."""
        self.patterns = []
        if not self.patterns_path.exists():
            self.patterns_path.mkdir(parents=True, exist_ok=True)
            return self

        for pattern_file in sorted(self.patterns_path.glob("*.json")):
            try:
                with open(pattern_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)

                # Pattern file can be a single dict or a list of dicts
                if isinstance(raw, list):
                    for p in raw:
                        self.patterns.append(AnomalyPattern(p))
                else:
                    self.patterns.append(AnomalyPattern(raw))
            except Exception as e:
                print(f"[AnomalyPatternLibrary] Failed to load {pattern_file.name}: {e}")

        self._loaded = True
        return self

    def is_loaded(self) -> bool:
        return self._loaded

    def list_patterns(self) -> List[str]:
        return [f"{p.id} [{p.severity}] — {p.name}" for p in self.patterns]

    def get_by_id(self, pattern_id: str) -> Optional[AnomalyPattern]:
        return next((p for p in self.patterns if p.id == pattern_id), None)


# ---------------------------------------------------------------------------
# Flat File Audit Engine
# ---------------------------------------------------------------------------

class FlatFileAuditEngine:
    """
    Scans a pipe-delimited .txt file against all loaded anomaly patterns.
    Produces a structured JSON report per file.

    This is Rell's flat-file audit layer:
    - Parses the file via FlatFileParser
    - Runs every AnomalyPattern against every record
    - Builds a structured report with finding detail + statistics
    - Writes report to data/audit/memory/reports/<filename>_audit.json
    - Writes a markdown summary alongside it

    The output format mirrors the SQL and file-system audit reports
    so Rell's voice is consistent across all three domains.
    """

    def __init__(
        self,
        patterns_path: str,
        reports_path: str,
    ):
        self.pattern_library = AnomalyPatternLibrary(patterns_path).load()
        self.reports_path = Path(reports_path)
        self.reports_path.mkdir(parents=True, exist_ok=True)

        if self.pattern_library.patterns:
            print(
                f"[FlatFileAuditEngine] {len(self.pattern_library.patterns)} anomaly patterns loaded: "
                f"{[p.id for p in self.pattern_library.patterns]}"
            )
        else:
            print(
                "[FlatFileAuditEngine] No anomaly patterns found. "
                "Add JSON pattern files to data/audit/anomaly_patterns/"
            )

    def scan_file(self, filepath: str, feed_label: Optional[str] = None) -> Dict[str, Any]:
        """
        Scan one .txt file. Parse it, run all anomaly patterns, write reports.

        Args:
            filepath:   Path to the pipe-delimited .txt file.
            feed_label: Optional label for the feed (e.g. "TXTRSTS", "FLHILDF").
                        If not provided, derived from filename.

        Returns:
            Full audit report dict.
        """
        fpath = Path(filepath)
        feed_label = feed_label or fpath.stem.upper()

        print(f"[FlatFileAuditEngine] Scanning: {fpath.name} (feed: {feed_label})")

        # 1. Parse file
        parser = FlatFileParser(filepath)
        parser.parse()

        if parser.parse_errors and not parser.records:
            return {
                "status": "parse_failed",
                "filepath": str(fpath),
                "feed_label": feed_label,
                "errors": parser.parse_errors,
            }

        # 2. Detect missing critical fields in schema
        schema_warnings = self._check_schema_coverage(parser.canonical_headers)

        # 3. Run anomaly patterns against every record
        all_findings: List[Dict[str, Any]] = []
        today = date.today()

        for record in parser.records:
            for pattern in self.pattern_library.patterns:
                finding = pattern.check(record, today)
                if finding:
                    finding["feed_label"] = feed_label
                    all_findings.append(finding)

        # 4. Build report
        report = self._build_report(
            fpath, feed_label, parser, all_findings, schema_warnings
        )

        # 5. Write reports to disk
        json_path, md_path = self._write_reports(fpath.stem, report)
        report["output_files"] = {
            "json_report": str(json_path),
            "markdown_report": str(md_path),
        }

        print(
            f"[FlatFileAuditEngine] {feed_label}: {parser.record_count} records scanned, "
            f"{len(all_findings)} findings."
        )
        return report

    def scan_intake_folder(
        self,
        intake_path: str,
        feed_label_map: Optional[Dict[str, str]] = None,
        archive: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Scan all .txt files in an intake folder.
        Optionally archive scanned files to data/audit/intake/processed/.

        Args:
            intake_path:    Path to directory containing .txt files.
            feed_label_map: Optional map of filename (without ext) -> feed label.
            archive:        If True, move processed files to intake/processed/.

        Returns:
            List of per-file report dicts.
        """
        intake = Path(intake_path)
        txt_files = list(intake.glob("*.txt"))

        if not txt_files:
            print(f"[FlatFileAuditEngine] No .txt files found in {intake_path}")
            return []

        print(f"[FlatFileAuditEngine] Found {len(txt_files)} file(s) in {intake_path}")
        reports = []
        feed_label_map = feed_label_map or {}

        for txt_file in sorted(txt_files):
            feed_label = feed_label_map.get(txt_file.stem, None)
            report = self.scan_file(str(txt_file), feed_label)
            reports.append(report)

            if archive and report.get("status") != "parse_failed":
                processed_dir = intake / "processed"
                processed_dir.mkdir(exist_ok=True)
                target = processed_dir / txt_file.name
                txt_file.rename(target)
                print(f"  Archived: {txt_file.name} -> processed/")

        return reports

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_schema_coverage(self, detected_headers: List[str]) -> List[str]:
        """Warn if any of the standard critical fields are absent from the file."""
        critical_fields = [
            "casenumber", "casestatus", "defendantfirstname", "defendantlastname",
            "casefiledate", "dispositiondate", "statute", "dispositiondetail"
        ]
        warnings = []
        for f in critical_fields:
            if f not in detected_headers:
                warnings.append(f"Critical field `{f}` not found in file headers.")
        return warnings

    def _build_report(
        self,
        fpath: Path,
        feed_label: str,
        parser: FlatFileParser,
        findings: List[Dict[str, Any]],
        schema_warnings: List[str],
    ) -> Dict[str, Any]:
        """Build the full structured report dict."""
        now = datetime.now().isoformat()

        by_severity: Dict[str, int] = {}
        by_pattern: Dict[str, int] = {}
        by_case: Dict[str, List] = {}

        for f in findings:
            sev = f.get("severity", "INFO")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            pid = f.get("pattern_id", "unknown")
            by_pattern[pid] = by_pattern.get(pid, 0) + 1
            cn = f.get("casenumber", "UNKNOWN")
            by_case.setdefault(cn, []).append(f)

        # Cases with multiple anomalies — most concerning
        multi_anomaly_cases = sorted(
            [(cn, len(fs)) for cn, fs in by_case.items() if len(fs) > 1],
            key=lambda x: x[1],
            reverse=True
        )

        return {
            "status": "complete",
            "feed_label": feed_label,
            "filepath": str(fpath),
            "filename": fpath.name,
            "scanned_at": now,
            "record_count": parser.record_count,
            "finding_count": len(findings),
            "fields_detected": parser.canonical_headers,
            "schema_warnings": schema_warnings,
            "summary": {
                "record_count": parser.record_count,
                "finding_count": len(findings),
                "by_severity": by_severity,
                "by_pattern": by_pattern,
                "cases_with_multiple_anomalies": multi_anomaly_cases[:20],
            },
            "findings": findings,
            "rell_assessment": self._rell_assessment(
                parser.record_count, findings, by_severity, by_pattern, schema_warnings
            ),
        }

    def _rell_assessment(
        self,
        record_count: int,
        findings: List[Dict[str, Any]],
        by_severity: Dict[str, int],
        by_pattern: Dict[str, int],
        schema_warnings: List[str],
    ) -> str:
        """Rell's plain-language assessment of the flat file scan."""
        if not findings and not schema_warnings:
            return (
                f"I scanned {record_count:,} records and found nothing to flag. "
                f"The fields are populated, the dates are coherent, the patterns hold. "
                f"I'd call this clean — though I note that clean under current patterns "
                f"doesn't mean clean under patterns we haven't defined yet."
            )

        critical = by_severity.get("CRITICAL", 0)
        high = by_severity.get("HIGH", 0)
        total = len(findings)

        if critical > 0:
            opener = (
                f"I need to stop here. Out of {record_count:,} records, "
                f"I found {critical} critical anomal{'y' if critical == 1 else 'ies'}. "
                f"These cannot be delivered without resolution."
            )
        elif high > 0:
            opener = (
                f"This file needs attention before delivery. "
                f"{total} anomal{'y' if total == 1 else 'ies'} across {record_count:,} records — "
                f"{high} of them high severity."
            )
        else:
            opener = (
                f"{total} anomal{'y' if total == 1 else 'ies'} found across {record_count:,} records. "
                f"None are critical, but these should be documented and investigated "
                f"before the next delivery cycle."
            )

        # Call out dominant patterns
        pattern_line = ""
        if by_pattern:
            top = sorted(by_pattern.items(), key=lambda x: x[1], reverse=True)[:3]
            pattern_line = " Most common: " + ", ".join(
                f"`{pid}` ({cnt})" for pid, cnt in top
            ) + "."

        schema_line = ""
        if schema_warnings:
            schema_line = (
                f" Also note: {len(schema_warnings)} expected field(s) were absent from this file. "
                f"This may mean the format changed."
            )

        return opener + pattern_line + schema_line

    def _write_reports(self, stem: str, report: Dict[str, Any]) -> Tuple[Path, Path]:
        """Write JSON and Markdown reports. Returns (json_path, md_path)."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = self.reports_path / f"{stem}_audit_{ts}.json"
        md_path = self.reports_path / f"{stem}_audit_{ts}.md"

        # JSON report
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

        # Markdown report
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self._format_markdown(report))

        return json_path, md_path

    def _format_markdown(self, report: Dict[str, Any]) -> str:
        """Format the report as a readable markdown document."""
        feed = report.get("feed_label", "Unknown Feed")
        filename = report.get("filename", "")
        scanned_at = report.get("scanned_at", "")[:19]
        record_count = report.get("record_count", 0)
        findings = report.get("findings", [])
        summary = report.get("summary", {})
        by_sev = summary.get("by_severity", {})
        schema_warnings = report.get("schema_warnings", [])

        lines = [
            f"# Flat File Audit — {feed}",
            f"",
            f"**File:** `{filename}`  ",
            f"**Scanned:** {scanned_at}  ",
            f"**Records:** {record_count:,}  ",
            f"**Findings:** {len(findings)}  ",
        ]

        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            cnt = by_sev.get(sev, 0)
            if cnt > 0:
                icons = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}
                lines.append(f"**{icons[sev]} {sev}:** {cnt}  ")

        lines += ["", "---", "", "## Rell's Assessment", "", report.get("rell_assessment", ""), "", "---", ""]

        if schema_warnings:
            lines += ["## Schema Warnings", ""]
            for w in schema_warnings:
                lines.append(f"- {w}")
            lines += ["", "---", ""]

        if findings:
            lines += [f"## Findings ({len(findings)})", ""]
            for i, f in enumerate(findings, 1):
                sev = f.get("severity", "INFO")
                icons = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}
                icon = icons.get(sev, "⚪")
                lines += [
                    f"### {i}. {icon} [{sev}] {f.get('pattern_name', 'Unknown Pattern')}",
                    f"",
                    f"**Case:** `{f.get('casenumber', 'UNKNOWN')}` (row {f.get('row', '?')})  ",
                    f"**Field:** `{f.get('field', '')}` = `{f.get('value', '')}`  ",
                    f"",
                    f"**Observation:** {f.get('observation', '')}",
                    f"",
                    f"**Rell's Assessment:** {f.get('rell_assessment', '')}",
                    f"",
                    f"**Suggested Fix:** {f.get('suggested_fix', '')}",
                    f"",
                    f"---",
                    f"",
                ]
        else:
            lines += ["## Findings", "", "*No anomalies detected.*", ""]

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper: date parsing
# ---------------------------------------------------------------------------

def _parse_date(val: str) -> Optional[date]:
    """
    Parse a date string in multiple common formats.
    Returns None if unparseable (rather than crashing).
    """
    if not val or not val.strip():
        return None
    val = val.strip()

    formats = [
        "%Y-%m-%d",      # 2025-03-15
        "%m/%d/%Y",      # 03/15/2025
        "%m-%d-%Y",      # 03-15-2025
        "%Y/%m/%d",      # 2025/03/15
        "%d/%m/%Y",      # 15/03/2025
        "%m/%d/%y",      # 03/15/25
        "%Y-%m-%dT%H:%M:%S",  # ISO with time
        "%Y-%m-%d %H:%M:%S",  # datetime string
    ]
    for fmt in formats:
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None
