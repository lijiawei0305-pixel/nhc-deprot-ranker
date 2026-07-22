# Phase 2 Baseline Implementation Plan

## Objective and boundary

Phase 2 implements and honestly evaluates only:

- B0: raw `xtb_deprot_kcal` prediction;
- B1: `beta_0 + rho * xtb_deprot_kcal`, with free intercept and free slope;
- exact LOOCV and leave-one-axis-family-out validation;
- lower-is-better absolute and ranking metrics;
- reproducible B1 coefficient uncertainty and versioned evidence outputs.

Phase 2 does not implement H1/H2, tune family penalties, score the 401,856-row pool with a production model, select acquisition candidates, run quantum chemistry, or write to HPC. Phase 2 metrics are baseline evidence, not the final B0/B1/H1 promotion decision reserved for Phase 4.

## Inputs and integrity checks

The only scientific data inputs are the ignored Phase 1 outputs:

```text
data/processed/v001/candidates.parquet
data/processed/v001/labels.parquet
data/processed/v001/source_manifest.json
data/processed/v001/protocol_manifest.json
data/processed/v001/data_quality.json
data/processed/v001/_SUCCESS
```

The runner must verify the checked-in `docs/PROCESSED_V001_MANIFEST.json` row counts and hashes before fitting. Candidate and label tables are joined one-to-one by unique InChIKey, and all 71 labels must match candidates. No source-group field may be used as a feature.

Required columns are `inchikey`, `xtb_deprot_kcal`, `dft_deprot_electronic_kcal`, `axis_a_family`, `axis_b_family`, and `combined_family`. Every model input must be finite. The target remains an electronic energy with `lower_is_better=true`.

## Estimators

### B0 raw xTB

B0 has no learned parameters and returns the xTB value unchanged. Its metadata records the input column, target definition, applicable observed xTB range, sample count, and lower-is-better direction.

### B1 global affine

B1 fits ordinary least squares with an unpenalized intercept and freely learned slope. It records:

- `beta_0`, `rho`, residual variance, coefficient standard errors, matrix rank, and condition number;
- training sample count and xTB range;
- whether least squares required a pseudoinverse fallback;
- the exact training InChIKey hash.

The implementation rejects fewer than three unique finite training rows and zero xTB variance. The full-data result is compared with the audited historical values `beta_0=196.178439` and `rho=0.715701`; a mismatch must be explained rather than silently accepted. The historical fit used stored source targets, while v001 uses endpoint-recomputed targets whose source-rounding differences reach about `0.00025 kcal/mol`. The pre-registered reproduction tolerances are therefore separate: `0.002` for the intercept and `0.00002` for the slope.

Coefficient uncertainty uses a deterministic paired InChIKey bootstrap. Development runs use 200 repeats and the final Phase 2 report uses the configured 2,000 repeats with seed `20260722`. Each bootstrap refits B1; failed degenerate resamples are counted and reported, never silently replaced.

## Validation protocols

### LOOCV

Each of the 71 labels is held out exactly once. B1 is refit on the remaining 70 rows; B0 remains the raw held-out xTB value. The output contains one OOF row per InChIKey and fold-local B1 coefficients.

LOOCV must reproduce or explain the audited B1 values: MAE about `2.7214`, RMSE about `3.5098`, Spearman about `0.957076`, and Kendall about `0.821328`.

### Axis-A and axis-B holdout

Use deterministic leave-one-group-out splits for `axis_a_family` and `axis_b_family`. Each fold records train/test InChIKeys and held-out family. Assertions require no key overlap and no held-out family in training. Metrics are computed once over the concatenated OOF predictions for each protocol, plus per-held-out-family absolute-error summaries.

Although B1 has no family features, these protocols still measure chemical-family extrapolation of the global relation. They must not be described as blind tests.

### Combined-family holdout

The 71 current labels have 71 exact combined-family singletons. Combined-family holdout is therefore identical to LOOCV and provides no distinct group-generalization evidence. Phase 2 reports it as `unavailable_redundant_singletons` instead of presenting a duplicate result as independent validation.

### Blind holdout

The historical 12- and 35-row blind rounds have been revealed. The result is `blind_test_missing`; all 71 labels may be used for historical-reproduction CV, but none is described as a new blind test.

### Size extrapolation — resolved decision

Both optional Phase 1 size columns are intentionally null because no validated size routine was used. The user approved reporting `size_extrapolation_unavailable` and keeping Phase 2 limited to existing verified fields. A future size protocol requires a tested chemistry-aware derivation plus a new immutable dataset version.

No row order, SMILES string length, xTB energy, fragment count, or other proxy may be mislabeled as molecular size.

## Metric definitions

All ranking ties use deterministic InChIKey tie-breaking, and all functions take `lower_is_better=true` explicitly.

- MAE and RMSE: ordinary OOF absolute-energy errors.
- Spearman rho and Kendall tau: correlation between true and predicted lower-is-better ranks.
- Pairwise accuracy: fraction of correctly ordered pairs after excluding true-energy separations at or below the configured `1.0 kcal/mol` threshold.
- Recall `(M, K)`: `|TrueTopM ∩ PredTopK| / M`.
- Precision `(M, K)`: `|TrueTopM ∩ PredTopK| / K`.
- NDCG@K: true-rank relevance `n + 1 - true_rank`, linearly discounted by `log2(position + 1)`, normalized by ideal DCG.
- Enrichment `(M, K)`: precision divided by the random prevalence `M/n`.
- Regret@K: minimum true energy among predicted Top-K minus the global minimum true energy.
- Rank-shift audit: xTB, B1 OOF, and true ranks/errors plus residual and family fields for every label.

Metric functions reject non-finite arrays, length/key mismatches, invalid K/M, and unsupported direction. Tests cover perfect/reversed order, tie filtering, M unequal to K, and deterministic ties.

## Output layout

The proposed immutable result is:

```text
results/baselines_v001/
├── model.pkl
├── model_manifest.json
├── coefficients.json
├── bootstrap_summary.json
├── bootstrap_summary.parquet
├── family_effects.csv
├── oof_predictions.csv
├── split_manifest.json
├── metrics.json
├── rank_shift_audit.csv
├── promotion_decision.json
├── figures/
├── phase2_gate.json
└── _SUCCESS
```

The directory uses the same sibling-temporary-directory and atomic-rename policy as Phase 1. Existing results are never overwritten; changed inputs or logic require a new version. Every manifest records dataset/model versions, input and output SHA256 values, seed, package versions, and whether predictions are OOF. `family_effects.csv` explicitly records `not_applicable_phase2_baselines`; `promotion_decision.json` records that final B0/B1/H1 selection is deferred to Phase 4.

Phase 2 generates the applicable baseline figures: xTB-vs-DFT scatter, full affine line, affine OOF residuals, true-vs-xTB rank, true-vs-affine OOF rank, Top-M recall, NDCG, regret, and grouped-CV performance. Each figure states sample count, protocol, model/dataset version, OOF status, and CI definition. H1-only family-effect and per-candidate uncertainty plots are explicitly not applicable.

## CLI

The Phase 2 command will be:

```bash
nhc-deprot train \
  --dataset data/processed/v001 \
  --model-config configs/baselines.yaml \
  --evaluation-config configs/evaluation.yaml \
  --out results/baselines_v001 \
  --dry-run
```

Removing `--dry-run` runs only after the plan and size decision are confirmed. The existing common `--seed`, `--log-level`, and `--overwrite` options remain; `--overwrite` cannot replace an immutable result version.

## Test gate before real fitting

- B0 identity prediction and serialization metadata;
- B1 known-coefficient recovery, free slope, analytic uncertainty, degenerate-input rejection, and deterministic bootstrap;
- exact LOOCV one-row-per-key and train-only fitting;
- axis group holdout with no key/family leakage;
- perfect/reversed ranking, NDCG, Top-M/K, enrichment, regret, and tie-threshold fixtures;
- input manifest/hash failures and non-finite rejection;
- dry-run non-writing, atomic failure cleanup, and immutable-output rejection;
- historical coefficient/LOOCV reproduction on real v001 only after all synthetic tests pass.

## Phase 2 acceptance gate

Phase 2 passes only when:

- B0 and B1 are both implemented and tested;
- 71/71 LOOCV OOF predictions exist with correct direction;
- full-fit and LOOCV results reproduce or explicitly explain the legacy audit;
- axis-A and axis-B OOF predictions cover 71/71 keys without leakage;
- all required ranking metrics and rank-shift rows are finite and reproducible;
- bootstrap coefficient uncertainty is deterministic and reports failures;
- missing blind and size protocols are honestly recorded;
- pytest, Ruff, mypy, pre-commit, wheel, CLI, hash, and private-path gates pass.

Passing Phase 2 permits a Phase 3 proposal; it does not start H1 automatically.
