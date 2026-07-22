# Phase 2 Baseline Report

## Outcome

Phase 2 passed on 2026-07-22. The local immutable result `results/baselines_v001` contains B0 raw xTB and B1 free-slope global affine models, exact LOOCV predictions, axis-A/axis-B family holdouts, ranking metrics, 2,000 paired bootstrap fits, split manifests, model serialization, and nine audited figures.

The large runtime result remains ignored. Exact input/output hashes and selected evidence are checked in as `BASELINES_V001_MANIFEST.json`.

## Full B1 fit

Using all 71 endpoint-revalidated labels:

```text
y_DFT = 196.1773139188 + 0.7157116718 * xTB
```

| Quantity | Result |
| --- | ---: |
| Intercept analytic SE | 2.43449 |
| Slope analytic SE | 0.026729 |
| Design rank | 2 |
| Condition number | 540.63 |
| Pseudoinverse fallback | No |
| Training xTB range | 57.3482–116.1717 kcal/mol |

The 2,000-repeat paired InChIKey bootstrap had zero failed fits. Its 95% percentile intervals are `191.1444–201.0057` for the intercept and `0.66608–0.76915` for the slope. The slope interval remains well below 1, supporting the requirement that B1 must learn a free slope.

## Historical reproduction

All eight registered comparisons passed. The B1 LOOCV results are:

| Metric | Phase 2 | Historical audit |
| --- | ---: | ---: |
| MAE (kcal/mol) | 2.721585 | 2.7214 |
| RMSE (kcal/mol) | 3.509913 | 3.5098 |
| Spearman | 0.9570758 | 0.957076 |
| Kendall | 0.8213280 | 0.821328 |

The full-fit intercept differs from the historical value by `0.001125` and the slope by `0.00001067`. This is expected because the historical fit used stored rounded targets, while v001 fits endpoint-recomputed targets. The separate pre-registered tolerances (`0.002` intercept, `0.00002` slope) both pass.

## Honest ranking comparison

| Protocol / model | MAE | RMSE | Spearman | Kendall | Pairwise accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| LOOCV B0 | 170.6541 | 170.7439 | 0.958954 | 0.825352 | 0.931559 |
| LOOCV B1 | 2.7216 | 3.5099 | 0.957076 | 0.821328 | 0.929447 |
| Axis-A holdout B1 | 2.7378 | 3.5248 | 0.957378 | 0.822133 | 0.929869 |
| Axis-B holdout B1 | 2.7875 | 3.5763 | 0.954460 | 0.814085 | 0.926067 |

B0 is intentionally an uncalibrated ranking baseline, so its roughly `170 kcal/mol` absolute offset is not a meaningful calibration claim. B1 corrects the absolute scale, but honest fold-specific predictions slightly reduce the main ranking correlations. Both models find the same registered head sets for most M/K combinations; for example, true Top-10 recall within predicted Top-20 is `0.9` for both. Regret@10/20/50 is zero for both on these 71 labels.

The Phase 2 conclusion is therefore limited: global affine calibration is valid and useful for absolute electronic-energy prediction, but it has not demonstrated a ranking improvement over B0. B0 remains the production ranking baseline. `promotion_decision.json` correctly defers B0/B1/H1 selection to Phase 4.

## Protocol availability

- LOOCV: complete, 71/71 unique OOF keys.
- Axis-A holdout: complete, 38 folds and 71/71 OOF keys.
- Axis-B holdout: complete, 35 folds and 71/71 OOF keys.
- Combined-family holdout: `unavailable_redundant_singletons` because all 71 exact groups are singletons and the result would duplicate LOOCV.
- Size extrapolation: `unavailable_missing_validated_size`; the approved Phase 2 scope does not invent a proxy.
- Blind holdout: `blind_test_missing`; the historical blind rounds have been revealed.

No grouped protocol is described as a new blind test.

## Independent verification

A separate readback recomputed every manifest hash, loaded `model.pkl`, checked finite B0/B1 predictions, verified 213 OOF rows and 71 rank-audit rows, and walked every fold to require disjoint train/test keys, complete 71-key coverage, and exactly one test appearance per protocol. It also confirmed the exact Python source-tree hash, 2,000 successful bootstrap fits, all unavailable-protocol statuses, nine readable figures, and absence of private absolute paths. All assertions passed.

## Gate decision

Phase 2 is complete. Phase 3 may be proposed only after this branch is reviewed and the user separately authorizes H1 partial pooling.
