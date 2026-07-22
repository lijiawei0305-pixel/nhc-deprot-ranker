# Validation Report

## Phase 0 status

No new model was trained or evaluated. This report records historical evidence needed to pre-specify later baselines; it is not a Phase 4 promotion decision.

## Historical n=71 evidence

| Quantity | Result |
| --- | ---: |
| Raw xTB Spearman | 0.958954 |
| Raw xTB Kendall | 0.825352 |
| Full-data affine intercept | 196.178439 |
| Full-data affine slope | 0.715701 |
| Affine exact-LOO MAE | 2.7214 kcal/mol |
| Affine exact-LOO RMSE | 3.5098 kcal/mol |
| Affine R²_LOO | 0.90685 |
| Affine OOF Spearman | 0.957076 |
| Affine OOF Kendall | 0.821328 |

A positive single affine transformation preserves the full-data xTB ranking, so its main historical benefit is energy-scale calibration. Fold-specific OOF fits cause the small OOF ranking difference.

The historical size-extrapolation analysis reported raw/offset xTB ranking near Spearman 0.97 on 30 large molecules while offset-only MAE remained 5.629 kcal/mol. This supports the possibility that raw xTB is already sufficient for ranking, not a claim that it is universally sufficient.

## Blind status

Legacy 12- and 35-molecule holdouts were genuinely pre-registered when first run, but their labels have since been revealed and used in later analysis. They cannot be reused as a new-repository blind test. Current configuration therefore records `blind_test_missing` in substance.

## Decision

Model promotion: **not evaluated**. Phase 2 must recompute B0/B1 OOF results under the new metric suite; Phase 3 must evaluate H1 with nested grouped validation. Historical results cannot promote H1.
