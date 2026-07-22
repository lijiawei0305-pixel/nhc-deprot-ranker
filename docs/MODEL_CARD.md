# Model Card — Production Ranking Default v001

## Status and decision

Phase 4 outcome: `raw_xTB_wins`.

The production ranking default is **B0 raw GFN2-xTB deprotonation electronic energy**, with lower values ranked better. B1 remains the approved absolute electronic-energy calibration model when a DFT-scale number is required. H1 remains a research candidate and is not promoted.

This decision was made from 71 frozen labels and three aligned honest OOF protocols. No model was refit or retuned in Phase 4. Phase 5 subsequently applied the frozen decision to all 401,856 candidates without refitting.

## Model definitions

Ranking default:

```text
score = xtb_deprot_kcal
lower_is_better = true
```

Absolute-calibration companion:

```text
dft_electronic_estimate = 196.1773139188 + 0.7157116718 * xtb_deprot_kcal
```

B1 is not a ranking upgrade: its positive affine slope preserves full-fit xTB order, while its fold-specific honest rank metrics do not improve on B0.

## Intended use

- prioritize imidazolium NHC precursor candidates for additional electronic-energy calculations;
- compare candidates under the registered `NHC-H+ -> NHC + H+` electronic-energy convention;
- use B1 only when an approximate DFT-scale electronic deprotonation energy is useful.

The models do not predict synthesis success, solution chemistry, a complete 298.15 K Gibbs free energy, frequency-confirmed minima, kinetics, or Cu(111) binding.

## Evidence and decision gates

All comparisons use the same 71 InChIKeys under LOOCV, leave-axis-A-family-out, and leave-axis-B-family-out validation.

### B1 versus B0

B1 passes provisional non-inferiority and regret thresholds, but fails the mandatory improvement gate: Spearman and Kendall point deltas are negative under all three protocols. It therefore cannot replace B0 for ranking despite its much better absolute calibration.

### H1 versus B1 and B0

H1 improves point Spearman and Kendall versus B1 under all protocols. Its LOOCV Spearman delta is `+0.015895` with paired-bootstrap 95% interval `[+0.000134, +0.037695]`. However:

- the only positive head-recall point delta is `+0.05` for true Top-20 within predicted Top-20 under LOOCV, with interval `[-0.05, +0.20]`;
- no H1 primary-ranking improvement over B0 has a non-negative 95% lower bound; LOOCV Spearman H1-minus-B0 is `+0.014017`, interval `[-0.001242, +0.034039]`;
- held-out axis-B family `Br|CF3` is catastrophic under the confirmed conjunction: B1 MAE `1.0269`, H1 MAE `4.7791`, increase `3.7522 kcal/mol`, ratio `4.654×`;
- supported axis-B offset `Me|NO2` has conditional sign stability `0.5331`, below the registered `0.60` threshold;
- axis-B aggregate H1 MAE is also worse than B1 (`2.9163` versus `2.7875 kcal/mol`).

H1 passes grouped Spearman/Kendall non-inferiority, zero-effect unknown-family fallback, finite prediction, regret, exact-combined-effect absence, and reproducibility checks. These passes do not override its failed recall, family-collapse, offset-stability, and stable-B0-improvement gates.

## Uncertainty

Phase 4 uses 2,000 deterministic paired InChIKey bootstrap replicates per OOF protocol, seed `20260722`, with zero failures. Truth and B0/B1/H1 predictions are resampled together. Models are not refit and H1 penalties are not retuned.

These Phase 4 intervals describe uncertainty in fixed OOF metric comparisons. They are not per-candidate predictive intervals.

Phase 5 separately applies the 2,000 stored B1 coefficient replicates to each candidate and records mean, sample standard deviation, p05, p50, p95, and width. Those fields quantify affine coefficient-resampling uncertainty only. They omit residual error, model-form error, H1 effects, structure error, and protocol error, and therefore must not be presented as total predictive intervals. All replicate slopes are positive (`0.625914–0.806484`), so their Top-K membership is exactly the B0 membership.

## Applicability and fallback

- B0 requires a finite `xtb_deprot_kcal` computed under the registered xTB protocol.
- The decision is supported only for the audited imidazolium precursor domain represented by the v001 candidate contract.
- B0 itself has no learned family vocabulary and therefore does not fail on an unseen family label.
- B1 should not be extrapolated far beyond its labeled training xTB range, `57.3482–116.1717 kcal/mol`, without an explicit warning.
- H1 unknown-family effects are exactly zero, but H1 is not the production default.
- Phase 5 found 2,782 candidates outside the B1 training xTB range, 373,576 with unseen axis A, 368,992 with unseen axis B, and only 2,316 with both axes seen.
- Both validated size fields are unavailable for all 401,856 candidates. Every row therefore carries `size_unavailable`; zero rows are claimed fully in-domain. A separate core-domain flag ignores only this universally missing dimension and contains 103 rows.

## Known limitations

- only 71 high-fidelity electronic-energy labels are available;
- 22/38 axis-A and 16/35 axis-B families are singletons;
- all 71 exact combined families are singletons;
- the skeleton term is unidentifiable because all labels are `imidazolium`;
- no validated size field supports size extrapolation;
- no genuinely unused blind holdout remains;
- labels are electronic energies and do not establish Hessian-confirmed minima or Gibbs free energies;
- B0 has a large absolute offset and must not be presented as a calibrated DFT energy;
- the first 50 B0-ranked candidates all lie below the labeled xTB range and have at least one unseen axis; top rank does not imply high confidence or synthetic desirability.

## Reproducibility identity

- dataset: `v001`, 401,856 candidates, 71 labels;
- decision: `results/decision_v001`, outcome `raw_xTB_wins`;
- decision manifest SHA256: `a12ddd334187051f21dd5a4223fb92b94c8cff711765be8b305f7c01593c0c05`;
- Phase 4 source-tree SHA256: `d1014ec2dea78fbee00ad48ee8de0a61751faf514a40f732fcdc5ad84d70ffa2`;
- Phase 4 policy: `configs/evaluation.yaml`, SHA256 `6932899131dcceca49cfb0807f4b69903dde32e5c7bd5835406fbc5cf41c27a4`;
- Phase 5 score: `results/scoring_v001`, 401,856 rows, manifest SHA256 `c9c87b1597ed8d994b089595b9da7c93a21467dbee82d1e0256a0e3fce5dacf6`;
- Phase 5 full ranked table SHA256: `dc560def31e2f6726404b3325ddf485aa065c782dfd205e17d90d310feb9d6ec`;
- Phase 5 acquisition: `results/acquisition_v001`, 50 rows, manifest SHA256 `ee243360640299a0819f5ccf51a20ee30c31f56f581c4dbaa59c7522e2f1e94b`.

Exact inputs, outputs, gates, metric intervals, family audits, full scoring, and acquisition identities are recorded in `DECISION_V001_MANIFEST.json`, `SCORING_V001_MANIFEST.json`, `ACQUISITION_V001_MANIFEST.json`, and the phase reports.

## Deployment boundary

Phase 5 produces local full-pool ranking, applicability, and acquisition artifacts only. It does not deploy a service, run quantum chemistry, write to the legacy project/server, or submit HPC jobs. Acting on the 50-candidate suggestion requires a new documented phase and explicit authorization.
