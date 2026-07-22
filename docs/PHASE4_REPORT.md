# Phase 4 Model Decision Report

## Outcome

Phase 4 passed on 2026-07-22 with outcome `raw_xTB_wins`. The production ranking default remains B0 raw xTB. B1 remains the companion model for DFT-scale absolute electronic-energy calibration; H1 is retained as a non-production research candidate.

The immutable local result is `results/decision_v001`. It contains frozen B0/B1/H1 comparisons, 2,000 paired OOF bootstrap replicates per protocol, two family audits, four decision figures, complete input/output hashes, and the explicit gate record. The large runtime result remains ignored; selected evidence is checked in as `DECISION_V001_MANIFEST.json`.

No B0/B1/H1 model was refit, no H1 penalty was retuned, and no full-pool candidate was scored.

## B1 decision

B1 passes the provisional non-inferiority thresholds but fails the required positive primary-ranking improvement.

| Protocol | Spearman Δ B1−B0 | 95% interval | Kendall Δ B1−B0 | 95% interval |
| --- | ---: | ---: | ---: | ---: |
| LOOCV | -0.001878 | [-0.006910, 0.000000] | -0.004024 | [-0.012072, 0.000000] |
| Axis-A | -0.001576 | [-0.006808, 0.000772] | -0.003219 | [-0.011268, 0.002414] |
| Axis-B | -0.004494 | [-0.011067, -0.000905] | -0.011268 | [-0.023340, -0.002414] |

All registered regret deltas are zero. B1 is useful for absolute calibration—LOOCV MAE `2.7216 kcal/mol` versus the intentionally uncalibrated B0 offset—but it does not replace B0 for ranking.

## H1 decision

H1 passes grouped rank non-inferiority and improves point rank correlations versus B1:

| Protocol | Spearman Δ H1−B1 | 95% interval | Kendall Δ H1−B1 | 95% interval |
| --- | ---: | ---: | ---: | ---: |
| LOOCV | +0.015895 | [+0.000134, +0.037695] | +0.037827 | [-0.004829, +0.078873] |
| Axis-A | +0.008015 | [-0.005202, +0.021801] | +0.024950 | [-0.011268, +0.057143] |
| Axis-B | +0.007948 | [-0.002282, +0.022974] | +0.018511 | [-0.008853, +0.049115] |

It nevertheless fails four required gates:

1. Stable head recall: the only positive point delta is LOOCV true-Top-20 recall within predicted Top-20, `+0.05`, but its interval is `[-0.05, +0.20]`.
2. Stable improvement over B0: every H1-minus-B0 primary interval crosses zero; LOOCV Spearman is `+0.014017`, interval `[-0.001242, +0.034039]`.
3. No catastrophic family error: held-out axis-B `Br|CF3` has B1 MAE `1.0269`, H1 MAE `4.7791`, increase `3.7522 kcal/mol`, ratio `4.654×`, exceeding both confirmed thresholds.
4. Supported offset stability: axis-B `Me|NO2`, support 3, has conditional sign stability `0.5331`, below `0.60`.

H1 passes the zero-effect unknown-family fallback, finite prediction, grouped Spearman/Kendall, regret, exact-combined-effect absence, and artifact-reproduction gates. Axis-B aggregate MAE also worsens from `2.7875` to `2.9163 kcal/mol`, reinforcing the conservative non-promotion decision.

## Bootstrap and protocol scope

- unit: paired InChIKey resampling of fixed aligned OOF rows;
- repeats: 2,000 per protocol, 6,000 total successful protocol replicates;
- failures: zero;
- seed: `20260722`;
- confidence: 95%;
- model refitting: no;
- penalty retuning: no.

LOOCV, axis-A, and axis-B each contain exactly 71 unique OOF keys. Size extrapolation remains `unavailable_missing_validated_size`, and blind evaluation remains `blind_test_missing`; neither is misreported as a pass.

## Independent verification

A separate readback matched 55 registered input hashes, 11 pre-manifest output hashes, the decision manifest, `_SUCCESS`, the current 50-file Python source tree, all 180 uncertainty rows, 6,000 successful bootstrap protocol replicates, the single catastrophic family, and the single unstable supported offset. It also confirmed the absence of private paths and fake-IP values in the runtime result.

All four figures were inspected. They expose B1's non-improvement, H1 interval overlap, the `Br|CF3` collapse, and the `Me|NO2` stability failure rather than hiding negative evidence.

## Gate decision

Phase 4 is complete and reproducible. The selected production ranking default is B0 raw xTB; B1 is the absolute-calibration companion; H1 is not promoted. Phase 5 remains unstarted and requires separate user authorization before scoring the 401,856 candidates.
