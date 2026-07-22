# Phase 0 Implementation Report

## Completed

- Initialized an independent `main` Git repository without modifying the legacy project.
- Added repository-wide operating constraints and documentation-first gates.
- Audited all 21 required legacy files, the authoritative full candidate table, both family lookup sources, all 71 labels, and historical baseline analyses.
- Added portable tracked configuration and an ignored real-location configuration.
- Added typed source configuration, electronic-label formula validation, deterministic protocol hashing, SHA256 utilities, primary-key checks, family canonicalization, normalized schemas, a unified Phase 0-safe CLI, and direct script wrappers.
- Added requested package/module directory skeletons for later phases without implementing training/scoring.
- Added synthetic, HPC-independent Phase 0 tests and development quality configuration.

## Scientific assumptions used

- Target is electronic energy with the legacy proton constant.
- Lower is better.
- Skipped Hessian labels remain usable as electronic-energy-only labels.
- Symmetry is exchange invariance.
- Current skeleton metadata is explicitly imidazolium.
- Exact combined-family effects are disabled because all labeled combinations are singletons.

## Explicitly not performed

- No PySCF, xTB, Hessian, VASP, or CP2K run.
- No model training, nested CV, bootstrap ensemble, full-pool scoring, or acquisition ranking.
- No HPC write, upload, download of large data, process action, or job submission.
- No claim of model superiority or DFT-level predictive accuracy.

## Phase boundary

Later CLI commands return a clear Phase 0 boundary error. Phase 1 requires separate user approval after the final Phase 0 gate.

## Gate decision

**Phase 0 passed on 2026-07-22.** Evidence and quality-gate details are in `LEGACY_AUDIT.md`, `DATA_AUDIT.md`, `TEST_REPORT.md`, and `REPRODUCIBILITY.md`.
