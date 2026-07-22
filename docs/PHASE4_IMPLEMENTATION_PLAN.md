# Phase 4 Model-Decision Implementation Plan

## Objective and boundary

Phase 4 makes one reproducible production-default decision from the already frozen Phase 2 and Phase 3 evidence. The only allowed outcomes are:

```text
raw_xTB_wins
global_affine_wins
hierarchical_wins
insufficient_evidence
```

This phase does not refit B0, B1, or H1; retune penalties; add H2, size, electronic, or exact-combined-family features; score 401,856 candidates; select new calculations; run quantum chemistry; connect to HPC; or write to a server.

## Frozen inputs and integrity

The evaluator reads:

```text
data/processed/v001/
results/baselines_v001/
results/hierarchical_v001/
docs/PROCESSED_V001_MANIFEST.json
docs/BASELINES_V001_MANIFEST.json
docs/HIERARCHICAL_V001_MANIFEST.json
configs/evaluation.yaml
```

Before computing a decision it verifies every registered runtime hash, dataset/model versions, the common 71-key training hash, exact protocol/key alignment, OOF flags, Phase 2/3 gate status, and the H1 model/source-tree identities. A hash or alignment mismatch is a hard failure, not `insufficient_evidence`.

Phase 4 treats all prediction values, family effects, split definitions, and selected penalties as immutable. It may derive comparison statistics and confidence intervals but may not change an earlier result directory.

## Evidence already fixed

- B0 has the same deterministic raw-xTB ranking under each protocol.
- B1 improves absolute calibration but its Spearman and Kendall point estimates are below B0 under LOOCV, axis-A holdout, and axis-B holdout.
- H1 improves Spearman and Kendall relative to B1 under all three protocols.
- H1 improves LOOCV and axis-A MAE, while axis-B MAE worsens by `0.1288 kcal/mol`.
- H1 true-Top-10 recall in predicted Top-10 falls from `0.8` to `0.7` under both grouped protocols; true-Top-10 recall in predicted Top-20 stays `0.9`.
- H1 and B1 regret@10/20/50 are identical at zero in the registered point estimates.
- All unseen outer-held-out family effects are exactly zero and predictions remain finite.
- No exact-combined-family effect was fitted; size extrapolation and a genuine blind holdout are unavailable.
- Of 73 active axis effects, 72 bootstrap 95% intervals cross zero; raw sign stability has median `0.637`.

These observations constrain but do not themselves replace the registered decision algorithm.

## Paired OOF uncertainty

Phase 4 adds 2,000 deterministic paired bootstrap replicates with seed `20260722` using the frozen aligned OOF predictions. Each replicate resamples InChIKeys once and applies the same multiplicity to B0, B1, H1, and truth. Duplicate sampled keys receive deterministic replicate suffixes only for tie-breaking.

For every protocol and model pair, the evaluator records point delta, bootstrap mean, p2.5, p5, p50, p95, p97.5, and the probability that the configured gate is satisfied for:

- Spearman and Kendall;
- every registered true-Top-M/predicted-Top-K recall;
- regret@10/20/50;
- MAE and RMSE as secondary context.

The bootstrap quantifies uncertainty of the fixed OOF comparison. It does not refit models, retune H1, create candidate-level predictive intervals, or claim an unused blind test.

## Deterministic B1 gate

B1 may replace B0 only if all of the following hold:

1. at least one honest protocol has a positive point improvement in a primary rank metric;
2. every protocol satisfies configured Spearman and Kendall non-inferiority;
3. no registered regret exceeds B0 by more than the configured tolerance;
4. paired-bootstrap evidence does not show that the claimed improvement is dominated by instability;
5. all required hashes and OOF rows reproduce.

If B1 fails, it remains available for absolute electronic-energy calibration but cannot become the default ranking model.

## Deterministic H1 gate

H1 may replace B1 only if all of the following hold:

1. grouped axis-A and axis-B Spearman deltas meet `min_spearman_delta`;
2. grouped axis-A and axis-B Kendall deltas meet `min_kendall_delta`;
3. at least one registered head-recall delta is positive and its paired-bootstrap 95% interval demonstrates the configured stability rule;
4. every regret delta is at most `max_regret_increase_kcal`;
5. all held-out-family contributions are exactly zero and predictions are finite;
6. the confirmed no-family-collapse rule passes;
7. the confirmed family-offset stability rule passes;
8. exact combined-family overfit is absent by construction;
9. missing blind and size protocols remain explicit and are never converted to passes;
10. all required artifacts reproduce.

Passing H1-vs-B1 is necessary but not sufficient for production use: H1 must also show an honest primary-ranking improvement over B0. No complexity bonus is granted.

## Operational policy — confirmed

The task specification requires “no catastrophic family error” and family offsets that do not completely flip, but provides no numerical definitions. The user confirmed this conservative operational registration before the automated Phase 4 decision was run:

```yaml
promotion:
  primary_rank:
    min_delta: 0.0
    require_95_percent_lower_bound_nonnegative: true
  family_collapse:
    max_heldout_mae_increase_kcal: 3.0
    max_heldout_mae_ratio: 2.0
    catastrophic_requires_both: true
  family_offset_stability:
    minimum_support: 3
    min_conditional_sign_stability: 0.60
  head_recall:
    min_delta: 0.0
    require_95_percent_lower_bound_nonnegative: true
```

A held-out family is catastrophic only when H1 exceeds B1 by more than `3.0 kcal/mol` **and** more than `2×`. Conditional sign stability is `max(P(effect>0), P(effect<0)) / P(level present)` so absent singleton levels do not count as sign flips. The stability threshold applies only to levels with at least three original labels. Head recall still requires a strictly positive point delta; a non-negative 95% lower bound prevents an isolated point improvement from being called stable.

The current audit indicates that these rules are scientifically consequential: axis-B `Br|CF3` has one held-out label, B1 MAE `1.0269`, and H1 MAE `4.7791`; several support-3-or-more offsets also have weak conditional sign stability. These thresholds are now frozen and must not be adjusted after the automated Phase 4 decision.

## Outcome selection

After evaluating every gate:

- `hierarchical_wins` if H1 passes all H1 gates and beats B0 honestly;
- otherwise `global_affine_wins` if B1 passes all B1 gates;
- otherwise `raw_xTB_wins` if the evidence is complete enough to reject promotion and B0 remains the valid default;
- `insufficient_evidence` only when required evidence is genuinely unavailable or statistically indeterminate, not when a candidate model clearly fails a registered gate.

The decision report records both `outcome` and `production_default`. A more complex model failing promotion does not delete it; B1 may remain the absolute-calibration model while B0 remains the ranking default.

## Implementation and CLI

`validation/promotion.py` will contain pure, typed decision and paired-bootstrap functions. A Phase 4 runner will verify inputs and atomically create an immutable result. The CLI entry point is:

```bash
nhc-deprot evaluate \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --hierarchical-results results/hierarchical_v001 \
  --evaluation-config configs/evaluation.yaml \
  --out results/decision_v001 \
  --dry-run
```

Removing `--dry-run` is allowed only after the policy above is confirmed and synthetic promotion tests pass.

## Output layout

```text
results/decision_v001/
├── promotion_decision.json
├── model_comparison.json
├── metric_uncertainty.parquet
├── family_collapse_audit.csv
├── family_stability_audit.csv
├── input_manifest.json
├── decision_manifest.json
├── phase4_gate.json
├── figures/
│   ├── 01_primary_metric_deltas.png
│   ├── 02_head_recall_deltas.png
│   ├── 03_family_collapse_audit.png
│   └── 04_family_stability_audit.png
└── _SUCCESS
```

The directory is assembled beside the target and atomically renamed. Existing versions are never overwritten. The checked-in `MODEL_CARD.md`, Phase 4 report, test report, and compact evidence manifest will describe the ignored runtime result.

## Tests before real evaluation

- each of the four allowed outcomes is reachable on synthetic evidence;
- B1 cannot promote without a positive honest primary-ranking improvement;
- Spearman/Kendall non-inferiority thresholds are read from YAML;
- stable head-recall improvement requires both point and interval rules;
- regret tolerance is applied in the correct lower-is-better direction;
- unknown-family zero/finiteness failure blocks H1;
- catastrophic family error uses the confirmed absolute/ratio conjunction;
- offset stability uses conditional sign probability and the minimum-support filter;
- missing blind/size protocols remain explicit and cannot silently pass;
- paired bootstrap is deterministic and keeps truth/model rows aligned;
- duplicate bootstrap keys receive deterministic tie-break identities;
- evidence/hash/key mismatches hard-fail;
- dry-run is non-writing, failed temporary results are cleaned, and existing decisions are immutable.

## Phase 4 acceptance gate

Phase 4 passes only when the policy is confirmed, all synthetic tests and engineering gates pass, the real decision is produced from frozen evidence, every input/output/source hash matches independent readback, `MODEL_CARD.md` records the selected default and limitations, and no Phase 5 or prohibited computation has occurred.

Passing Phase 4 permits a separate Phase 5 proposal. It does not score the full candidate pool automatically.
