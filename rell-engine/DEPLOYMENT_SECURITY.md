# Rell Deployment Security Guide

This document covers every security boundary in a Rell deployment — from local development to regulated production environments.

---

## Table of Contents

1. [Threat Model](#threat-model)
2. [What Stays Local by Default](#what-stays-local-by-default)
3. [LLM Data Exposure](#llm-data-exposure)
4. [Credential Management](#credential-management)
5. [Audit Output Sensitivity](#audit-output-sensitivity)
6. [Data Residency & GDPR Compliance](#data-residency--gdpr-compliance)
7. [Read-Only Database Enforcement](#read-only-database-enforcement)
8. [Recommended Deployment Architectures](#recommended-deployment-architectures)
9. [Production Secrets Management](#production-secrets-management)
10. [Incident Response](#incident-response)
11. [Quick Security Checklist](#quick-security-checklist)

---

## Threat Model

Rell is an audit engine. It reads data — it never writes to source systems. The threats it must defend against are:

| Threat | Impact | Mechanism |
|--------|--------|-----------|
| Credential leak (DB passwords, API keys) | High | Secrets committed to git or logged |
| Audit findings sent to cloud LLM | Medium | Raw PII/business data leaves the network |
| Audit reports exfiltrated | Medium | Reports contain sensitive field values |
| Unauthorized audit run | Medium | Attacker reads schema/data via Rell |
| Supply chain compromise | Low | Malicious Python package reads .env |

---

## What Stays Local by Default

When you run Rell without any `--llm` flag, **zero external network calls are made**:

```
python run_audit.py scan-directory ./data/
```

- All parsing, rule evaluation, and finding generation is fully deterministic
- No data leaves your machine
- Output files are written to `data/output/` on your own disk
- This is the recommended mode for regulated environments (GDPR, HIPAA, SOX)

The only external calls Rell ever makes are optional and explicit:

| Flag | External call made |
|------|--------------------|
| `--llm openai` | Finding summaries sent to OpenAI API |
| `--llm claude` | Finding summaries sent to Anthropic API |
| `--llm ollama` | Localhost only — Ollama is local |
| *(no flag)* | None |

---

## LLM Data Exposure

This is the most important security decision you will make when deploying Rell.

### Option A: Deterministic (No LLM) — Maximum Privacy

```bash
python run_audit.py scan-directory ./data/
```

**What is sent externally:** Nothing. Zero.  
**Who should use this:** Any deployment handling regulated data (GDPR, HIPAA, CCPA, PCI-DSS, SOX).  
**Quality of assessments:** Rule-based. Every finding is deterministic and auditable.

---

### Option B: Ollama (Local LLM) — Enhanced + Private

```bash
python run_audit.py scan-directory ./data/ --llm ollama
python run_audit.py scan-directory ./data/ --llm ollama --model mistral
```

**What is sent externally:** Nothing. Ollama runs on your machine.  
**Who should use this:** Teams who want narrative-quality assessments without cloud exposure.  
**Setup requirements:** Ollama installed and running, model pulled (`ollama pull llama3`).  
**Resource impact:** Uses local CPU/GPU. Slower than cloud, no cost, fully private.

Supported models (recommended for compliance audit work):
- `llama3` — general purpose, good reasoning
- `mistral` — fast, strong analytical writing
- `phi3` — lightweight, laptop-friendly
- `codellama` — schema and SQL context

---

### Option C: Cloud LLM (OpenAI / Claude) — Enhanced Quality, External Exposure

```bash
python run_audit.py scan-directory ./data/ --llm openai
python run_audit.py scan-directory ./data/ --llm claude
```

**What is sent externally:** Finding summaries and prompt context (which may include field names, sample values, schema structures, and anomaly descriptions).

**What is NOT sent:** Raw source files. Rell sends constructed prompts — excerpts, summaries, and descriptions — not full table dumps. However these prompts can and will contain business-context data.

**Who should use this:**
- Pre-production, dev, or staging environments only
- Production systems where data classification permits cloud processing
- Teams with DPA (Data Processing Agreement) with OpenAI / Anthropic

**Who should NOT use this:**
- Any system containing unredacted GDPR personal data (Articles 4, 9)
- HIPAA covered entities or business associates
- Systems with data residency requirements (EU, China, etc.) with US-based cloud restrictions

**If you use cloud LLM in production:**
1. Review your legal basis under GDPR Article 6 / Article 28
2. Ensure a signed DPA with OpenAI ([privacy.openai.com](https://privacy.openai.com)) or Anthropic ([anthropic.com/privacy](https://anthropic.com/privacy))
3. Enable `Zero Data Retention` policy if your OpenAI tier supports it
4. Log which audit runs used `--llm openai|claude` for your data processing register

---

## Credential Management

Rell never stores credentials in source code. It supports three methods:

### Method 1: `.env` file (Development)

Copy `.env.example` to `.env` in the `rell-engine/` directory:

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
RELL_LLM_PROVIDER=ollama
RELL_LLM_MODEL=mistral
OLLAMA_BASE_URL=http://localhost:11434

DB_CONN_PRODUCTION=mssql+pyodbc://readonly_user:password@server/db?driver=ODBC+Driver+17+for+SQL+Server
```

**Security requirements for `.env`:**
- `.env` is in `.gitignore` — never commit it
- Restrict file permissions: `chmod 600 .env` (Linux/Mac) or deny read to other Windows users
- Use a unique read-only DB user for Rell — do not use `sa` or admin accounts

---

### Method 2: Environment Variables (CI/CD, Docker, Production)

Set variables at the OS or container level — Rell reads them automatically:

```powershell
# Windows (current session)
$env:OPENAI_API_KEY = "sk-..."
$env:DB_CONN_PRODUCTION = "mssql+pyodbc://..."

# Windows (persistent — use System > Environment Variables)
[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-...", "Machine")
```

```bash
# Linux/Mac
export OPENAI_API_KEY="sk-..."
export DB_CONN_PRODUCTION="mssql+pyodbc://..."
```

---

### Method 3: Windows Credential Manager (Windows Production Deployments)

For sensitive deployments on Windows, store credentials in the Windows Credential Manager using `keyring`:

```python
import keyring
keyring.set_password("rell", "OPENAI_API_KEY", "sk-...")
key = keyring.get_password("rell", "OPENAI_API_KEY")
```

This stores credentials encrypted by Windows DPAPI — not accessible to other users and not stored on disk as plaintext.

**To integrate with Rell:** Override `os.getenv("OPENAI_API_KEY")` by pre-loading into environment at process start time from keyring.

---

## Audit Output Sensitivity

Rell writes findings to `data/output/`. These files contain:

- Field names and values from audited data
- Anomaly descriptions that may reference actual data values
- Schema structures and credential nicknames
- Timestamps, row counts, and statistical summaries

**Treat audit outputs as confidential business data.**

Recommendations:
- Do not store output files in shared directories or public S3 buckets
- Apply the same data classification to output files as to the source data
- Set a retention policy — audit findings are not indefinitely valuable and increase exposure
- If audit outputs are shared (e.g., sent to a compliance officer), redact sample values before sending

```bash
# Output location
data/output/findings_YYYYMMDD_HHMMSS.json
data/output/reports/audit_report_YYYYMMDD_HHMMSS.txt
```

---

## Data Residency & GDPR Compliance

### GDPR Compliance Summary

| Rell Mode | Data leaves EU? | GDPR Article 46 transfer? | Safe for EU personal data? |
|-----------|----------------|--------------------------|---------------------------|
| `--llm none` (default) | Never | Not applicable | Yes |
| `--llm ollama` | Never | Not applicable | Yes |
| `--llm openai` | Yes (to US) | Requires DPA + SCC | Only with legal basis |
| `--llm claude` | Yes (to US) | Requires DPA + SCC | Only with legal basis |

**Standard Contractual Clauses (SCCs)** are required for GDPR-compliant data transfer to US cloud LLM providers. Both OpenAI and Anthropic offer DPAs that incorporate SCCs.

### Recommended GDPR-Compliant Deployment

```bash
# Step 1: Default to deterministic (no data leaves machine)
python run_audit.py scan-directory ./data/ --profile gdpr-eu

# Step 2: If LLM-enhanced assessments are needed, use Ollama
python run_audit.py scan-directory ./data/ --profile gdpr-eu --llm ollama

# Step 3: Only use cloud LLM in pre-production or with explicit DPA
python run_audit.py scan-directory ./staging/  --llm openai
```

### Data Minimization (GDPR Article 5(1)(c))

Rell reads only what you point it at — it does not crawl directories recursively by default. Limit its scope to the specific data under audit rather than granting access to entire data lakes.

---

## Read-Only Database Enforcement

Rell only reads from databases. It does not write. But the database user you provide should enforce this at the server level — do not rely solely on Rell's behavior.

### SQL Server (Recommended Minimum Permissions)

```sql
-- Create a dedicated read-only user for Rell
CREATE LOGIN rell_audit WITH PASSWORD = 'StrongPassword!';
USE YourDatabase;
CREATE USER rell_audit FOR LOGIN rell_audit;

-- Grant read-only access to specific schemas
GRANT SELECT ON SCHEMA::dbo TO rell_audit;

-- Explicitly deny writes
DENY INSERT, UPDATE, DELETE, TRUNCATE ON SCHEMA::dbo TO rell_audit;
DENY ALTER, DROP, CREATE ON DATABASE::YourDatabase TO rell_audit;
```

### PostgreSQL

```sql
CREATE ROLE rell_audit WITH LOGIN PASSWORD 'StrongPassword';
GRANT CONNECT ON DATABASE yourdb TO rell_audit;
GRANT USAGE ON SCHEMA public TO rell_audit;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rell_audit;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO rell_audit;
```

### Connection String Best Practices

```dotenv
# Good — dedicated read-only user
DB_CONN_PROD=mssql+pyodbc://rell_audit:password@server/db?driver=ODBC+Driver+17+for+SQL+Server

# Bad — do not do this
DB_CONN_PROD=mssql+pyodbc://sa:password@server/db?...
DB_CONN_PROD=mssql+pyodbc://admin:password@server/db?...
```

---

## Recommended Deployment Architectures

### Architecture A: Air-Gapped / Maximum Security

```
[Analyst Workstation]
        │
        ├── rell-engine/ (local)
        ├── Ollama (local, no internet)
        └── data/ (local or network share)
                │
                └── outputs/ → [Encrypted archive → Compliance Officer]
```

Network requirements: None. Zero outbound connections.  
Suitable for: Defence, healthcare, government, regulated finance.

---

### Architecture B: Standard Enterprise

```
[Audit Server (on-prem)]
        │
        ├── rell-engine/
        ├── .env (managed by IT, rotated quarterly)
        ├── data/input/ → [Read-only mount from data warehouse]
        └── data/output/ → [Internal compliance share]
                │
                └── [Optional: --llm ollama on GPU server]
                         │
                         └── LAN only, never internet
```

---

### Architecture C: Cloud-Augmented (with DPA)

```
[Audit Server]
        │
        ├── rell-engine/
        ├── Secrets: AWS Secrets Manager / Azure Key Vault
        └── --llm openai (findings summarized via OpenAI API)
                │
                ├── Requires: Signed DPA with OpenAI
                ├── Requires: Data classification review
                └── Logging: All --llm runs logged to audit trail
```

---

## Production Secrets Management

For production deployments, do not use `.env` files. Use a secrets manager:

### AWS Secrets Manager

```python
import boto3, json

def get_secret(name: str) -> dict:
    client = boto3.client("secretsmanager", region_name="us-east-1")
    secret = client.get_secret_value(SecretId=name)
    return json.loads(secret["SecretString"])

creds = get_secret("rell/production")
os.environ["OPENAI_API_KEY"] = creds["openai_api_key"]
```

### Azure Key Vault

```python
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

credential = DefaultAzureCredential()
client = SecretClient(vault_url="https://your-vault.vault.azure.net/", credential=credential)
os.environ["OPENAI_API_KEY"] = client.get_secret("openai-api-key").value
```

### HashiCorp Vault

```bash
vault kv get -field=openai_api_key secret/rell/production
```

---

## Incident Response

### If API Keys Are Exposed

1. **Revoke immediately** — do not wait for confirmation of misuse
   - OpenAI: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
   - Anthropic: [console.anthropic.com](https://console.anthropic.com)
2. Remove the key from git history: `git filter-repo --path .env --invert-paths`
3. Generate a new key with the minimum required permissions
4. Review API usage logs for any unauthorized calls

### If a `.env` File Is Committed

```bash
# Remove from all history
git filter-repo --path .env --invert-paths
git push --force-with-lease

# Rotate all credentials in the file immediately
```

### If Audit Output Files Are Exposed

1. Classify the exposure — what data categories were in the findings?
2. Determine if GDPR Article 33 (72-hour breach notification) applies
3. If personal data was involved, consult your DPO
4. Revoke any access that may have allowed the exposure

---

## Quick Security Checklist

Before running Rell in any environment, verify:

```
[ ] .env is listed in .gitignore
[ ] DB user is read-only (SELECT only, no INSERT/UPDATE/DELETE)
[ ] No admin or sa accounts in DB_CONN_* values
[ ] API keys are stored in .env or env vars, not in source code
[ ] data/output/ is not publicly accessible (not in web root, not public S3)
[ ] --llm mode chosen matches data sensitivity level:
      - Regulated data     → no --llm flag (deterministic)
      - Sensitive business → --llm ollama
      - Non-sensitive      → --llm openai|claude (with DPA)
[ ] Audit output retention policy is defined
[ ] Ollama base URL is localhost (not exposed to internet) if using --llm ollama
```

---

*Rell is an audit tool — its job is to find problems in other people's data practices. Hold it to the same standard.*
