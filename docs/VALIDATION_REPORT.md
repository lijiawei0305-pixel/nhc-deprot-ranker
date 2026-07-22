# Validation and Production Decision Report

## Final outcome

Phase 4 selected `raw_xTB_wins` from the frozen 71-label evidence. B0 raw xTB is the production ranking default, B1 is the absolute-scale affine companion, and H1 is not promoted.

## Evidence

All models were compared over identical InChIKeys under LOOCV, leave-axis-A-family-out, and leave-axis-B-family-out protocols. Phase 4 used 2,000 paired fixed-OOF bootstrap replicates per protocol, with zero failures and no model refitting or penalty retuning.

B1 did not improve Spearman or Kendall point estimates over B0 under any protocol, although it substantially improves absolute calibration. H1 improved several point rank correlations but failed required stable head recall, stable improvement over B0, one catastrophic held-out axis-B family (`Br|CF3`), and one supported-offset stability case (`Me|NO2`). No genuinely unused blind holdout or validated size extrapolation set exists.

The complete comparisons, intervals, thresholds, and negative evidence are in `PHASE4_REPORT.md` and `DECISION_V001_MANIFEST.json`.

## Phase 5 production invariants

Full scoring verified 401,856/401,856 unique candidates, exact equality of stored xTB, production, and calibrated ranks, and zero nonzero rank shifts. All 2,000 B1 coefficient slopes are positive, so Top-10/50/100 membership is invariant in every replicate.

Applicability is not inferred from finite output. There are 2,782 baseline extrapolations; all rows lack validated size; most families are unseen; and zero rows are called fully in-domain. Acquisition excludes all 71 labels, selects 50 unique keys with exact quotas, and exposes that all 50 proposed points are outside the labeled xTB range.

## Claims not supported

The evidence does not establish DFT accuracy for the complete pool, Gibbs free energies, frequency-confirmed minima, experimental synthesis success, H1 family physics, or that the first-ranked candidate is chemically optimal. Phase 5 B1 intervals cover coefficient resampling only and are not total predictive intervals.
