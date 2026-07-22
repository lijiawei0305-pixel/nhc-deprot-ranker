# Project Implementation Report

## Outcome

Phases 0–5 are complete locally as of 2026-07-22. The project audited the legacy evidence, built one immutable dataset, evaluated B0/B1/H1 under honest protocols, selected `raw_xTB_wins`, scored the complete candidate pool, and produced a local high-fidelity acquisition suggestion.

## Delivered pipeline

1. Phase 0 pinned source identities, electronic-energy semantics, family symmetry, server boundaries, and a portable repository under MIT.
2. Phase 1 built `data/processed/v001` with 401,856 candidates, 71 labels, complete fragment coverage, one protocol identity, and zero key/formula/conflict failures.
3. Phase 2 reproduced B0/B1, exact LOOCV, grouped family holdouts, ranking metrics, and 2,000 coefficient bootstraps.
4. Phase 3 implemented H1 with train-only preprocessing, nested penalty selection, zero unknown-family fallback, grouped validation, and bootstrap family audits.
5. Phase 4 compared frozen B0/B1/H1 evidence and selected B0 raw xTB. B1 remains only an absolute-scale companion; H1 was not promoted.
6. Phase 5 scored all 401,856 candidates, audited applicability, exported Top-100, and selected 50 unique unlabeled candidates with exact `15/13/12/10` quotas.

The unified CLI now supports `audit-legacy`, `validate-labels`, `build-dataset`, `train`, `evaluate`, `score`, and `acquire`. Production outputs are constructed atomically, refuse overwrite, and carry input/output/source SHA256 identities.

## Scientific result

The final production ranking is B0 raw xTB, lower is better. B1 has a positive affine slope and improves the absolute electronic-energy scale but not ranking. H1 has some positive point estimates but fails stable head-recall, stable B0-improvement, catastrophic-family, and supported-offset stability gates.

Phase 5 preserves this decision exactly: all B0/B1 ranks are identical, every `rank_shift` is zero, and H1 does not enter scoring or acquisition. B1 interval fields are limited to coefficient-resampling uncertainty and are never claimed as total predictive uncertainty.

## Quality and evidence

The current release gate passes pytest, Ruff, strict mypy, pre-commit, package build, CLI dry-runs, real-result hash readback, private-path checks, and visual QA. Large runtime files remain ignored; checked-in manifests preserve the processed, baseline, hierarchical, decision, scoring, and acquisition identities.

Exact per-phase commands, files, assumptions, counts, tests, negative evidence, and gate decisions are in `PHASE1_REPORT.md` through `PHASE5_REPORT.md` and their paired test reports.

## Explicit boundary

No phase ran new PySCF, xTB, Hessian, VASP, or CP2K calculations. Phase 5 did not connect to HPC, write to a server, transfer a batch, or submit a job. The 50 candidates are local suggestions for future labels, not validated synthesis targets or proof of DFT accuracy.
