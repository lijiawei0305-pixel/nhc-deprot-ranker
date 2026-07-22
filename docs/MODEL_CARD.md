# Model Card — Production Ranking Default v001

## Status and decision

Phase 4 outcome: `raw_xTB_wins`.

The production ranking default is **B0 raw GFN2-xTB deprotonation electronic energy**, with lower values ranked better. B1 remains the approved absolute electronic-energy calibration model when a DFT-scale number is required. H1 remains a research candidate and is not promoted.

This decision was made from 71 frozen labels and three aligned honest OOF protocols. No model was refit or retuned in Phase 4, and the 401,856-row candidate pool was not scored.

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

These intervals describe uncertainty in fixed OOF metric comparisons. They are not per-candidate predictive intervals and do not cover the full candidate pool.

## Applicability and fallback

- B0 requires a finite `xtb_deprot_kcal` computed under the registered xTB protocol.
- The decision is supported only for the audited imidazolium precursor domain represented by the v001 candidate contract.
- B0 itself has no learned family vocabulary and therefore does not fail on an unseen family label.
- B1 should not be extrapolated far beyond its labeled training xTB range, `57.3482–116.1717 kcal/mol`, without an explicit warning.
- H1 unknown-family effects are exactly zero, but H1 is not the production default.

## Known limitations

- only 71 high-fidelity electronic-energy labels are available;
- 22/38 axis-A and 16/35 axis-B families are singletons;
- all 71 exact combined families are singletons;
- the skeleton term is unidentifiable because all labels are `imidazolium`;
- no validated size field supports size extrapolation;
- no genuinely unused blind holdout remains;
- labels are electronic energies and do not establish Hessian-confirmed minima or Gibbs free energies;
- B0 has a large absolute offset and must not be presented as a calibrated DFT energy.

## Reproducibility identity

- dataset: `v001`, 401,856 candidates, 71 labels;
- decision: `results/decision_v001`, outcome `raw_xTB_wins`;
- decision manifest SHA256: `a12ddd334187051f21dd5a4223fb92b94c8cff711765be8b305f7c01593c0c05`;
- Phase 4 source-tree SHA256: `d1014ec2dea78fbee00ad48ee8de0a61751faf514a40f732fcdc5ad84d70ffa2`;
- Phase 4 policy: `configs/evaluation.yaml`, SHA256 `6932899131dcceca49cfb0807f4b69903dde32e5c7bd5835406fbc5cf41c27a4`.

Exact inputs, outputs, gates, metric intervals, and family audits are recorded in `DECISION_V001_MANIFEST.json` and `PHASE4_REPORT.md`.

## Deployment boundary

Phase 4 selects B0 but does not execute Phase 5. Full-pool ranking, applicability flags, candidate export, and acquisition recommendations require separate authorization and a new immutable result.
