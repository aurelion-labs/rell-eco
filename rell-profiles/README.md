# rell-profiles

> The curated compliance ruleset registry for RELL.

**License:** BSL (Business Source License)  
**Status:** Architecture phase | v0.1.0 in progress

## What This Is

`rell-profiles` is the moat. While the engine is open (MIT), this registry contains the compiled, maintained, and conflict-resolved compliance rulesets that make RELL immediately useful in regulated industries.

Each profile is a JSON file that tells `rell-engine` exactly what to check, how to score findings, and what severity to assign violations.

## Profile Registry

### Governance
| Profile | Standard | Status |
|---------|----------|--------|
| `gdpr-eu` | EU General Data Protection Regulation | In Progress |
| `ccpa-california` | California Consumer Privacy Act | Planned |
| `pdpa-thailand` | Thailand Personal Data Protection Act | Planned |
| `iso-27001` | ISO/IEC 27001 Information Security | Planned |
| `dpdp-india` | India Digital Personal Data Protection Act | Planned |

### Healthcare
| Profile | Standard | Status |
|---------|----------|--------|
| `hipaa-us` | HIPAA Privacy + Security Rules | Planned |
| `hl7-fhir-r4` | HL7 FHIR R4 Data Standards | Planned |
| `hitech` | HITECH Act Breach Notification | Planned |

### Infrastructure
| Profile | Standard | Status |
|---------|----------|--------|
| `nerc-cip` | NERC CIP Critical Infrastructure | Planned |
| `cmmc-level2` | CMMC Level 2 (US Defense) | Planned |

### Economic
| Profile | Standard | Status |
|---------|----------|--------|
| `imf-article4` | IMF Article IV Indicators | Planned |
| `worldbank-wdi` | World Bank Development Indicators | Planned |

### ESG
| Profile | Standard | Status |
|---------|----------|--------|
| `gri-2021` | GRI Universal Standards 2021 | Planned |
| `tcfd` | TCFD Climate Disclosure Framework | Planned |
| `sec-climate` | SEC Climate Disclosure Rule | Planned |

## Profile Structure

Each profile is a JSON file:

```json
{
  "profile_id": "gdpr-eu",
  "version": "1.0.0",
  "standard": "General Data Protection Regulation (EU) 2016/679",
  "jurisdiction": "European Union",
  "last_reviewed": "2026-02-18",
  "obligations": [
    {
      "article": "Art. 5(1)(a)",
      "title": "Lawfulness, fairness, transparency",
      "check_type": "consent_field_present",
      "severity": "CRITICAL",
      "fields": ["consent_flag", "consent_timestamp", "consent_basis"]
    }
  ]
}
```

## Licensing

Community tier: `gdpr-eu` is free and open.  
Full registry: BSL — contact z3rosl33p for commercial licensing.

The engine is open. The profiles are where the maintenance, legal review, and conflict resolution live. That work has real value.
