# Phase 0 Test Report

Date: 2026-07-22
Environment: local macOS, Python 3.14.3
Project support floor: Python 3.11

## Results

| Gate | Result |
| --- | --- |
| pytest | 23 passed in 0.08 s |
| Ruff lint | All checks passed |
| Ruff format | 51 files already formatted |
| mypy | Success; 43 source files checked |
| YAML/JSON/TOML parse | Passed |
| Required Phase 0 skeleton | 28/28 checked paths present |
| Wheel build | Passed: `nhc_deprot_ranker-0.1.0-py3-none-any.whl` |
| Wheel SHA256 | `65787c136c59d6c2a6846d9fa8a694c33eb159f0577575efef04d7b793d498f0` |
| Ignored real-location config | Passed |
| Private path/IP scan outside ignored config/user prompt | No matches |

## Tested behavior

- Hartree-to-kcal conversion and `-6.28` proton constant;
- formula acceptance within tolerance and hard rejection beyond `0.02`;
- non-finite endpoint rejection;
- deterministic and protocol-sensitive SHA256 protocol IDs;
- N1/N3 and C4/C5 exchange-invariant family construction;
- explicit unknown family token and deterministic combined family;
- blank and duplicate primary-key rejection;
- exact file SHA256;
- typed read-only source configuration and writable-access rejection;
- streaming CSV key/missingness audit;
- local label CSV formula audit;
- finite normalized candidate schema and hash validation;
- CLI dry-run non-writing behavior;
- clear rejection of later-phase commands.

## Real-data formula smoke

The Phase 0 CLI validated the local blind-round-2 source in dry-run mode:

- rows/formula checked: 35/35;
- failures: 0;
- maximum absolute formula difference: `0.0002475915 kcal/mol`;
- no output file written.

The complete 401,856-row candidate and 71-label audits are documented separately in `LEGACY_AUDIT.md` and `DATA_AUDIT.md`; no large real input is part of the test suite.

## Not tested in Phase 0

No candidate/label production importer, model fit, nested/grouped CV, bootstrap, full scoring, acquisition, PySCF/xTB/Hessian, or HPC job behavior exists yet. Their tests remain gated by later phases.
