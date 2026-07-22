# Phase 3 Test Report

Date: 2026-07-22
Environment: local macOS, Python 3.14.3
Project support floor: Python 3.11

## Automated result

| Gate | Result |
| --- | --- |
| pytest | 71 passed |
| Ruff lint/format | Passed; 66 files formatted |
| strict mypy | Passed; 48 package/script source files checked |
| pre-commit | Passed all configured hooks |
| Wheel build | Passed: `nhc_deprot_ranker-0.1.0-py3-none-any.whl` |
| Wheel SHA256 | `1130455824ef1ec241e95029bee3bae028bea23be2360544bb11fe5f8f828929` |
| Phase 3 CLI dry-run | Passed; reported no H2, Phase 4, HPC write, or quantum-chemistry action |
| Phase 3 synthetic end to end | Passed, including immutable atomic output and nine figures |
| Real nested readback | LOOCV/axis-A/axis-B all 71/71; 213 total OOF rows |
| Held-out family fallback | Exact zero contribution for every held-out axis family |
| Model roundtrip | Predictions bitwise identical; direct-solver diagnostics preserved |
| Bootstrap | 2,000 requested, 2,000 successful, fixed selected penalties |
| Output/source hash readback | All 24 runtime files accounted for; every recorded hash matched |
| Private path/fake-IP scan | No matches in runtime result or tracked candidate files |

## Behavior covered

- recovery of known intercept, slope, and additive axis-family effects;
- inactive single-skeleton identifiability rule and exact zero effect;
- stronger shrinkage for rarer families and convergence toward zero as lambda grows;
- lambda-zero training predictions matching identifiable unpenalized behavior;
- finite zero-effect fallback for unseen skeleton/axis levels;
- direct and recorded Moore–Penrose solver paths;
- rejection of NaN, duplicate keys, invalid penalties, and zero xTB scale;
- deterministic finite coarse/refined penalty search and training-fold-only scaling;
- deterministic paired bootstrap with fixed nested-CV penalties and Top-K probabilities;
- exact save/load identity;
- outer/inner key disjointness, grouped-family isolation, and one OOF prediction per key;
- processed/baseline evidence hash rejection, atomic build cleanup, dry-run non-writing, and immutable existing-result rejection.

## Visual QA

All nine PNGs were generated headlessly and inspected. The H1/B1 aggregate plot makes the Axis-B MAE regression visible rather than hiding it. Both family forest plots show broad intervals for sparse levels, the bootstrap prediction plot is explicitly labeled as full-fit rather than OOF, and the sign-stability plot exposes weakly identified families. Plot footers state n, split protocol, dataset/model version, OOF status, and interval definition.
