# rell-gov

> RELL instance for data governance and privacy compliance.

**License:** BSL  
**Status:** Planned | Follows `rell-engine` v0.1.0 and `rell-profiles` v0.1.0

## Target Market

Corporations handling personal data with obligations under:
- GDPR (EU)
- CCPA / CPRA (California)
- PDPA (Thailand)
- DPDP Act (India)
- ISO 27001

## What It Does

`rell-gov` bundles `rell-engine` with the governance profile set from `rell-profiles`. One install covers the most common privacy and data governance obligations.

```bash
rell init --profile gdpr-eu
python run_audit.py
```

## Profiles Included

| Profile | Standard |
|---------|----------|
| `gdpr-eu` | EU GDPR |
| `ccpa-california` | California CCPA/CPRA |
| `pdpa-thailand` | Thailand PDPA |
| `iso-27001` | ISO/IEC 27001 |

## Status

Waiting on `rell-engine` extraction and `rell-profiles` v0.1.0 completion.
