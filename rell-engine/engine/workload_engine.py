"""
workload_engine.py - Workload Scoring, Analysis, and Assignment Advisory

This is Rell's fourth audit domain — workforce load intelligence.

The question this engine answers is: given a set of feeds and a set of analysts,
who is carrying how much, and when a new feed comes in, who should get it?

Three classes:

WorkloadScorer
    Computes workload points for a feed row from raw columns (volume, frequency,
    time). The formula lives in data/audit/workload/scoring_config.json — swap
    weights without touching this file. If the row already has a pre-calculated
    points value from the Excel, that can be used directly too.

WorkloadAnalyzer
    Takes a list of scored feed rows and builds per-analyst load summaries:
    total points, feed count, heaviest feeds, lightest feeds. Flags analysts
    who are over or under the team average by a configurable threshold.

AssignmentAdvisor
    Given a new incoming feed with its own attributes (volume, frequency, time),
    scores it and recommends which analyst should receive it — the one with the
    most available capacity, weighted by existing load.

WorkloadAuditEngine
    Orchestrates the above: reads a workbook via excel_parser.WorkbookParser,
    scores all rows, runs analysis, produces a JSON + Markdown report.

All output drops in data/audit/memory/reports/ with Rell's voice throughout.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Frequency normalizer
# ---------------------------------------------------------------------------

#: Maps string frequency values to a numeric multiplier representing
#: deliveries per month. Used in the scoring formula.
FREQUENCY_TO_MONTHLY: Dict[str, float] = {
    # Daily
    "daily": 22.0,
    "weekday": 22.0,
    "workday": 22.0,
    "business day": 22.0,
    "businessday": 22.0,
    "everyday": 30.0,
    "7days": 30.0,

    # Weekly
    "weekly": 4.33,
    "week": 4.33,
    "per week": 4.33,
    "biweekly": 2.17,  # every 2 weeks
    "bi-weekly": 2.17,
    "every 2 weeks": 2.17,
    "every two weeks": 2.17,

    # Monthly
    "monthly": 1.0,
    "month": 1.0,
    "per month": 1.0,
    "once a month": 1.0,

    # Quarterly
    "quarterly": 0.33,
    "quarter": 0.33,
    "every 3 months": 0.33,

    # Semi-annual
    "semi-annual": 0.17,
    "semiannual": 0.17,
    "twice a year": 0.17,
    "biannual": 0.17,

    # Annual
    "annual": 0.083,
    "yearly": 0.083,
    "once a year": 0.083,
    "annually": 0.083,

    # Ad hoc / one-time
    "ad hoc": 0.5,
    "adhoc": 0.5,
    "on demand": 0.5,
    "as needed": 0.5,
    "one-time": 0.083,
    "onetime": 0.083,
}


def normalize_frequency(raw: Any) -> float:
    """
    Convert a frequency string or number to a monthly delivery multiplier.

    Returns 1.0 (monthly) as default if unknown.
    """
    if isinstance(raw, (int, float)):
        return float(raw)
    if not raw:
        return 1.0
    key = str(raw).lower().strip()
    return FREQUENCY_TO_MONTHLY.get(key, 1.0)


# ---------------------------------------------------------------------------
# Workload Scorer
# ---------------------------------------------------------------------------

class WorkloadScorer:
    """
    Calculates workload points for a single feed row.

    Default formula:
        monthly_volume    = volume * frequency_multiplier
        volume_points     = (monthly_volume / volume_unit) * volume_weight
        time_points       = (time_minutes / 60) * time_weight * frequency_multiplier
        difficulty_points = difficulty * difficulty_weight
        total_points      = volume_points + time_points + difficulty_points

    All weights and units come from scoring_config.json — no code changes
    needed to adjust the formula.

    If the row already contains a pre-calculated 'workload_points' value
    from the Excel, that value is used directly (use_excel_score=True).
    The scorer can also validate the Excel score against its own calculation
    and flag significant deviations.
    """

    DEFAULT_CONFIG: Dict[str, Any] = {
        "_comment": (
            "Edit these weights to tune the scoring formula. "
            "volume_unit: records per 1 point of volume score (e.g. 1000000 = 1pt per million). "
            "time_weight: points per hour of QA time, scaled by frequency. "
            "difficulty_weight: multiplier on raw difficulty score (1-5 scale). "
            "deviation_alert_pct: flag if Excel score deviates from calculated by this %. "
        ),
        "volume_unit": 1000000,
        "volume_weight": 1.0,
        "time_weight": 0.5,
        "difficulty_weight": 0.5,
        "deviation_alert_pct": 20,
        "use_excel_score": True,
        "recalculate_for_validation": True,
        "frequency_defaults": {
            "unknown": 1.0
        },
        "overload_threshold_pct": 25,
        "underload_threshold_pct": 25,
        "max_recommended_points": 20.0
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score a single feed record. Returns:
        {
            "workload_points": float,
            "source": "excel" | "calculated" | "partial",
            "calculation_detail": { ... },
            "validation_warning": str or None
        }
        """
        freq_raw = record.get("frequency", "") or record.get("cadence", "")
        freq_mult = normalize_frequency(freq_raw)

        volume = _to_float(record.get("volume", 0))
        time_minutes = _to_float(record.get("time_minutes", 0)) or (
            _to_float(record.get("time_hours", 0)) * 60
        )
        difficulty = _to_float(record.get("difficulty", 0))

        volume_unit = float(self.config.get("volume_unit", 1_000_000))
        volume_weight = float(self.config.get("volume_weight", 1.0))
        time_weight = float(self.config.get("time_weight", 0.5))
        difficulty_weight = float(self.config.get("difficulty_weight", 0.5))

        # Monthly equivalents
        monthly_volume = volume * freq_mult
        volume_points = (monthly_volume / volume_unit) * volume_weight if volume_unit else 0.0
        time_points = (time_minutes / 60.0) * time_weight * freq_mult
        difficulty_points = difficulty * difficulty_weight

        calculated = round(volume_points + time_points + difficulty_points, 4)

        detail = {
            "frequency_multiplier": freq_mult,
            "monthly_volume": round(monthly_volume, 0),
            "volume_points": round(volume_points, 4),
            "time_points": round(time_points, 4),
            "difficulty_points": round(difficulty_points, 4),
            "calculated_total": calculated,
        }

        excel_score = _to_float(record.get("workload_points", None))
        use_excel = self.config.get("use_excel_score", True)
        validate = self.config.get("recalculate_for_validation", True)
        deviation_pct = float(self.config.get("deviation_alert_pct", 20))

        validation_warning = None
        final_score = calculated
        source = "calculated"

        if excel_score is not None and excel_score > 0:
            if use_excel:
                final_score = excel_score
                source = "excel"
                if validate and calculated > 0:
                    dev = abs(excel_score - calculated) / calculated * 100
                    if dev > deviation_pct:
                        validation_warning = (
                            f"Excel score ({excel_score}) deviates {dev:.1f}% from calculated "
                            f"({calculated}). Check scoring parameters."
                        )
            else:
                source = "calculated"
        elif excel_score is None and volume == 0 and time_minutes == 0:
            source = "partial"

        return {
            "workload_points": round(final_score, 4),
            "source": source,
            "calculation_detail": detail,
            "validation_warning": validation_warning,
        }


# ---------------------------------------------------------------------------
# Workload Analyzer
# ---------------------------------------------------------------------------

class WorkloadAnalyzer:
    """
    Analyzes scored feed rows to produce per-analyst load summaries.

    Input:  list of records (dicts), each with 'assignee' and 'workload_points'
    Output: per-analyst breakdown + team comparison + overload/underload flags
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or WorkloadScorer.DEFAULT_CONFIG
        self.overload_threshold_pct = float(
            self.config.get("overload_threshold_pct", 25)
        )
        self.underload_threshold_pct = float(
            self.config.get("underload_threshold_pct", 25)
        )
        self.max_recommended = float(
            self.config.get("max_recommended_points", 20.0)
        )

    def analyze(self, scored_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build per-analyst summaries from scored records.

        Args:
            scored_records: Records with 'assignee', 'workload_points', and
                            optionally 'feed_name', 'feed_id', 'state', 'frequency'.

        Returns:
            Full analysis dict including per-analyst breakdown and team stats.
        """
        # Group feeds by analyst
        by_analyst: Dict[str, List[Dict[str, Any]]] = {}
        unassigned = []

        for r in scored_records:
            assignee = str(r.get("assignee", "")).strip()
            if not assignee:
                unassigned.append(r)
                continue
            by_analyst.setdefault(assignee, []).append(r)

        # Build per-analyst summaries
        analyst_summaries: Dict[str, Dict[str, Any]] = {}
        for analyst, feeds in by_analyst.items():
            analyst_summaries[analyst] = self._summarize_analyst(analyst, feeds)

        # Team stats
        all_points = [a["total_points"] for a in analyst_summaries.values()]
        team_avg = sum(all_points) / len(all_points) if all_points else 0.0
        team_total = sum(all_points)

        # Flag overload / underload
        for analyst, summary in analyst_summaries.items():
            pts = summary["total_points"]
            if team_avg > 0:
                deviation = (pts - team_avg) / team_avg * 100
                summary["deviation_from_avg_pct"] = round(deviation, 1)
                if deviation > self.overload_threshold_pct:
                    summary["load_status"] = "OVERLOADED"
                elif deviation < -self.underload_threshold_pct:
                    summary["load_status"] = "UNDERLOADED"
                else:
                    summary["load_status"] = "BALANCED"
            else:
                summary["deviation_from_avg_pct"] = 0.0
                summary["load_status"] = "UNKNOWN"

            summary["capacity_remaining"] = max(
                0.0, round(self.max_recommended - pts, 4)
            )

        return {
            "analyst_summaries": analyst_summaries,
            "team_stats": {
                "analyst_count": len(analyst_summaries),
                "feed_count": len(scored_records) - len(unassigned),
                "unassigned_count": len(unassigned),
                "total_team_points": round(team_total, 4),
                "average_points_per_analyst": round(team_avg, 4),
                "max_recommended_per_analyst": self.max_recommended,
            },
            "unassigned_feeds": [
                {
                    "feed_name": r.get("feed_name", r.get("feed_id", "UNKNOWN")),
                    "workload_points": r.get("workload_points", 0),
                    "row": r.get("_row"),
                }
                for r in unassigned
            ],
        }

    def _summarize_analyst(
        self, analyst: str, feeds: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        total_pts = sum(_to_float(r.get("workload_points", 0)) for r in feeds)
        sorted_feeds = sorted(feeds, key=lambda r: _to_float(r.get("workload_points", 0)), reverse=True)

        return {
            "analyst": analyst,
            "feed_count": len(feeds),
            "total_points": round(total_pts, 4),
            "feeds": [
                {
                    "feed_name": r.get("feed_name", r.get("feed_id", "UNKNOWN")),
                    "feed_id": r.get("feed_id", r.get("feed_name", "")),
                    "state": r.get("state", ""),
                    "frequency": r.get("frequency", ""),
                    "volume": r.get("volume", ""),
                    "workload_points": r.get("workload_points", 0),
                    "score_source": r.get("_score_source", ""),
                    "validation_warning": r.get("_validation_warning"),
                }
                for r in sorted_feeds
            ],
        }


# ---------------------------------------------------------------------------
# Assignment Advisor
# ---------------------------------------------------------------------------

class AssignmentAdvisor:
    """
    Recommends which analyst should receive an incoming feed.

    Uses the WorkloadAnalyzer output to find the analyst with the most
    remaining capacity. Optionally constrains by state familiarity or
    existing feed type.

    Returns an ordered recommendation list so the user can choose
    the top pick or a backup.
    """

    def __init__(self, analysis: Dict[str, Any], config: Optional[Dict[str, Any]] = None):
        self.analysis = analysis
        self.config = config or WorkloadScorer.DEFAULT_CONFIG

    def recommend(
        self,
        feed_points: float,
        feed_name: str = "incoming feed",
        state: Optional[str] = None,
        preferred_analyst: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Recommend assignment for an incoming feed.

        Args:
            feed_points:        Calculated workload points for the new feed.
            feed_name:          Name/ID of the incoming feed (for report display).
            state:              Optional state code — weights analysts who already
                                handle feeds from that state.
            preferred_analyst:  Optional analyst override — Rell will note if this
                                person is already at capacity.

        Returns:
            Dict with ranked recommendations and Rell's reasoning.
        """
        summaries = self.analysis.get("analyst_summaries", {})
        if not summaries:
            return {
                "feed_name": feed_name,
                "feed_points": feed_points,
                "recommendations": [],
                "rell_reasoning": "No analyst data available. Can't make a recommendation.",
            }

        candidates = []
        for analyst, summary in summaries.items():
            current_pts = summary.get("total_points", 0.0)
            capacity = summary.get("capacity_remaining", 0.0)
            status = summary.get("load_status", "UNKNOWN")
            projected = current_pts + feed_points

            # State familiarity bonus — if analyst already handles feeds in this state
            state_bonus = 0
            if state:
                analyst_states = {
                    str(f.get("state", "")).strip().upper()
                    for f in summary.get("feeds", [])
                }
                if state.upper() in analyst_states:
                    state_bonus = 1  # bump priority

            candidates.append({
                "analyst": analyst,
                "current_points": current_pts,
                "projected_points": round(projected, 4),
                "capacity_remaining": capacity,
                "projected_capacity": round(capacity - feed_points, 4),
                "load_status": status,
                "state_familiar": state_bonus > 0,
                "_sort_key": (
                    # Primary sort: prefer analysts with capacity
                    0 if capacity > feed_points else 1,
                    # Secondary: minimize overload
                    projected,
                    # Tertiary: state familiarity (lower = more familiar)
                    -state_bonus,
                ),
            })

        # Sort by composite key
        candidates.sort(key=lambda c: c["_sort_key"])
        for c in candidates:
            del c["_sort_key"]

        # Reasoning for top pick
        top = candidates[0] if candidates else None
        rell_reasoning = self._rell_reasoning(
            feed_name, feed_points, top, candidates, state, preferred_analyst, summaries
        )

        # Check preferred analyst if given
        preferred_info = None
        if preferred_analyst:
            preferred_info = next(
                (c for c in candidates if c["analyst"].lower() == preferred_analyst.lower()),
                None,
            )

        return {
            "feed_name": feed_name,
            "feed_points": feed_points,
            "state": state,
            "recommendations": candidates,
            "top_pick": candidates[0]["analyst"] if candidates else None,
            "preferred_analyst_status": preferred_info,
            "rell_reasoning": rell_reasoning,
        }

    def _rell_reasoning(
        self,
        feed_name, feed_points, top, candidates, state, preferred, summaries
    ) -> str:
        if not top:
            return "No analysts on record."

        lines = []
        team_avg = self.analysis.get("team_stats", {}).get("average_points_per_analyst", 0)

        top_analyst = top["analyst"]
        top_pts = top["current_points"]
        top_proj = top["projected_points"]

        if top["capacity_remaining"] > feed_points:
            verdict = (
                f"My recommendation is {top_analyst}. "
                f"They're carrying {top_pts:.2f} points against a team average of {team_avg:.2f}. "
                f"Adding this feed ({feed_points:.2f} pts) brings them to {top_proj:.2f} — "
                f"still within acceptable range."
            )
        else:
            verdict = (
                f"No analyst has clean capacity for this feed. "
                f"{top_analyst} is the best available option at {top_pts:.2f} points, "
                f"but this assignment will push them to {top_proj:.2f} — above the recommended ceiling. "
                f"This is a workload risk worth noting."
            )
        lines.append(verdict)

        if state:
            if top.get("state_familiar"):
                lines.append(
                    f"{top_analyst} already handles {state} feeds, "
                    f"which makes the onboarding curve shorter."
                )
            else:
                familiar = [c["analyst"] for c in candidates if c.get("state_familiar")]
                if familiar:
                    lines.append(
                        f"Note: {', '.join(familiar[:2])} already work {state} feeds "
                        f"and may ramp up faster — but their load is higher."
                    )

        if preferred and preferred.lower() != top_analyst.lower():
            pref_data = next(
                (c for c in candidates if c["analyst"].lower() == preferred.lower()), None
            )
            if pref_data:
                if pref_data["projected_capacity"] < 0:
                    lines.append(
                        f"You mentioned {preferred} — they're currently at "
                        f"{pref_data['current_points']:.2f} points. "
                        f"Assigning this feed would put them at {pref_data['projected_points']:.2f}, "
                        f"which exceeds the ceiling. I'd advise against it."
                    )
                else:
                    lines.append(
                        f"You mentioned {preferred} — they could also take this. "
                        f"They'd sit at {pref_data['projected_points']:.2f} points, manageable."
                    )

        return " ".join(lines)


# ---------------------------------------------------------------------------
# Workload Audit Engine
# ---------------------------------------------------------------------------

class WorkloadAuditEngine:
    """
    Orchestrates the full workload audit pipeline:

    1. Parse the workbook (excel_parser.WorkbookParser)
    2. Score every row (WorkloadScorer)
    3. Analyze load distribution (WorkloadAnalyzer)
    4. Produce assignment recommendations (AssignmentAdvisor)
    5. Write JSON + Markdown report to data/audit/memory/reports/

    Usage:
        engine = WorkloadAuditEngine(
            scoring_config_path="data/audit/workload/scoring_config.json",
            reports_path="data/audit/memory/reports/",
        )
        report = engine.scan_workbook("workload_tracker.xlsx")
    """

    def __init__(
        self,
        scoring_config_path: str,
        reports_path: str,
    ):
        self.reports_path = Path(reports_path)
        self.reports_path.mkdir(parents=True, exist_ok=True)

        # Load scoring config (create default if absent)
        config_path = Path(scoring_config_path)
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        else:
            self.config = WorkloadScorer.DEFAULT_CONFIG
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            print(
                f"[WorkloadAuditEngine] Created default scoring config: {config_path}\n"
                f"  Review and edit this file to tune the scoring formula."
            )

        self.scorer = WorkloadScorer(self.config)
        self.analyzer = WorkloadAnalyzer(self.config)

    def scan_workbook(
        self,
        filepath: str,
        sheet_name: Optional[str] = None,
        incoming_feed: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Scan one workbook file, produce analysis and report.

        Args:
            filepath:      Path to .xlsx or .csv workbook.
            sheet_name:    Sheet/tab name for .xlsx (None = first sheet).
            incoming_feed: Optional dict describing a new feed to assign:
                           {"feed_name": "...", "volume": N, "frequency": "weekly",
                            "time_minutes": N, "difficulty": N, "state": "TX"}

        Returns:
            Full audit report dict.
        """
        from excel_parser import WorkbookParser

        fpath = Path(filepath)
        print(f"[WorkloadAuditEngine] Scanning: {fpath.name}")

        parser = WorkbookParser(filepath, sheet_name=sheet_name)
        parser.parse()

        if parser.parse_errors and not parser.records:
            return {
                "status": "parse_failed",
                "filepath": str(fpath),
                "errors": parser.parse_errors,
            }

        # Score every row
        scored = []
        for record in parser.records:
            score_result = self.scorer.score(record)
            record["workload_points"] = score_result["workload_points"]
            record["_score_source"] = score_result["source"]
            record["_validation_warning"] = score_result.get("validation_warning")
            record["_calc_detail"] = score_result["calculation_detail"]
            scored.append(record)

        # Analyze distribution
        analysis = self.analyzer.analyze(scored)

        # Assignment recommendation for incoming feed
        recommendation = None
        if incoming_feed:
            incoming_score = self.scorer.score(incoming_feed)
            advisor = AssignmentAdvisor(analysis, self.config)
            recommendation = advisor.recommend(
                feed_points=incoming_score["workload_points"],
                feed_name=incoming_feed.get("feed_name", incoming_feed.get("feed_id", "New Feed")),
                state=incoming_feed.get("state"),
                preferred_analyst=incoming_feed.get("preferred_analyst"),
            )

        # Validation warnings across all rows
        validation_warnings = [
            {
                "row": r.get("_row"),
                "feed": r.get("feed_name", r.get("feed_id", "?")),
                "warning": r["_validation_warning"],
            }
            for r in scored
            if r.get("_validation_warning")
        ]

        report = self._build_report(
            fpath, parser, analysis, validation_warnings, recommendation
        )

        json_path, md_path = self._write_reports(fpath.stem, report)
        report["output_files"] = {
            "json_report": str(json_path),
            "markdown_report": str(md_path),
        }

        print(
            f"[WorkloadAuditEngine] {len(scored)} feeds scored. "
            f"{analysis['team_stats']['analyst_count']} analysts. "
            f"{len(validation_warnings)} score warnings."
        )
        return report

    def recommend_assignment(
        self,
        workbook_path: str,
        incoming_feed: Dict[str, Any],
        sheet_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convenience shortcut: scan a workbook and get an assignment
        recommendation for a specific incoming feed.
        """
        return self.scan_workbook(workbook_path, sheet_name, incoming_feed)

    # ------------------------------------------------------------------
    # Report builders
    # ------------------------------------------------------------------

    def _build_report(
        self,
        fpath: Path,
        parser: Any,
        analysis: Dict[str, Any],
        validation_warnings: List[Dict],
        recommendation: Optional[Dict],
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        team_stats = analysis.get("team_stats", {})

        return {
            "status": "complete",
            "filepath": str(fpath),
            "filename": fpath.name,
            "scanned_at": now,
            "row_count": parser.row_count,
            "fields_detected": parser.canonical_headers,
            "team_stats": team_stats,
            "analyst_summaries": analysis.get("analyst_summaries", {}),
            "unassigned_feeds": analysis.get("unassigned_feeds", []),
            "validation_warnings": validation_warnings,
            "assignment_recommendation": recommendation,
            "rell_assessment": self._rell_assessment(analysis, recommendation, validation_warnings),
        }

    def _rell_assessment(
        self,
        analysis: Dict,
        recommendation: Optional[Dict],
        warnings: List,
    ) -> str:
        stats = analysis.get("team_stats", {})
        summaries = analysis.get("analyst_summaries", {})
        avg = stats.get("average_points_per_analyst", 0)
        total = stats.get("total_team_points", 0)
        analysts = stats.get("analyst_count", 0)
        feeds = stats.get("feed_count", 0)
        unassigned = stats.get("unassigned_count", 0)

        overloaded = [a for a, s in summaries.items() if s.get("load_status") == "OVERLOADED"]
        underloaded = [a for a, s in summaries.items() if s.get("load_status") == "UNDERLOADED"]

        lines = [
            f"I reviewed {feeds} feeds across {analysts} analysts. "
            f"The team is carrying {total:.2f} total workload points — {avg:.2f} on average."
        ]

        if overloaded:
            lines.append(
                f"{', '.join(overloaded)} {'is' if len(overloaded) == 1 else 'are'} over the "
                f"team average by more than {self.analyzer.overload_threshold_pct:.0f}%. "
                f"That imbalance should be addressed before adding more work."
            )

        if underloaded:
            lines.append(
                f"{', '.join(underloaded)} {'has' if len(underloaded) == 1 else 'have'} capacity. "
                f"{'They are' if len(underloaded) > 1 else 'They are'} more than "
                f"{self.analyzer.underload_threshold_pct:.0f}% below the team average."
            )

        if not overloaded and not underloaded:
            lines.append("Load distribution looks balanced. No analyst is significantly over or under.")

        if unassigned > 0:
            lines.append(
                f"{unassigned} feed{'s are' if unassigned > 1 else ' is'} unassigned. "
                f"These represent orphaned work — no one is currently responsible for them."
            )

        if warnings:
            lines.append(
                f"{len(warnings)} score calculation discrepanc{'ies were' if len(warnings) > 1 else 'y was'} "
                f"found between the Excel values and my calculated values. Review the validation warnings."
            )

        if recommendation:
            lines.append(recommendation.get("rell_reasoning", ""))

        return " ".join(lines)

    def _write_reports(self, stem: str, report: Dict[str, Any]) -> Tuple[Path, Path]:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = self.reports_path / f"{stem}_workload_{ts}.json"
        md_path   = self.reports_path / f"{stem}_workload_{ts}.md"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self._format_markdown(report))

        return json_path, md_path

    def _format_markdown(self, report: Dict[str, Any]) -> str:
        filename = report.get("filename", "")
        scanned_at = report.get("scanned_at", "")[:19]
        stats = report.get("team_stats", {})
        summaries = report.get("analyst_summaries", {})
        unassigned = report.get("unassigned_feeds", [])
        warnings = report.get("validation_warnings", [])
        rec = report.get("assignment_recommendation")

        lines = [
            f"# Workload Audit — {filename}",
            f"",
            f"**Scanned:** {scanned_at}  ",
            f"**Feeds:** {stats.get('feed_count', 0)}  ",
            f"**Analysts:** {stats.get('analyst_count', 0)}  ",
            f"**Total Points:** {stats.get('total_team_points', 0):.2f}  ",
            f"**Avg per Analyst:** {stats.get('average_points_per_analyst', 0):.2f}  ",
            f"**Max Recommended:** {stats.get('max_recommended_per_analyst', 'N/A')}  ",
            f"",
            f"---",
            f"",
            f"## Rell's Assessment",
            f"",
            report.get("rell_assessment", ""),
            f"",
            f"---",
            f"",
            f"## Analyst Load Summary",
            f"",
        ]

        status_icons = {"OVERLOADED": "🔴", "UNDERLOADED": "🟡", "BALANCED": "🟢", "UNKNOWN": "⚪"}

        for analyst, summary in sorted(summaries.items(), key=lambda x: -x[1]["total_points"]):
            icon = status_icons.get(summary.get("load_status", "UNKNOWN"), "⚪")
            dev = summary.get("deviation_from_avg_pct", 0)
            dev_str = f"+{dev:.1f}%" if dev > 0 else f"{dev:.1f}%"
            cap = summary.get("capacity_remaining", 0)
            lines += [
                f"### {icon} {analyst}",
                f"",
                f"| Metric | Value |",
                f"|---|---|",
                f"| Feeds | {summary['feed_count']} |",
                f"| Total Points | {summary['total_points']:.2f} |",
                f"| Deviation from Avg | {dev_str} |",
                f"| Capacity Remaining | {cap:.2f} |",
                f"| Status | {summary.get('load_status', 'UNKNOWN')} |",
                f"",
                f"**Top feeds by workload:**",
                f"",
                f"| Feed | State | Frequency | Volume | Points |",
                f"|---|---|---|---|---|",
            ]
            for feed in summary.get("feeds", [])[:10]:
                lines.append(
                    f"| {feed.get('feed_name', feed.get('feed_id', ''))} "
                    f"| {feed.get('state', '')} "
                    f"| {feed.get('frequency', '')} "
                    f"| {feed.get('volume', '')} "
                    f"| {feed.get('workload_points', 0)} |"
                )
            lines += ["", "---", ""]

        if unassigned:
            lines += ["## Unassigned Feeds", ""]
            for u in unassigned:
                lines.append(f"- `{u.get('feed_name', 'UNKNOWN')}` — {u.get('workload_points', 0):.2f} pts")
            lines += ["", "---", ""]

        if warnings:
            lines += [f"## Score Validation Warnings ({len(warnings)})", ""]
            for w in warnings:
                lines.append(f"- Row {w.get('row')}: `{w.get('feed')}` — {w.get('warning')}")
            lines += ["", "---", ""]

        if rec:
            top_pick = rec.get("top_pick", "N/A")
            pts = rec.get("feed_points", 0)
            recs = rec.get("recommendations", [])
            lines += [
                f"## Assignment Recommendation — `{rec.get('feed_name', 'New Feed')}`",
                f"",
                f"**Feed Points:** {pts:.2f}  ",
                f"**Top Pick:** {top_pick}  ",
                f"",
                rec.get("rell_reasoning", ""),
                f"",
                f"**Ranked candidates:**",
                f"",
                f"| Rank | Analyst | Current | Projected | Status | State Familiar |",
                f"|---|---|---|---|---|---|",
            ]
            for i, c in enumerate(recs, 1):
                familiar = "Yes" if c.get("state_familiar") else "—"
                lines.append(
                    f"| {i} | {c['analyst']} | {c['current_points']:.2f} "
                    f"| {c['projected_points']:.2f} | {c['load_status']} | {familiar} |"
                )
            lines += ["", "---", ""]

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(val: Any) -> float:
    """Safe cast to float. Returns 0.0 on failure."""
    if val is None or val == "":
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
