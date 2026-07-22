# Phase 3 Hierarchical Model Report

## Outcome

Phase 3 passed on 2026-07-22. The local immutable result `results/hierarchical_v001` contains H1 nested out-of-fold predictions, finite penalty searches, family effects, 2,000 fixed-penalty paired bootstrap fits, exact split manifests, model serialization, and nine audited figures.

The large runtime result remains ignored. Exact input/output hashes and selected evidence are checked in as `HIERARCHICAL_V001_MANIFEST.json`. `promotion_decision.json` remains `deferred_to_phase4`; Phase 3 does not promote a production model.

## Final H1 fit

Using all 71 endpoint-revalidated labels, the fitted global calibration is:

```text
y_DFT = 199.9839679255 + 0.6711162925 * xTB
        + u_axis_a + u_axis_b
```

| Quantity | Result |
| --- | ---: |
| Selected axis-A penalty | 0.1 |
| Selected axis-B penalty | 0.1 |
| Skeleton penalty/effect | 0.0 / 0.0 |
| Skeleton status | `inactive_single_level` |
| Design rows / columns / rank | 71 / 75 / 64 |
| Penalized rank | 75 |
| Penalized condition number | 816.32 |
| Solver | Direct symmetric solve; no pseudoinverse |
| Training xTB range | 57.3482–116.1717 kcal/mol |

The 38 axis-A effects span `-7.6019` to `4.5559` kcal/mol and the 35 axis-B effects span `-5.0184` to `5.7538`. Unknown families and outer-held-out families contribute exactly zero. The single skeleton coefficient is fixed to zero because it is inseparable from the intercept, not because a physical skeleton effect has been disproved.

## Honest H1 versus B1 evidence

H1 and B1 use identical outer test rows and keys.

| Protocol / model | MAE | RMSE | Spearman | Kendall | Pairwise accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| LOOCV B1 | 2.7216 | 3.5099 | 0.957076 | 0.821328 | 0.929447 |
| LOOCV H1 | 2.2373 | 2.8147 | 0.972971 | 0.859155 | 0.947191 |
| Axis-A B1 | 2.7378 | 3.5248 | 0.957378 | 0.822133 | 0.929869 |
| Axis-A H1 | 2.5515 | 3.2564 | 0.965392 | 0.847082 | 0.940431 |
| Axis-B B1 | 2.7875 | 3.5763 | 0.954460 | 0.814085 | 0.926067 |
| Axis-B H1 | 2.9163 | 3.5541 | 0.962408 | 0.832596 | 0.934939 |

H1 improves LOOCV and Axis-A aggregate error and improves Spearman/Kendall under all three protocols. Axis-B MAE nevertheless worsens by `0.1288 kcal/mol`. True Top-10 recall in predicted Top-10 falls from `0.8` to `0.7` in both family-holdout protocols, although true Top-10 recall in predicted Top-20 remains `0.9` and regret@10/20/50 remains zero.

The worst H1 held-out-family MAE is `10.1149` for axis-A `Ethynyl|Ethynyl` (B1 `11.0952`) and `6.3874` for axis-B `CN|H` (B1 `8.2043`). Some smaller groups regress materially, so aggregate improvement is not treated as proof against family collapse; that decision belongs to Phase 4.

## Nested selection and uncertainty

Outer folds select penalties using only their training rows. The search evaluates five shared coarse values followed by at most a local 3×3 axis refinement, optimizing concatenated inner-OOF RMSE with deterministic stronger-shrinkage tie-breaking. The final all-label inner search selected `lambda_axis_a=lambda_axis_b=0.1`.

The final uncertainty run requested 2,000 paired InChIKey resamples and completed all 2,000 with no failures. Penalties remain fixed while scaling, vocabularies, and coefficients are refitted. The prediction intervals and Top-K probabilities apply only to the 71 labeled full-fit query rows; they are neither OOF intervals nor full-pool candidate uncertainty.

Individual family effects remain weakly identified. Among 73 active axis effects, sign stability ranges from `0.3845` to `0.9795` with median `0.637`; 72 of 73 percentile 95% intervals cross zero. Singleton levels are absent from many resamples, which correctly yields zero fallback contributions and lowers their present fraction/sign stability. Family-effect interpretation must therefore remain cautious.

## Protocol and leakage audit

- LOOCV: 71/71 unique OOF keys, with nested five-fold key CV.
- Axis-A holdout: 38 outer folds and 71/71 OOF keys; inner folds keep whole remaining axis-A families disjoint.
- Axis-B holdout: 35 outer folds and 71/71 OOF keys; inner folds keep whole remaining axis-B families disjoint.
- Combined-family holdout: unchanged as `unavailable_redundant_singletons`.
- Size extrapolation: unchanged as `unavailable_missing_validated_size`.
- Blind holdout: unchanged as `blind_test_missing`.

Independent readback verified disjoint splits, complete coverage, train-only category vocabularies/scaling, zero held-out-axis effects, the zero skeleton effect, exact model save/load predictions, every recorded output hash, source-tree identity, readable plots, and no private paths.

## Gate decision

Phase 3 is complete. It establishes a reproducible H1 candidate and honest evidence, but not a production-model choice. Phase 4 may be proposed only after this branch is reviewed and the user separately authorizes the promotion analysis. No H2, full-pool scoring, quantum-chemistry calculation, HPC connection, or server write was performed.
