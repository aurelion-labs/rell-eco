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
            "Scoring formula weights. volume_weight=0 disables raw-record-volume scoring "
            "until accurate volume data is available. base_feed_points gives every assigned "
            "feed a baseline score. sheet_type_multipliers boost or discount feeds by source "
            "sheet (LeadList courts are more complex; State_SME is territory reference only). "
            "time_weight: points per hour of QA time, scaled by frequency. "
            "difficulty_weight: multiplier on raw difficulty score (1-5 scale)."
        ),
        "volume_unit": 1000000,
        "volume_weight": 0.0,
        "base_feed_points": 1.0,
        "sheet_type_multipliers": {
            "LeadList-Master": 2.0,
            "State_SME": 0.5,
        },
        # Role weights applied on top of sheet multiplier during role expansion.
        # ll = Lead List Responsibility (complex), dqs = DQS Responsible,
        # backup = Back-up DA Responsible.
        "ll_role_weight":     3.0,
        "dqs_role_weight":    1.0,
        "backup_role_weight": 0.5,
        # Canonical full names of DQS specialists. Analysts here (or with zero
        # primary/LL credits) are shown in the DQS Workload table, not the DA table.
        "dqs_team": [
            "David Parker",
            "Kayleigh Kinslow",
            "Erica Hsu",
            "Haley Menard",
            "Tara Jerideau",
            "Robin Mark",
        ],
        # Explicit name aliases — maps names as they appear in Excel to canonical display names.
        # Use for married/maiden name changes, abbreviations that can't be auto-resolved, etc.
        # Key: name in spreadsheet, Value: canonical full name.
        "name_aliases": {
            "Robin B": "Robin Mark",
        },
        # Analysts on external teams (Team Kennedy etc.) — excluded from all output.
        "other_teams": [
            "Beth H",
            "Kayla Wallace",
            "Trey Lennox",
        ],
        # Analysts with incomplete workload data. Shown with [partial] tag, excluded from deviations.
        "partial_data": [
            "Matthew Jay",
            "Wayne Allen",
        ],
        # Analysts who have left the company. Shown with [departed] tag so reviewers update the sheet.
        "departed": [
            "Michelle Albea",
        ],
        # Cross-team collaborators. Shown with [cross-collab] tag, excluded from team averages.
        "cross_collab": [
            "David Parker",
        ],
        # Non-DA/DQS roles. Shown with [biz-ops] tag, excluded from team averages.
        "other_roles": [
            "Adam Rollings",
        ],
        # Auie's Philippines DA team. All other DAs default to the US team.
        "philippines_team": [
            "Rosan Nila Batalla",
            "Maria Camille Gonzales",
            "Catrina Baguio",
            "Japeth Jalando-on",
            "Dennis Hadlocon",
            "Patrixia Kate Nunag",
            "Joshua Alec Trofeo",
            "Jenny Rose Padua",
            "Julie Rose Arceta",
            "Paul Justin Mallari",
            "Flordelia Aguinaldo",
            "Jeraldine Calagui",
        ],
        "time_weight": 0.5,
        "difficulty_weight": 0.5,
        "deviation_alert_pct": 20,
        "use_excel_score": False,
        "recalculate_for_validation": False,
        "frequency_defaults": {
            "unknown": 1.0
        },
        "overload_threshold_pct": 25,
        "underload_threshold_pct": 25,
        "max_recommended_points": 40.0,
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
        volume_weight = float(self.config.get("volume_weight", 0.0))
        time_weight = float(self.config.get("time_weight", 0.5))
        difficulty_weight = float(self.config.get("difficulty_weight", 0.5))
        base_feed_points = float(self.config.get("base_feed_points", 1.0))

        # Sheet-type multiplier — boosts complex sources (LeadList courts) or
        # discounts reference-only sheets (State_SME territory assignments)
        sheet = record.get("_sheet", "")
        sheet_multipliers: Dict[str, float] = self.config.get("sheet_type_multipliers", {})
        sheet_mult = float(sheet_multipliers.get(sheet, 1.0))

        # Monthly equivalents
        monthly_volume = volume * freq_mult
        volume_points = (monthly_volume / volume_unit) * volume_weight if volume_unit else 0.0
        time_points = (time_minutes / 60.0) * time_weight * freq_mult
        difficulty_points = difficulty * difficulty_weight

        # Base score per feed (always awarded) + optional volume/time/difficulty
        subtotal = base_feed_points + volume_points + time_points + difficulty_points
        calculated = round(subtotal * sheet_mult, 4)

        detail = {
            "frequency_multiplier": freq_mult,
            "base_feed_points": base_feed_points,
            "sheet_multiplier": sheet_mult,
            "monthly_volume": round(monthly_volume, 0),
            "volume_points": round(volume_points, 4),
            "time_points": round(time_points, 4),
            "difficulty_points": round(difficulty_points, 4),
            "calculated_total": calculated,
        }

        excel_score = _to_float(record.get("workload_points", None))
        use_excel = self.config.get("use_excel_score", False)
        validate = self.config.get("recalculate_for_validation", False)
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

    # ------------------------------------------------------------------
    # Name normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _build_name_map(names: List[str]) -> Dict[str, str]:
        """
        Build a mapping of abbreviated/variant names to canonical full names.

        Strategy: group names by (first_word, last_initial). Within each
        group, use the longest name as canonical. All shorter variants map
        to it.

        Examples:
            "Hoang N"      -> "Hoang Nguyen"
            "Colin M"      -> "Colin Maxwell"
            "Chase K"      -> "Chase Key"

        Single-word names or names with no matching longer version are kept
        as-is.
        """
        from collections import defaultdict

        # Build index: (first_lower, last_initial_lower) -> list of names
        groups: Dict[tuple, List[str]] = defaultdict(list)
        for name in names:
            parts = name.strip().split()
            if not parts:
                continue
            first = parts[0].lower()
            last_initial = parts[-1][0].lower() if len(parts) > 1 else ""
            groups[(first, last_initial)].append(name)

        name_map: Dict[str, str] = {}
        for group_names in groups.values():
            if len(group_names) == 1:
                # No ambiguity — identity mapping
                name_map[group_names[0]] = group_names[0]
            else:
                # Pick the longest name (most complete) as canonical
                canonical = max(group_names, key=lambda n: len(n))
                for variant in group_names:
                    name_map[variant] = canonical

        return name_map

    def analyze(self, scored_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build per-analyst summaries from scored records.

        Args:
            scored_records: Records with 'assignee', 'workload_points', and
                            optionally 'feed_name', 'feed_id', 'state', 'frequency'.

        Returns:
            Full analysis dict including per-analyst breakdown and team stats.
            Analysts are tagged by team (DA or DQS) based on:
              1. Explicit membership in the 'dqs_team' config list, OR
              2. Auto-detection: zero primary/LL feed credits (only dqs/backup/sme roles)
        """
        # Apply explicit name aliases BEFORE auto-normalization.
        # Covers cases like married name changes where initials differ and
        # auto-grouping (by first+last_initial) would miss the merge.
        raw_aliases = self.config.get("name_aliases", {})
        if raw_aliases:
            alias_map = {k.strip().lower(): v.strip() for k, v in raw_aliases.items()}
            for r in scored_records:
                assignee = str(r.get("assignee", "")).strip()
                if assignee.lower() in alias_map:
                    r["assignee"] = alias_map[assignee.lower()]

        # Build name normalization map across all assignee values in this dataset
        all_names = [
            str(r.get("assignee", "")).strip()
            for r in scored_records
            if str(r.get("assignee", "")).strip()
        ]
        name_map = self._build_name_map(list(set(all_names)))

        # Build DQS team set — normalize configured names through the same name_map
        raw_dqs_team: List[str] = [
            v for v in self.config.get("dqs_team", [])
            if isinstance(v, str) and not v.startswith("_")
        ]
        dqs_team_set: set = set()
        for name in raw_dqs_team:
            canonical = name_map.get(name, name)
            dqs_team_set.add(canonical.lower())

        # Build exclusion set for external-team analysts (Team Kennedy etc.)
        raw_other_teams: List[str] = [
            v for v in self.config.get("other_teams", [])
            if isinstance(v, str) and not v.startswith("_")
        ]
        other_teams_set: set = set()
        for name in raw_other_teams:
            canonical = name_map.get(name, name)
            other_teams_set.add(canonical.lower())

        # Build Philippines team set (Auie's team)
        raw_ph_team: List[str] = [
            v for v in self.config.get("philippines_team", [])
            if isinstance(v, str) and not v.startswith("_")
        ]
        philippines_team_set: set = set()
        for name in raw_ph_team:
            canonical = name_map.get(name, name)
            philippines_team_set.add(canonical.lower())

        # Group feeds by analyst (using canonical name)
        by_analyst: Dict[str, List[Dict[str, Any]]] = {}
        unassigned = []

        for r in scored_records:
            assignee = str(r.get("assignee", "")).strip()
            if not assignee:
                unassigned.append(r)
                continue
            canonical = name_map.get(assignee, assignee)
            if canonical.lower() in other_teams_set:
                continue  # external team analyst — excluded from all output
            by_analyst.setdefault(canonical, []).append(r)

        # Build per-analyst summaries + tag team
        analyst_summaries: Dict[str, Dict[str, Any]] = {}
        for analyst, feeds in by_analyst.items():
            summary = self._summarize_analyst(analyst, feeds)

            # Auto-detect DQS: no primary/LL feeds at all → likely DQS/SME-only
            has_primary = any(
                r.get("_role", "primary") not in ("backup", "dqs")
                for r in feeds
            )
            in_dqs_list = analyst.lower() in dqs_team_set
            is_dqs = in_dqs_list or (not has_primary)
            summary["team"] = "DQS" if is_dqs else "DA"
            summary["team_source"] = "config" if in_dqs_list else ("auto" if is_dqs else "config")

            analyst_summaries[analyst] = summary

        # Segment by team
        da_summaries  = {k: v for k, v in analyst_summaries.items() if v["team"] == "DA"}
        dqs_summaries = {k: v for k, v in analyst_summaries.items() if v["team"] == "DQS"}

        # Split DA into US (Kiara + Josefina) and Philippines (Auie)
        us_da_summaries = {k: v for k, v in da_summaries.items() if k.lower() not in philippines_team_set}
        ph_da_summaries = {k: v for k, v in da_summaries.items() if k.lower() in philippines_team_set}

        # Assign display tags — these analysts still appear in their table but are
        # excluded from deviation calculations and overload/underload flagging.
        def _make_tagged_set(key: str) -> set:
            raw = [v for v in self.config.get(key, []) if isinstance(v, str) and not v.startswith("_")]
            return {name_map.get(n, n).lower() for n in raw}

        _partial_set      = _make_tagged_set("partial_data")
        _departed_set     = _make_tagged_set("departed")
        _cross_collab_set = _make_tagged_set("cross_collab")
        _other_roles_set  = _make_tagged_set("other_roles")

        for analyst, summary in analyst_summaries.items():
            al = analyst.lower()
            if al in _partial_set:
                summary["display_tag"] = "partial"
            elif al in _departed_set:
                summary["display_tag"] = "departed"
            elif al in _cross_collab_set:
                summary["display_tag"] = "x-collab"
            elif al in _other_roles_set:
                summary["display_tag"] = "biz-ops"
            elif summary.get("team_source") == "auto":
                summary["display_tag"] = "auto"
            else:
                summary["display_tag"] = ""

        # Per-sub-group deviation + overload flags.
        # Only active analysts (no display_tag) contribute to the group average.
        for group_summaries in (us_da_summaries, ph_da_summaries, dqs_summaries):
            active_pts = [
                s["total_points"] for s in group_summaries.values()
                if not s.get("display_tag")
            ]
            team_avg = sum(active_pts) / len(active_pts) if active_pts else 0.0
            for summary in group_summaries.values():
                pts = summary["total_points"]
                summary["capacity_remaining"] = max(0.0, round(self.max_recommended - pts, 4))
                if summary.get("display_tag"):
                    # Tagged: informational only — not compared against team average
                    summary["deviation_from_avg_pct"] = None
                    summary["load_status"] = "NOTE"
                elif team_avg > 0:
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

        all_points = [a["total_points"] for a in analyst_summaries.values()]
        team_total = sum(all_points)

        def _tstats(summaries: Dict[str, Dict]) -> Dict:
            # Stats reflect active analysts only (tagged analysts excluded from averages)
            active = {k: v for k, v in summaries.items() if not v.get("display_tag")}
            pts = [s["total_points"] for s in active.values()]
            total = sum(pts)
            avg   = total / len(pts) if pts else 0.0
            return {
                "analyst_count": len(active),
                "feed_count":    sum(s["feed_count"] for s in active.values()),
                "total_team_points": round(total, 4),
                "average_points_per_analyst": round(avg, 4),
            }

        return {
            "analyst_summaries": analyst_summaries,
            "da_summaries":      da_summaries,
            "dqs_summaries":     dqs_summaries,
            "us_da_summaries":   us_da_summaries,
            "ph_da_summaries":   ph_da_summaries,
            "team_stats": {
                "analyst_count":    len(analyst_summaries),
                "feed_count":       len(scored_records) - len(unassigned),
                "unassigned_count": len(unassigned),
                "total_team_points": round(team_total, 4),
                "average_points_per_analyst": round(
                    team_total / max(len(analyst_summaries), 1), 4
                ),
                "max_recommended_per_analyst": self.max_recommended,
            },
            "da_team_stats":    _tstats(da_summaries),
            "us_da_team_stats": _tstats(us_da_summaries),
            "ph_da_team_stats": _tstats(ph_da_summaries),
            "dqs_team_stats":   _tstats(dqs_summaries),
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
        primary_pts = sum(
            _to_float(r.get("workload_points", 0))
            for r in feeds
            if r.get("_role") != "backup"
        )
        backup_pts = sum(
            _to_float(r.get("workload_points", 0))
            for r in feeds
            if r.get("_role") == "backup"
        )
        total_pts = primary_pts + backup_pts
        sorted_feeds = sorted(feeds, key=lambda r: _to_float(r.get("workload_points", 0)), reverse=True)

        return {
            "analyst": analyst,
            "feed_count": len(feeds),
            "total_points": round(total_pts, 4),
            "primary_points": round(primary_pts, 4),
            "backup_points":  round(backup_pts, 4),
            "feeds": [
                {
                    "feed_name": r.get("feed_name", r.get("feed_id", "UNKNOWN")),
                    "feed_id": r.get("feed_id", r.get("feed_name", "")),
                    "state": r.get("state", ""),
                    "frequency": r.get("frequency", ""),
                    "volume": r.get("volume", ""),
                    "workload_points": r.get("workload_points", 0),
                    "role": r.get("_role", "primary"),
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

    Usage (file-based config):
        engine = WorkloadAuditEngine(
            scoring_config_path="data/audit/workload/scoring_config.json",
            reports_path="data/audit/memory/reports/",
        )
        report = engine.scan_workbook("workload_tracker.xlsx")

    Usage (dict config — for programmatic / standalone use):
        engine = WorkloadAuditEngine(
            config=merged_config_dict,
            reports_path="data/reports/",
        )
        report = engine.scan_workbook("workload_tracker.xlsx")
    """

    def __init__(
        self,
        scoring_config_path: Optional[str] = None,
        reports_path: str = "data/audit/memory/reports",
        config: Optional[Dict[str, Any]] = None,
    ):
        self.reports_path = Path(reports_path)
        self.reports_path.mkdir(parents=True, exist_ok=True)

        if config is not None:
            # Config dict passed directly — no file I/O needed (used by standalone tool)
            self.config = config
        elif scoring_config_path is not None:
            # Load scoring config from file path (create default if absent)
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
        else:
            # No config provided — fall back to hardcoded defaults
            self.config = WorkloadScorer.DEFAULT_CONFIG

        self.scorer = WorkloadScorer(self.config)
        self.analyzer = WorkloadAnalyzer(self.config)

    # ------------------------------------------------------------------
    # Role expansion
    # ------------------------------------------------------------------

    def _expand_role_records(
        self, scored: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Expand multi-role columns (ll_assignee, dqs_assignee, backup_assignee)
        from each scored record into additional records for those people.

        The LeadList-Master sheet has separate columns for:
          - Lead List Responsibility  →  ll_assignee   (complex, high weight)
          - DQS Responsible           →  dqs_assignee  (medium weight)
          - Back-up DA Responsible    →  backup_assignee (low weight)

        Each role generates its own scored record so the person gets credit
        in the workload analysis. Role weights are multiplied on top of the
        base_feed_points to reflect the appropriate complexity premium.

        Config keys used:
          ll_role_weight      (default 3.0) — Lead-list owners carry complex work
          dqs_role_weight     (default 1.0) — DQS validation responsibility
          backup_role_weight  (default 0.5) — backup / coverage labour
        """
        ll_weight     = float(self.config.get("ll_role_weight",     3.0))
        dqs_weight    = float(self.config.get("dqs_role_weight",    1.0))
        backup_weight = float(self.config.get("backup_role_weight", 0.5))
        base          = float(self.config.get("base_feed_points",   1.0))

        sheet_multipliers: Dict[str, float] = self.config.get("sheet_type_multipliers", {})

        role_map = [
            ("ll_assignee",     "ll",     ll_weight),
            ("dqs_assignee",    "dqs",    dqs_weight),
            ("backup_assignee", "backup", backup_weight),
        ]

        extra: List[Dict[str, Any]] = []
        for record in scored:
            sheet = record.get("_sheet", "")
            sheet_mult = float(sheet_multipliers.get(sheet, 1.0))

            for field, role_tag, weight in role_map:
                name = str(record.get(field, "")).strip()
                if name and name.lower() not in ("", "nan", "none", "n/a", "na", "0"):
                    pts = round(base * sheet_mult * weight, 4)
                    new_rec = dict(record)
                    new_rec["assignee"] = name
                    new_rec["workload_points"] = pts
                    new_rec["_score_source"] = f"role_{role_tag}"
                    new_rec["_role"] = role_tag
                    extra.append(new_rec)

        return scored + extra

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

        # Multi-sheet vs single-sheet
        if sheet_name:
            parser.parse()
        else:
            parser.parse_all_sheets(skip_non_data=True)

        if parser.parse_errors and not parser.records:
            return {
                "status": "parse_failed",
                "filepath": str(fpath),
                "errors": parser.parse_errors,
            }

        # Load weights from the workbook's own parameters tab (if present)
        params_from_wb = parser.read_params_sheet()
        if params_from_wb:
            print(f"[WorkloadAuditEngine] Loaded {len(params_from_wb)} parameter(s) from workbook params tab.")
            # Merge into scorer config — workbook values take precedence over defaults
            self.scorer.config.update(params_from_wb)
            self.analyzer.overload_threshold_pct  = float(
                params_from_wb.get("overload_threshold_pct",  self.analyzer.overload_threshold_pct)
            )
            self.analyzer.underload_threshold_pct = float(
                params_from_wb.get("underload_threshold_pct", self.analyzer.underload_threshold_pct)
            )

        # Score every row
        scored = []
        for record in parser.records:
            score_result = self.scorer.score(record)
            record["workload_points"] = score_result["workload_points"]
            record["_score_source"] = score_result["source"]
            record["_validation_warning"] = score_result.get("validation_warning")
            record["_calc_detail"] = score_result["calculation_detail"]
            scored.append(record)

        # Expand multi-role columns from LeadList-Master into separate scored records.
        # Lead List Responsibility, DQS Responsible, and Back-up DA each map to a
        # distinct person with a distinct workload contribution. Role weights are
        # multiplied on top of the sheet_type_multiplier already in base_feed_points.
        scored = self._expand_role_records(scored)

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
            "da_summaries":      analysis.get("da_summaries",     {}),
            "dqs_summaries":     analysis.get("dqs_summaries",    {}),
            "us_da_summaries":   analysis.get("us_da_summaries",  {}),
            "ph_da_summaries":   analysis.get("ph_da_summaries",  {}),
            "da_team_stats":     analysis.get("da_team_stats",    {}),
            "us_da_team_stats":  analysis.get("us_da_team_stats", {}),
            "ph_da_team_stats":  analysis.get("ph_da_team_stats", {}),
            "dqs_team_stats":    analysis.get("dqs_team_stats",   {}),
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
        overall_stats = analysis.get("team_stats", {})
        total         = overall_stats.get("total_team_points", 0)
        feeds         = overall_stats.get("feed_count", 0)
        unassigned    = analysis.get("unassigned_feeds", [])

        lines = [
            f"I reviewed {feeds} feeds totaling {total:.2f} workload points across three teams. "
            f"Here's how each team looks:"
        ]

        # Per-team narrative block
        team_configs = [
            ("US DATA ANALYSTS (Kiara & Josefina)", "us_da_summaries", "us_da_team_stats"),
            ("PHILIPPINES DA (Auie)",               "ph_da_summaries", "ph_da_team_stats"),
            ("DATA QUALITY SPECIALISTS",            "dqs_summaries",   "dqs_team_stats"),
        ]

        for team_label, sum_key, stats_key in team_configs:
            summaries  = analysis.get(sum_key, {})
            stats      = analysis.get(stats_key, {})
            count      = stats.get("analyst_count", 0)
            if not summaries or count == 0:
                continue

            avg        = stats.get("average_points_per_analyst", 0)
            team_feeds = stats.get("feed_count", 0)

            # Active-only for over/under detection (tagged analysts excluded)
            active      = {a: s for a, s in summaries.items() if not s.get("display_tag")}
            overloaded  = [a for a, s in active.items() if s.get("load_status") == "OVERLOADED"]
            underloaded = [a for a, s in active.items() if s.get("load_status") == "UNDERLOADED"]

            section = (
                f"\n**{team_label}** — {count} active analyst{'s' if count != 1 else ''}, "
                f"{team_feeds} feeds, avg {avg:.2f} pts."
            )

            if overloaded:
                section += (
                    f" {', '.join(overloaded)} {'is' if len(overloaded) == 1 else 'are'} "
                    f"significantly over the team average — reassignment should be prioritized."
                )
            if underloaded:
                section += (
                    f" {', '.join(underloaded)} {'has' if len(underloaded) == 1 else 'have'} "
                    f"capacity and can absorb additional feeds."
                )
            if not overloaded and not underloaded:
                section += " Distribution looks balanced within this team."

            lines.append(section)

        if unassigned:
            n = len(unassigned)
            lines.append(
                f"\n{n} feed{'s are' if n > 1 else ' is'} unassigned — "
                f"orphaned work with no current owner."
            )

        if warnings:
            lines.append(
                f"{len(warnings)} score validation "
                f"discrepanc{'ies' if len(warnings) > 1 else 'y'} found. "
                f"Review the warnings section before acting on these numbers."
            )

        if recommendation:
            lines.append("\n" + recommendation.get("rell_reasoning", ""))

        return "\n".join(lines)

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

        status_icons = {"OVERLOADED": "🔴", "UNDERLOADED": "🟡", "BALANCED": "🟢", "UNKNOWN": "⚪", "NOTE": "📋"}

        for analyst, summary in sorted(summaries.items(), key=lambda x: -x[1]["total_points"]):
            icon = status_icons.get(summary.get("load_status", "UNKNOWN"), "⚪")
            dev = summary.get("deviation_from_avg_pct")
            dev_str = (f"+{dev:.1f}%" if dev > 0 else f"{dev:.1f}%") if dev is not None else "n/a"
            cap = summary.get("capacity_remaining", 0)
            lines += [
                f"### {icon} {analyst}",
                f"",
                f"| Metric | Value |",
                f"|---|---|",
                f"| Feeds | {summary['feed_count']} |",
                f"| Primary Points | {summary.get('primary_points', summary['total_points']):.2f} |",
                f"| Backup Points | {summary.get('backup_points', 0):.2f} |",
                f"| Total Points | {summary['total_points']:.2f} |",
                f"| Deviation from Avg | {dev_str} |",
                f"| Capacity Remaining | {cap:.2f} |",
                f"| Status | {summary.get('load_status', 'UNKNOWN')} |",
                f"",
                f"**Top feeds by workload:**",
                f"",
                f"| Feed | State | Frequency | Volume | Role | Points |",
                f"|---|---|---|---|---|---|",
            ]
            for feed in summary.get("feeds", [])[:10]:
                lines.append(
                    f"| {feed.get('feed_name', feed.get('feed_id', ''))} "
                    f"| {feed.get('state', '')} "
                    f"| {feed.get('frequency', '')} "
                    f"| {feed.get('volume', '')} "
                    f"| {feed.get('role', 'primary')} "
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
