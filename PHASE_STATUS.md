# Phase Status

Updated: 2026-07-22

| Phase | Status | Gate |
| --- | --- | --- |
| Phase 0 — legacy audit | Complete | Passed 2026-07-22 |
| Phase 1 — data contract/import | Complete and merged to `main` | Passed 2026-07-22 |
| Phase 2 — baselines | Complete on `agent/phase2-baselines` | Passed 2026-07-22 |
| Phase 3 — hierarchical model | Not started | Phase 2 pass required |
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

## Current boundary

Phase 0/1 are published on `main`; Phase 2 is complete on its review branch. Runtime data/models/results remain ignored local artifacts, while exact hashes and quality evidence are checked in. No H1 model, production promotion, quantum-chemistry calculation, full-pool scoring, or HPC job has been performed.

## Next action

Review and merge the Phase 2 draft pull request. Phase 3 requires separate authorization and does not start automatically.
