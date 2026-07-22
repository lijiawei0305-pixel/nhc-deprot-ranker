# Phase 5 Full-Pool Scoring and Acquisition Report

## Outcome

Phase 5 passed on 2026-07-22. The frozen Phase 4 winner, B0 raw xTB, scored and ordered all 401,856 unique candidates. B1 supplied a separate DFT-scale affine companion and coefficient-bootstrap interval; it did not change any rank. H1 was not loaded for prediction or used by acquisition.

The immutable local outputs are `results/scoring_v001` and `results/acquisition_v001`. Large runtime artifacts remain ignored. Their complete checked-in evidence is in `SCORING_V001_MANIFEST.json` and `ACQUISITION_V001_MANIFEST.json`.

## Inputs read

No legacy-repository or server file was newly read in Phase 5. The implementation read only the frozen local derivatives and registered evidence created in Phases 1, 2, and 4:

- `data/processed/v001` and `PROCESSED_V001_MANIFEST.json`;
- `results/baselines_v001` and `BASELINES_V001_MANIFEST.json`;
- `results/decision_v001` and `DECISION_V001_MANIFEST.json`;
- the confirmed `configs/acquisition.yaml` policy.

Every registered upstream hash was verified before output construction. The Phase 4 decision had to equal `raw_xTB_wins` with production default `B0_raw_xTB`.

## Full scoring

| Check | Result |
| --- | ---: |
| Candidate rows / unique InChIKeys | 401,856 / 401,856 |
| Missing or duplicate InChIKeys | 0 / 0 |
| Missing/non-finite xTB score | 0 |
| Top review rows | 100 |
| B0/calibrated rank differences | 0 |
| Nonzero `rank_shift` | 0 |
| B1 coefficient replicates | 2,000 |
| B1 replicate slope range | 0.625914–0.806484 |
| Rows outside labeled xTB range | 2,782 |
| Rows missing both validated size fields | 401,856 (100%) |
| Rows with both axis families seen | 2,316 |
| Fully `in_domain` rows | 0 |
| Core-domain rows ignoring unavailable size | 103 |

The production order is ascending `(xtb_deprot_kcal, inchikey)`. B1 uses `196.1773139188 + 0.7157116718 * xTB`; all 2,000 resampled slopes are positive, so every replicate preserves B0 order. Top-10/50/100 membership probabilities are therefore deterministic 0/1 membership frequencies. B1 p05/p50/p95 and standard deviation describe coefficient-resampling uncertainty only; they do not include residual noise or H1 family uncertainty.

Size was not synthesized from SMILES. Every row carries `size_unavailable`, so no row is mislabeled fully in-domain. Family support, baseline extrapolation, sparse-family, interval-width, high-uncertainty, and per-axis seen flags/counts remain directly auditable.

## Acquisition result

The eligible pool contains 401,785 unlabeled candidates after excluding all 71 labeled InChIKeys exactly once. The local suggestion contains 50 unique candidates with zero label overlap and exact largest-remainder quotas:

| Bucket | Selected |
| --- | ---: |
| Predicted top region | 15 |
| Cutoff region | 13 |
| Chemical-family diversity | 12 |
| Uncertain/OOD/conflict | 10 |

No bucket required global-pool fill. The batch spans production ranks 1–69, 46 combined families, 10 axis-A families, and 21 axis-B families. All 50 are below the labeled xTB range, have unseen axis A, have high B1 coefficient uncertainty by the registered threshold, and lack validated size; 24 also have unseen axis B. These are explicit risk signals, not claims that the batch is high-confidence or experimentally best.

`high_fidelity_batch_manifest.json` carries the registered B3LYP-D3(BJ)/def2-SVP electronic-energy protocol, cation/neutral states, SMILES, reason codes, and priorities. It explicitly records `hessian_computed=false`, `submit_hpc=false`, and `server_write_authorized=false`.

## Files created or modified

Phase 5 added typed acquisition configuration, B0/B1 scoring, applicability auditing, deterministic quota/diversity selection, atomic immutable runners, CLI commands, eight audit figures, synthetic and end-to-end tests, evidence manifests, and Phase 5 documentation. It updated `AGENT.md`, `PHASE_STATUS.md`, `README.md`, `MODEL_CARD.md`, `ACQUISITION.md`, and `REPRODUCIBILITY.md` to reflect the completed boundary.

## Scientific assumptions

- lower xTB deprotonation electronic energy ranks better;
- B0 is the only formal production ordering because Phase 4 selected `raw_xTB_wins`;
- positive B1 affine transforms may calibrate the absolute electronic-energy scale but cannot supply a ranking improvement;
- B1 coefficient bootstrap is a limited parameter-uncertainty companion, not total predictive uncertainty;
- unavailable size cannot be inferred or silently treated as in-domain;
- family novelty supports data acquisition but does not reintroduce unpromoted H1 corrections;
- the selected molecules are suggestions for more electronic-energy labels, not validated synthesis targets.

## Commands and verification

Both `score` and `acquire` were run in dry-run mode before their real local executions. The real scoring command created 401,856 rows in about 14.4 seconds on the recorded local environment. Independent readback rehashed every registered output, rechecked unique keys, exact B0 ranks, Top-100 identity, zero rank shift, deterministic Top-K fields, applicability flags, label exclusion, quota realization, and local-only manifest flags.

All eight figures were inspected. A pre-freeze footer-layout issue was corrected; the immutable outputs were then rebuilt from the same verified inputs, rehashed, and reinspected with complete titles, axes, legends, provenance, and uncertainty scope visible.

## External computation not performed

No PySCF, xTB, Hessian, VASP, or CP2K calculation ran. No SSH/HPC connection, server write, file transfer, scheduler query, or job submission occurred. Phase 5 produces a local recommendation only; starting high-fidelity calculations would require a new explicit authorization and execution plan.

## Gate decision and next task

Phase 5 passes: full coverage, rank identity, uncertainty semantics, applicability, exact unlabeled quotas, hashes, independent readback, tests, and no-external-action constraints all succeeded. The next work is publication of this Phase 5 branch and review/merge to `main`. Any actual DFT acquisition campaign is a separate phase and remains unstarted.
