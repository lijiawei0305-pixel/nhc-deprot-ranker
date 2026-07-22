# Validation Protocol

Status: B0/B1 were implemented in Phase 2, H1 in Phase 3, and the frozen-evidence promotion decision in Phase 4. The final production ranking default is B0 raw xTB.

## 1. Leakage boundary

InChIKey is the split unit. Every fold refits preprocessing, family vocabulary, and hyperparameter selection using training rows only. Hyperparameters are selected in inner folds; outer folds are reserved for evaluation.

## 2. Required protocols

- LOOCV for historical comparison and per-label OOF predictions;
- leave-one-axis-A-family-out;
- leave-one-axis-B-family-out;
- combined-family holdout only when group count/support makes it meaningful;
- size extrapolation using a non-overlapping size split;
- a genuine pre-registered blind holdout only if an unused one exists.

The existing 12- and 35-molecule blind rounds have been revealed and influenced later analyses. They are historical external evidence, not a future blind test for this repository.

## 3. Metrics

Report MAE and RMSE, but decide ranking promotion primarily with:

- Spearman rho and Kendall tau;
- pairwise accuracy with configured tie threshold;
- recall of true Top-M within predicted Top-K;
- Precision@K, NDCG@K, enrichment factor, and Top-K regret;
- per-label rank-shift/residual audit.

All ranking functions are parameterized with `lower_is_better=true` and tested against perfect and reversed orderings.

## 4. Hyperparameters

Use finite, recorded searches inside inner CV. Start with a shared family penalty, then refine around the selected region. Final/outer test results cannot influence the grid.

## 5. Uncertainty

Bootstrap resampling uses InChIKey as the unit and a configured seed. Reports state whether penalties are retuned or fixed per bootstrap. Per-candidate intervals and Top-K probabilities come from the ensemble, not a single residual standard deviation.

## 6. Initial promotion thresholds

Thresholds live in `configs/evaluation.yaml`, including provisional non-inferiority values for Spearman, Kendall, and regret. A promotion report compares B0, B1, and H1 under the same OOF/held-out rows and can return `insufficient_evidence`.

Phase 4 registered numerical family-collapse, conditional offset-stability, stable primary-rank, and stable head-recall rules before running its automated decision. Paired metric intervals resample fixed OOF rows and do not refit models.
