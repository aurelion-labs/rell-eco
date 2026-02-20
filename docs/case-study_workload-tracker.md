# Case Study: Workload Distribution Tracker
### From Idea to Live Web App in One Session

---

## The Problem

A data operations team of 40+ analysts spread across three groups — US-based, Philippines-based, and a specialist quality unit — assigned incoming data feeds manually. The process lived in a spreadsheet. Reassignments happened based on gut feel. Analysts were burning out invisibly while others had spare capacity, and the manager responsible had no fast, defensible way to make the case for rebalancing.

The ask: *"Can you build something I can use to assign feeds more fairly?"*

---

## The Constraints

This wasn't a greenfield product opportunity. The constraints were real and specific:

- **Non-technical end user.** The manager using this tool is not an engineer. She can't run terminal commands, install dependencies, or read error logs.
- **IP protection.** The tool had to be extracted from a larger internal engine without exposing the rest of the stack.
- **No IT involvement.** No deployment tickets, no approval chains. The tool needed to be live and usable the same day.
- **Works with existing data.** The team already exports a weekly Excel workload sheet. The tool had to accept that file as-is.

---

## What I Built

A browser-based workload analysis tool — **upload a file, press a button, get a structured report** — deployed as a live web application accessible by URL and password.

**Core capabilities:**
- Ingests the team's existing Excel export (no reformatting required)
- Scores each analyst against a configurable point model: role weight (primary vs. backup), feed complexity by sheet type, volume (when available)
- Classifies each analyst as overloaded, balanced, or underloaded relative to their team average — not globally, but within each team separately (US DA / Philippines DA / DQS), so the comparison is always fair
- Surfaces cross-team collaborators, partial-data employees, and departed analysts as tagged rows rather than polluting the main scores
- Generates a written narrative ("Rell's Assessment") naming specific analysts and recommending reassignment priority
- Exports a formatted PDF suitable for a management meeting

**What the user sees:** A URL. A password. A drag-and-drop upload zone. One button. Results in seconds.

---

## Architecture Decisions

### Modular extraction
The workload tool is one component extracted from a larger internal audit engine. The distribution package (`rell-workload/`) contains only the code needed to run the workload feature. The compliance engine, schema registry, LLM integration, and audit reporting pipeline are not included — they don't exist from the recipient's perspective.

### Split configuration
Two config files with intentionally different audiences:
- `team-roster.json` — human-readable, with plain-English instructions embedded as comments. The manager edits this when someone joins, leaves, or changes roles.
- `scoring.json` — numerical weights with technical notes. Admin-only. She never opens this file.

### Deployment model
Deployed to [fly.io](https://fly.io) as a containerized FastAPI application. Key decisions:
- **Auto-sleep when idle** — the server shuts down when nobody is using it and restarts on the next request (~2 second cold start). Cost: $0 between sessions.
- **Password gate** — a session cookie signed with `itsdangerous.TimestampSigner` expires after 8 hours. One login per workday. No accounts, no registration, no email.
- **Secrets management** — `APP_PASSWORD` and `SECRET_KEY` are stored as encrypted fly.io secrets, never in the repository.

### Update workflow
When the team roster changes or the engine is improved: edit the file, run `flyctl deploy`, done. The manager refreshes her browser. No coordination required.

---

## The Build

**Total time: one working session.**

The sequence:

1. **Scoped the scoring model** — identified what "workload" actually means for this team: primary/backup role split, feed count, sheet type complexity. Decided to defer volume scoring until reliable data is available (flag, don't block).

2. **Built the engine** (`WorkloadAuditEngine`) — Excel parser ingests the sheet, normalizes analyst names (including a name-alias system for cases like a name change after marriage), maps feeds to analysts by role, computes per-analyst point totals, compares against team averages, classifies load status.

3. **Built the API** (`FastAPI`) — file upload endpoint, workload scan endpoint, PDF export endpoint. Designed to re-read config on every scan so roster changes take effect without restarting the server.

4. **Built the UI** — single-page interface: drag-and-drop upload zone, one "Analyze Workload" button, results rendered as three team tables with color-coded load badges and a narrative block. Export to PDF button.

5. **Extracted the standalone module** — stripped out everything not needed for the workload feature, split the config into user-editable and admin-only files, wrote a plain-English README.

6. **Added auth and deployed** — login page, session middleware, Dockerfile, fly.io config. First `flyctl deploy`. Bug caught from logs (CSS curly braces conflicting with Python's string formatter), fixed, redeployed. Live.

---

## Skills Demonstrated

| Area | Detail |
|---|---|
| Backend | Python, FastAPI, async request handling, file I/O |
| Data engineering | Excel parsing with openpyxl, multi-role scoring model, name normalization |
| Frontend | Vanilla HTML/CSS/JS, no framework dependencies |
| DevOps | Docker, fly.io, environment secrets, auto-scaling configuration |
| Security | Session cookie auth, HMAC signing, secure-flag handling for HTTP vs HTTPS |
| Systems design | Modular IP extraction, multi-audience config split, zero-IT-overhead distribution model |
| UX thinking | Reduced a complex scoring system to: URL → password → drop file → button |

---

## Outcome

The tool is live. The manager has the URL and password. She can run a workload analysis at any time without asking anyone for help, without installing anything, and without waiting for an IT ticket. When her team changes, she edits one JSON file. When the engine improves, she refreshes her browser.

The larger internal audit engine — which handles compliance profiling, regulatory schema validation, and LLM-assisted findings — continues development independently. The workload tool is the first of what will be several purpose-specific extractions from that engine, each distributed at the right access level for its audience.

---

*Built February 2026. Stack: Python 3.11 · FastAPI · openpyxl · ReportLab · itsdangerous · Docker · fly.io*
