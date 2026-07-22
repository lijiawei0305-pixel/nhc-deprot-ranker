# Phase Status

Updated: 2026-07-22

| Phase | Status | Gate |
| --- | --- | --- |
| Phase 0 — legacy audit | Complete | Passed 2026-07-22 |
| Phase 1 — data contract/import | Complete and merged to `main` | Passed 2026-07-22 |
| Phase 2 — baselines | Complete and merged to `main` | Passed 2026-07-22 |
| Phase 3 — hierarchical model | Complete on `agent/phase3-hierarchical`; awaiting review | Passed 2026-07-22 |
| Phase 4 — model decision | Not started | Phase 3 pass required |
| Phase 5 — full scoring/acquisition | Not started | Promoted Phase 4 model required |

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

## Current boundary

Phase 0/1/2 are published on `main`; Phase 3 is complete on its isolated branch and awaits review. Runtime data/models/results remain ignored local artifacts, while exact hashes and quality evidence are checked in. No Phase 4 decision, production promotion, quantum-chemistry calculation, full-pool scoring, or HPC job has been performed.

## Next action

Review and merge the Phase 3 draft PR. Start Phase 4 only after separate user authorization; the current evidence does not itself promote H1.
