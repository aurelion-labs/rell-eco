# rell-engine

> The open-core audit engine that powers every RELL domain instance.

**License:** MIT  
**Status:** Extracting from AURELION Nexus Premium | v0.1.0 in progress

## What This Is

`rell-engine` is the portable, domain-agnostic core of RELL. It handles:

- Flat file ingestion and anomaly detection
- Workload tracker scoring and load analysis
- SQL schema ingestion, versioning, and drift detection
- Live database auditing (read-only, credential-validated)
- Audit cycle management with persistent finding memory
- Structured report generation (Markdown + JSON)

The engine has no opinion about what compliance standard you care about. You bring the profile. The engine runs the checks and reports the findings.

## Quick Start

```bash
git clone https://github.com/z3rosl33p/rell-engine.git
cd rell-engine
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt

# Scan a flat file
python run_audit.py --scan-file path/to/data.txt

# Full operator guide
cat OPERATOR_GUIDE.md
```

## Loading a Compliance Profile

```bash
rell init --profile gdpr-eu        # from rell-profiles registry
rell init --profile ccpa-california
python run_audit.py                # runs with active profile loaded
```

## Relationship to AURELION

`rell-engine` is extracted from `aurelion-nexus-premium`. The original code lives in that repo as part of the AURELION Ecosystem. This repo is the clean, standalone version intended for distribution and production use.

## License

MIT — use it, extend it, build on it. The engine is the open core.  
Domain profiles in `rell-profiles` are licensed separately (BSL).
