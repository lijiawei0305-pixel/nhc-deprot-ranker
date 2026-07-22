# Phase 3 Hierarchical Implementation Plan

## Objective and boundary

Phase 3 implements H1, an additive partially pooled calibration:

```text
y = beta_0 + rho*xTB
    + u_skeleton[skeleton]
    + u_axis_a[axis_a_family]
    + u_axis_b[axis_b_family]
```

The deliverable includes a penalized linear solver, sklearn-style estimator, leakage-safe nested CV, family effects, fixed-penalty bootstrap uncertainty, unknown-family fallback, serialization, manifests, metrics, and audited figures.

Phase 3 does not add size or electronic descriptors, exact combined-family effects, H2, full-pool scoring, acquisition, Phase 4 promotion, quantum chemistry, or HPC writes.

## Inputs and integrity

The runner reads only immutable local results already produced and hashed:

```text
data/processed/v001/
results/baselines_v001/
docs/PROCESSED_V001_MANIFEST.json
docs/BASELINES_V001_MANIFEST.json
configs/model.yaml
configs/evaluation.yaml
```

Before fitting it verifies the Phase 1 and Phase 2 evidence hashes, dataset/model versions, the shared 71-key training-set hash, and the B0/B1 outer split definitions. H1 uses exactly the same endpoint-revalidated target and outer test rows as B1.

All 71 labels share one protocol, successful endpoint status, and `electronic_energy_only` quality, so Phase 3 uses uniform observation weights. Source group is provenance only and is never a feature or weight.

## Audited family support

| Term | Levels | Singletons | Maximum support |
| --- | ---: | ---: | ---: |
| skeleton | 1 | 0 | 71 |
| axis-A | 38 | 22 | 10 |
| axis-B | 35 | 16 | 5 |
| exact combined | 71 | 71 | 1 |

Axis effects are therefore strongly underdetermined without shrinkage. Exact combined-family effects remain disabled. The single skeleton level requires the explicit decision below.

## Single-skeleton decision — resolved

`skeleton=imidazolium` for all 71 rows, so a skeleton offset is not empirically separable from the intercept. The user approved this Phase 3 behavior:

- keep the skeleton term in the estimator interface for future datasets;
- mark it `inactive_single_level` for v001;
- fix its current effect to exactly zero rather than report a spurious estimated coefficient;
- make an unseen future skeleton fall back to zero, like every unknown family.

This is a versioned identifiability rule, not evidence that the true skeleton contribution is physically zero.

## Estimator and design matrix

`HierarchicalLinearCalibrator` exposes:

```text
fit(X, y)
predict(X)
predict_components(X)
get_coefficients()
save(path)
load(path)
```

Each fit performs the following using training rows only:

1. reject missing, non-finite, duplicate-key, blank-family, or length-mismatched input;
2. store sorted training vocabularies independently for skeleton, axis-A, and axis-B;
3. center and scale xTB using the training mean and population standard deviation;
4. construct `[intercept, standardized_xTB, active one-hot family columns]`;
5. use `handle_unknown=ignore` semantics so unseen levels contribute exactly zero;
6. store means, scales, vocabularies, training ranges, penalties, design rank, condition number, solver path, and training-key hash.

`predict_components` returns global intercept, global slope contribution, each family contribution, final prediction, and known/unknown flags. Reported `beta_0` and `rho` are converted back to the original xTB units.

## Penalized solver

For uniform Phase 3 weights, solve:

```text
(X.T X + P) theta = X.T y + P theta_prior
```

The intercept penalty is zero. The standardized slope uses configured `lambda_slope` and `rho_prior`; current defaults retain `lambda_slope=0`. Active family columns receive their term-specific lambdas.

The solver:

- checks finite matrices and non-negative penalties;
- records unpenalized and penalized rank plus condition number;
- uses a direct symmetric solve only below the configured conditioning threshold;
- otherwise uses a Moore–Penrose pseudoinverse and records the fallback;
- rejects non-finite coefficients and predictions;
- never silently adds jitter or changes a configured lambda.

## Finite regularization search

Inner selection minimizes concatenated inner-OOF RMSE. R² and outer ranking metrics never tune penalties.

Search is deterministic and finite:

1. coarse stage: the five configured shared-family lambdas, applied equally to axis-A and axis-B;
2. refinement stage: at most the nearest three configured axis-A values crossed with the nearest three axis-B values around the coarse winner, for at most nine candidates;
3. deterministic tie break: lower RMSE, then stronger total shrinkage, then lexical parameter order.

The full 5×5×5 Cartesian grid is never run. Every evaluated candidate, fold score, selected penalty, failure, and tie break is written to `nested_search.json`.

## Nested validation

Outer folds are evaluation-only. Every outer fold rebuilds xTB scaling, category vocabulary, design matrix, and penalty choice from its training rows.

### Outer LOOCV

- 71 outer folds, one InChIKey held out each time.
- Inner selection uses a deterministic five-fold InChIKey partition created from SHA256(key, seed), with each key appearing once as inner validation.

### Outer axis-A holdout

- 38 outer folds using the exact Phase 2 axis-A test groups.
- Inner selection uses a deterministic five-fold group-disjoint partition of the remaining axis-A families. Whole families stay within one fold, and a support-balanced greedy assignment with SHA256 tie-breaking prevents arbitrary row-order effects.
- The outer held-out axis-A category must be absent from the fitted vocabulary and contribute zero.

### Outer axis-B holdout

- 35 outer folds using the exact Phase 2 axis-B test groups.
- Inner selection uses the corresponding deterministic five-fold group-disjoint partition of the remaining axis-B families.
- The outer held-out axis-B category must be absent from the fitted vocabulary and contribute zero.

Combined-family, size, and blind protocols retain the honest unavailable states established in Phase 2. They are not replaced with proxies.

After outer evaluation, a final penalty is selected on all 71 rows using the registered deterministic five-fold inner protocol, then H1 is fitted once for serialization and bootstrap queries. This final fit is never presented as OOF performance.

## CLI

The existing `train` command dispatches from the typed model configuration. Phase 3 uses:

```bash
nhc-deprot train \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --model-config configs/model.yaml \
  --evaluation-config configs/evaluation.yaml \
  --out results/hierarchical_v001 \
  --dry-run
```

Removing `--dry-run` is allowed only after synthetic and leakage tests pass. Existing result versions cannot be overwritten.

## Bootstrap uncertainty

The final Phase 3 report uses 2,000 paired InChIKey resamples with seed `20260722`. Per `fixed_from_nested_cv`, the final selected penalties are held fixed; they are not retuned inside bootstrap replicates.

Each successful replicate refits scaling, vocabularies, and coefficients, then predicts the 71 labeled query rows. Outputs include:

- prediction mean, standard deviation, p05, p50, and p95;
- probability of entering each configured Top-K among the 71 labeled queries;
- family-effect distributions and sign stability;
- requested/successful/failed replicate counts.

These full-fit bootstrap intervals quantify model/label resampling uncertainty. They are not OOF performance and are not full-pool candidate uncertainty; the latter remains Phase 5 work.

## Output layout

```text
results/hierarchical_v001/
├── model.pkl
├── model_manifest.json
├── coefficients.json
├── family_effects.csv
├── nested_search.json
├── bootstrap_metadata.json
├── bootstrap_summary.parquet
├── bootstrap_family_effects.parquet
├── oof_predictions.csv
├── split_manifest.json
├── metrics.json
├── rank_shift_audit.csv
├── promotion_decision.json
├── phase3_gate.json
├── figures/
└── _SUCCESS
```

The directory is assembled in a sibling temporary directory and atomically renamed after all gates and hashes pass. Existing versions are immutable. `promotion_decision.json` remains `deferred_to_phase4` while recording provisional H1-vs-B1 evidence.

## Applicable figures

Phase 3 produces H1-vs-B1 OOF rank/metric comparisons, grouped performance, family-effect forest plots, family support versus shrinkage, bootstrap prediction intervals, and family sign stability. Every plot states n, split, dataset/model version, OOF status, and interval definition. Full-pool rank shifts remain out of scope.

## Test gate before real fitting

- recover known intercept, slope, and additive family offsets on synthetic data;
- show rarer family effects shrink more strongly than high-support effects;
- show family effects approach zero as lambda increases;
- match identifiable one-hot OLS when lambda is zero;
- return finite global fallback for unseen skeleton/axis levels;
- preserve predictions exactly after save/load;
- reproduce bootstrap arrays for the same seed;
- survive rank-deficient designs through a recorded pseudoinverse;
- reject NaN, duplicate keys, blank family, invalid penalty, and zero xTB scale;
- prove outer/inner key disjointness, held-out-family exclusion, train-only scaling/vocabulary, and one OOF prediction per key;
- prove no outer metric or row influences penalty selection;
- clean failed temporary builds and reject existing results.

## Phase 3 acceptance gate

Phase 3 passes only when:

- all synthetic partial-pooling, fallback, serialization, numerical, and leakage tests pass;
- LOOCV, axis-A, and axis-B nested OOF predictions each cover 71/71 keys;
- all outer folds record finite selected penalties and predictions;
- unseen held-out family contributions are exactly zero;
- H1 metrics are compared with B1 on identical keys/folds without making a Phase 4 promotion;
- 2,000 bootstrap attempts and failures are fully reported;
- family effects and their stability are auditable, with no exact-combined effect;
- input/config/source-tree/output hashes and `_SUCCESS` all match independent readback;
- pytest, Ruff, mypy, pre-commit, wheel, CLI, and private-path gates pass.

Passing Phase 3 permits a Phase 4 proposal; it does not start model promotion automatically.
