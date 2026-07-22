# Phase Status

Updated: 2026-07-22

| Phase | Status | Gate |
| --- | --- | --- |
| Phase 0 — legacy audit | Complete | Passed 2026-07-22 |
| Phase 1 — data contract/import | Complete and merged to `main` | Passed 2026-07-22 |
| Phase 2 — baselines | Complete and merged to `main` | Passed 2026-07-22 |
| Phase 3 — hierarchical model | Complete and merged to `main` | Passed 2026-07-22 |
| Phase 4 — model decision | Complete and merged to `main` | Passed 2026-07-22; `raw_xTB_wins` |
| Phase 5 — full scoring/acquisition | Complete and merged to `main` | Passed 2026-07-22 |
| Phase 6 — local DFT execution plan | Complete locally on `agent/phase6-local-dft-prep` | Local plan passed 2026-07-22; geometry/execution blocked |

## Current completed work

- Read the full task specification in `prompt.md`.
- Established repository-wide constraints in `AGENT.md`.
- Confirmed the `legacy_repo.root` current working tree as the primary Phase 0 audit source.
- Restricted the separate server-knowledge worktree to connection/HPC operating knowledge.
- Wrote the scientific scope, Phase 0 execution plan, and pre-execution audit template.
- Verified all 21 required legacy files and recorded their hashes.
- Established the 71-label composition, overlaps, local formula checks, target protocol, historical affine baseline, and feature-shortcut findings.
- Documented a no-write/no-compute server verification plan for the two HPC-only authoritative tables and raw gold endpoints.
- Completed the approved server read-only audit and closed all identified data-source gaps.
- Created the independent Git repository skeleton, MIT license, portable configuration, ignored local source map, package/CLI skeleton, Phase 0 utilities, source manifest, and reports.
- Published the Phase 0 foundation as the public GitHub repository `lijiawei0305-pixel/nhc-deprot-ranker` under MIT.
- Implemented local/SSH read-only streaming import, formula checks, canonical families, label conflict handling, protocol identity, provenance, atomic output, and immutable version enforcement.
- Built and independently verified `data/processed/v001`: 401,856 candidates, 71 labels, 100% fragment coverage, zero formula failures/conflicts, and one label protocol.
- Passed pytest (31), Ruff, mypy, configuration parsing, package build, pre-commit, and private-path checks.
- Merged Phase 1 PR #1 into `main` as `3626b0d` and opened the isolated Phase 2 baseline branch.
- Implemented B0/B1, exact LOOCV, axis-family holdouts, deterministic bootstrap, ranking metrics, immutable results, and auditable figures.
- Built and independently verified `results/baselines_v001`: 71 OOF rows per protocol, historical reproduction passed, 2,000/2,000 bootstrap fits succeeded, and all split/hash checks passed.
- Confirmed B1 improves absolute calibration but does not improve B0 ranking; production promotion remains deferred to Phase 4.
- Merged Phase 2 PR #2 into `main` as `e33e5cf` and opened the isolated Phase 3 branch.
- Re-audited current H1 support: one skeleton, 38 axis-A families (22 singletons), 35 axis-B families (16 singletons), and 71 combined-family singletons.
- Implemented the H1 penalized additive estimator, deterministic finite nested penalty search, train-only preprocessing, zero-effect unknown-family fallback, fixed-penalty paired bootstrap, serialization, manifests, and nine figures.
- Built and independently verified `results/hierarchical_v001`: LOOCV/axis-A/axis-B each cover 71/71 keys, all held-out family contributions are zero, model roundtrip is exact, and 2,000/2,000 bootstrap fits succeeded.
- Recorded provisional H1-vs-B1 evidence without promotion: H1 improves LOOCV MAE from 2.7216 to 2.2373 kcal/mol and Spearman from 0.95708 to 0.97297; Axis-B MAE worsens from 2.7875 to 2.9163 despite improved rank correlations.
- Audited weak family identification: 72/73 active family-effect bootstrap 95% intervals cross zero; this limitation is carried forward to Phase 4.
- Merged Phase 3 PR #3 into `main` as `2571ddc` and opened the isolated Phase 4 branch.
- Audited the frozen promotion evidence and identified the only unresolved scientific policy: numerical definitions for catastrophic held-out-family error and bootstrap family-offset stability.
- Confirmed and froze the conservative Phase 4 family-collapse, conditional sign-stability, and stable head-recall rules in `configs/evaluation.yaml`.
- Implemented the frozen-evidence evaluator, deterministic paired OOF bootstrap, B1/H1 promotion gates, family collapse/stability audits, immutable manifests, CLI, and four figures.
- Built and independently verified `results/decision_v001`: 55 input hashes, 13 runtime files, 180 uncertainty rows, and 6,000/6,000 protocol bootstrap replicates all passed.
- Final decision: `raw_xTB_wins`. B1 failed to improve primary ranking; H1 failed stable head recall, stable improvement over B0, one catastrophic held-out family, and one supported offset-stability gate.
- Selected B0 as the production ranking default and retained B1 as the absolute-calibration companion; H1 was not promoted.
- Merged Phase 4 PR #4 into `main` as `18aae58` and opened the isolated Phase 5 branch.
- Re-audited all 401,856 candidate fields: size is missing for every row; 2,782 rows are outside the labeled xTB range; only 2,316 rows have both axis families seen in training; all raw Top-50 rows are below the labeled xTB range and have at least one unseen axis family.
- Confirmed all 2,000 B1 bootstrap slopes are positive (`0.6259–0.8065`), so B1 companion ranks and Top-K membership are identical to B0 in every replicate.
- Confirmed the dual-track B0/B1 output semantics, Top-100 review table, and 50-candidate acquisition policy with exact quotas `15/13/12/10`.
- Implemented typed Phase 5 configuration, full scoring, B1 coefficient-bootstrap companion intervals, applicability flags, deterministic acquisition, immutable manifests, CLI, and eight audit figures.
- Built and independently verified `results/scoring_v001`: 401,856 unique ranked candidates, exact B0/calibrated rank identity, zero rank shifts, 2,782 baseline extrapolations, explicit size-unavailable status on every row, and no fully in-domain claims.
- Built and independently verified `results/acquisition_v001`: 50 unique unlabeled candidates, zero overlap with 71 labels, exact quotas with no fill, 46 combined families, and a local-only high-fidelity manifest with `submit_hpc=false`.
- Passed 87 pytest tests, Ruff, strict mypy, real output/hash readback, and visual QA; no quantum-chemistry or server/HPC action occurred.
- Authorized Phase 6 only as local planning: audited the legacy no-Hessian interface, confirmed no complete cation/neutral XYZ pair exists for the selected 50, and identified the legacy runner's additional ωB97X-D single-point steps as an execution blocker.
- Implemented strict Phase 6 configuration, upstream evidence/runtime/`_SUCCESS` hash-chain validation, exact 5×10 allocation, four-bucket smoke selection, safe immutable text-only output, CLI, and synthetic failure-path tests.
- Built and independently verified `results/dft_input_plan_v001`: 50/50 unique candidates, zero overlap with 71 labels, exact `15/13/12/10` totals, five ten-row batches, four smoke rows, 15 files, six directories, and zero geometry/executable/symlink artifacts.
- Recorded `geometry_generated=false`, `quantum_chemistry_run=false`, `hessian_computed=false`, `execution_ready=false`, `server_write_authorized=false`, and `submit_hpc=false` throughout the package.
- Preserved both required blockers, `blocked_no_xyz` and `blocked_runner_extra_steps`, and published complete checked-in evidence in `docs/DFT_INPUT_PLAN_V001_MANIFEST.json`.

## Current boundary

Phase 0–6 local planning is complete. The frozen 50-row acquisition now has an immutable, non-executable 5×10 handoff plan. Large runtime data/models/results remain ignored; checked-in manifests preserve their exact identities. No geometry generation, quantum-chemistry calculation, HPC connection, server write, file transfer, or job submission has occurred.

## Next action

Pause before any new implementation or external action. Ask the user to choose the uniform initial-geometry source and whether to develop a dedicated two-endpoint B3LYP-D3(BJ)/def2-SVP runner (recommended) or explicitly accept the legacy runner's additional single-point calculations.
