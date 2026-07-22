# Phase 2 Test Report

Date: 2026-07-22
Environment: local macOS, Python 3.14.3
Project support floor: Python 3.11

## Automated result

| Gate | Result |
| --- | --- |
| pytest | 54 passed |
| Ruff lint/format | Passed |
| strict mypy | Passed; 46 package/script source files checked |
| Wheel build | Passed: `nhc_deprot_ranker-0.1.0-py3-none-any.whl` |
| Wheel SHA256 | `a8741344a7b93570a3cad8a18a32b47c42e52a112518427ca71a575e82723468` |
| Phase 2 synthetic end to end | Passed, including nine figures |
| Real historical reproduction | Eight of eight comparisons passed |
| Real split readback | LOOCV/axis-A/axis-B all 71/71, no key leakage |
| Model roundtrip | Predictions identical and finite |
| Bootstrap | 2,000 requested, 2,000 successful, deterministic seed |
| Output hash readback | Every recorded artifact matched |
| Private path/fake-IP scan | No matches in runtime result |

## Behavior covered

- B0 identity prediction and applicability metadata;
- B1 recovery of known free intercept/slope, analytic uncertainty, numerical diagnostics, and degenerate/non-finite rejection;
- deterministic paired InChIKey bootstrap;
- model bundle save/load prediction identity;
- exact LOOCV coverage;
- complete held-out-family exclusion and key disjointness;
- perfect and reversed ranking behavior;
- deterministic key tie-breaking and pairwise tie filtering;
- distinct Top-M/selection-budget-K recall, precision, enrichment, NDCG, and regret;
- processed input hash rejection;
- atomic result construction, dry-run non-writing, and immutable existing-result rejection;
- complete CSV/JSON/Parquet/model/figure result assembly.

## Visual QA

All nine PNGs were generated headlessly. Calibration, Top-M recall, and grouped-CV figures were inspected at original resolution. The recall labels use numeric M/K order, the grouped B0/B1 MAE comparison uses an explicitly labeled log scale, and every plot footer states n, split protocol, model/data version, OOF status, and CI definition.
