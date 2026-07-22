# Phase 4 Test Report

Date: 2026-07-22
Environment: local macOS, Python 3.14.3
Project support floor: Python 3.11

## Automated result

| Gate | Result |
| --- | --- |
| pytest | 79 passed |
| Ruff lint/format | Passed; 70 files formatted |
| strict mypy | Passed; 50 package/script source files checked |
| pre-commit | Passed all configured hooks |
| Wheel build | Passed: `nhc_deprot_ranker-0.1.0-py3-none-any.whl` |
| Wheel SHA256 | `72780ebafa69f113b9eae4d1b830896499b6dacb05cbc5dcfbdf27d7c0c37cce` |
| Phase 4 CLI dry-run | Passed; reported no refit, retuning, Phase 5, full-pool, HPC, or quantum-chemistry action |
| Synthetic decision outcomes | All four allowed outcomes reachable |
| Real aligned evidence | 213 OOF rows; 71/71 keys in each of three protocols |
| Paired OOF bootstrap | 2,000/2,000 successful per protocol; 6,000 total; zero failures |
| Family-collapse audit | Confirmed absolute-and-ratio conjunction; one real failure |
| Offset-stability audit | Confirmed support filter and conditional sign probability; one real failure |
| Output/source hash readback | 55 inputs and all 13 runtime files accounted for and matched |
| Private path/fake-IP scan | No matches in the runtime result |

## Behavior covered

- deterministic aligned key bootstrap without model refitting or penalty retuning;
- candidate-minus-baseline intervals for Spearman, Kendall, pairwise accuracy, NDCG, head recall, regret, MAE, and RMSE;
- B1 positive-improvement, rank non-inferiority, regret, stability, and reproducibility gates;
- H1 grouped rank, stable recall, regret, zero unknown fallback, family collapse, offset stability, exact-combined absence, blind/size availability, B0 comparison, and reproducibility gates;
- exact configured threshold direction for lower-is-better regret and higher-is-better ranking metrics;
- all four permitted outcomes and their production defaults;
- Phase 1/2/3 hash, version, source identity, gate, key, fold, truth, and prediction mismatch rejection;
- atomic result construction, dry-run non-writing, temporary cleanup, and immutable existing-result rejection.

## Visual QA

All four PNGs were generated headlessly and inspected. Primary metric and recall intervals clearly show which intervals cross zero. The family-collapse plot highlights only `Br|CF3` in red under the confirmed conjunction, and the stability plot labels `axis_b_family:Me|NO2` below the `0.60` line. Titles, axes, legends, decision/data versions, OOF status, interval definition, and no-refit notes are present; long provenance footers on the two compact family plots reach the crop boundary but do not obscure the scientific evidence.
