# Phase 5 Full-Pool Scoring and Acquisition Plan

## Objective and boundary

Phase 5 applies the Phase 4 winner to all 401,856 immutable candidates, audits applicability, and proposes the next high-fidelity electronic-energy batch.

The production ordering is B0 raw xTB. B1 may supply a companion DFT-scale value and coefficient-bootstrap interval because Phase 4 explicitly retained it for absolute calibration. H1 is not used for formal ranking, uncertainty, family corrections, or acquisition scoring.

Phase 5 does not refit or retune a model, derive missing size with an unvalidated parser, run xTB/PySCF/Hessians, connect to HPC, copy a batch to the legacy project, or submit a job.

## Frozen inputs and integrity

```text
data/processed/v001/
results/baselines_v001/
results/decision_v001/
docs/PROCESSED_V001_MANIFEST.json
docs/BASELINES_V001_MANIFEST.json
docs/DECISION_V001_MANIFEST.json
configs/acquisition.yaml
```

Both `score` and `acquire` verify all registered hashes, versions, the 71-key label set, `raw_xTB_wins`, B0/B1 identities, and the full candidate row/key/rank contract before writing. A mismatch is a hard failure.

## Audited candidate support

| Quantity | Result |
| --- | ---: |
| Candidates / unique InChIKeys | 401,856 / 401,856 |
| Skeleton levels | 1 |
| Axis-A levels in pool / labels | 528 / 38 |
| Axis-B levels in pool / labels | 406 / 35 |
| Rows with both axes seen | 2,316 |
| Rows with neither axis seen | 343,028 |
| Rows with either seen family support 1–2 | 45,750 |
| Labeled xTB range | 57.3482–116.1717 kcal/mol |
| Pool rows outside labeled xTB range | 2,782 |
| Missing `n_heavy_atoms` / `n_electrons` | 401,856 / 401,856 |
| Labeled rows in raw Top-50 | 0 |
| Raw Top-50 below labeled xTB range | 50 |
| Raw Top-50 with both axes seen | 0 |

These facts require prominent applicability warnings even though B0 predictions are finite.

## Confirmed output policy

The task requires calibrated values, uncertainty, Top-K probabilities, rank shifts, and components, while Phase 4 selected uncalibrated B0. The recommended dual-track interpretation is:

- `production_score_kcal`, `production_rank`, and formal ordering come only from B0 `xtb_deprot_kcal`;
- `calibrated_dft_deprot_kcal` and interval fields come from the frozen full-fit B1 companion;
- `calibrated_rank` equals B0 because the full-fit B1 slope is positive;
- `rank_shift` is exactly zero and the acquisition conflict contribution is zero;
- `global_component` is the B1 companion value, while skeleton/axis components are exactly zero/not applicable;
- `prediction_std_kcal`, p05, and p95 quantify only B1 coefficient-resampling uncertainty, not residual or H1 predictive uncertainty;
- all 2,000 B1 bootstrap slopes must be positive before Top-10/50/100 probabilities are assigned deterministically from B0 rank.

The recommended acquisition batch contains 50 unlabeled unique candidates. `top_candidates.csv` contains the first 100 production-ranked rows for review. Quotas use largest-remainder rounding in YAML order:

```text
predicted_top_region:       15
cutoff_region:              13
chemical_family_diversity:  12
uncertain_ood_conflict:     10
total:                      50
```

The user confirmed these semantics and counts before implementation and formal output generation.

## Scored output

`nhc-deprot score` creates `results/scoring_v001` atomically:

```text
results/scoring_v001/
├── full_ranked_candidates.parquet
├── top_candidates.csv
├── applicability_summary.json
├── score_manifest.json
├── figures/
│   ├── 01_xtb_rank_distribution.png
│   ├── 02_b1_interval_width_vs_xtb.png
│   ├── 03_applicability_counts.png
│   └── 04_family_support_coverage.png
└── _SUCCESS
```

Required prompt fields are retained, with explicit additional columns that separate production ranking from the B1 companion. The table is ordered by `(production_score_kcal, inchikey)` and preserves exact B0 ranks.

## B1 companion uncertainty

The 2,000 stored paired-label B1 coefficient replicates are applied in bounded row chunks. For candidate x:

```text
y_rep = beta_0_rep + rho_rep * x
```

Per row, Phase 5 records mean, sample standard deviation, p05, p50, p95, and interval width. The implementation never materializes a 401,856×2,000 matrix at once. It validates all replicate slopes as finite and positive; under that condition each replicate has the exact B0 ordering, so Top-10/50/100 probabilities are 1 for members and 0 otherwise.

The full-fit B1 point coefficient—not the bootstrap mean—defines `calibrated_dft_deprot_kcal`.

## Applicability

Each row records explicit booleans and support counts for:

- xTB inside/outside the 71-label range;
- skeleton, axis-A, and axis-B seen in the labels;
- axis-A and axis-B label counts;
- sparse family when a seen axis has support below 3;
- B1 interval width and high-uncertainty status, using the 95th percentile of widths on the 71 labeled xTB queries;
- size availability.

Because both size columns are missing for every candidate, no row is called fully `in_domain`. `applicability_status` is a deterministic semicolon-separated set drawn from `baseline_extrapolation`, `size_unavailable`, `unseen_axis_a`, `unseen_axis_b`, `sparse_family`, and `high_uncertainty`. A separate `core_model_in_domain` ignores the universally unavailable size dimension but does not hide it.

## Acquisition score

Only unlabeled candidates are eligible. Components are normalized to [0,1]:

```text
acquisition_score =
    w_top            * probability_top_50
  + w_uncertainty    * uncertainty_percentile
  + w_rank_shift     * 0
  + w_family_novelty * family_novelty
  + w_cutoff         * cutoff_proximity
  + w_diversity      * diversity_score
```

Family novelty is 1 when both axes are unseen, 0.5 when one is unseen, and otherwise decreases with label support. Cutoff proximity is triangular around production rank 50 within a configured window. Diversity uses deterministic greedy coverage of combined family, then axis-A, axis-B, and fragment identities; no unregistered molecular fingerprint dependency is added.

Bucket selection is deterministic in YAML order, excludes previously selected keys, and uses `(acquisition_score desc, production_rank asc, inchikey asc)` tie-breaking. Empty bucket pools may be filled only from the remaining global candidate pool and must report the shortfall/fill count.

## Acquisition outputs

`nhc-deprot acquire` verifies `results/scoring_v001` and creates `results/acquisition_v001` atomically:

```text
results/acquisition_v001/
├── acquisition_candidates.csv
├── high_fidelity_batch_manifest.json
├── acquisition_summary.json
├── acquisition_manifest.json
├── figures/
│   ├── 01_acquisition_buckets.png
│   ├── 02_selected_rank_vs_uncertainty.png
│   ├── 03_selected_family_coverage.png
│   └── 04_selected_applicability.png
└── _SUCCESS
```

The batch manifest includes InChIKey, cation/neutral SMILES, suggested priority, reasons, the registered B3LYP-D3(BJ)/def2-SVP electronic-energy protocol, `hessian_computed=false`, and `submit_hpc=false`. It is a local suggestion artifact only.

## CLI

```bash
nhc-deprot score \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --decision-results results/decision_v001 \
  --acquisition-config configs/acquisition.yaml \
  --out results/scoring_v001 \
  --dry-run

nhc-deprot acquire \
  --dataset data/processed/v001 \
  --scored-results results/scoring_v001 \
  --acquisition-config configs/acquisition.yaml \
  --out results/acquisition_v001 \
  --dry-run
```

Removing `--dry-run` was allowed only after the policy was confirmed and synthetic gates passed.

## Tests before production output

- exact 401,856-key coverage and stable lower-is-better ordering;
- B0 score/rank identity with the processed dataset;
- positive-affine rank preservation and deterministic Top-K probabilities;
- chunked B1 intervals matching an unchunked synthetic reference;
- missing/non-finite/negative bootstrap slopes rejected;
- baseline-range, family support, sparse, unseen, uncertainty, and size-unavailable flags;
- no false full-domain status when size is unavailable;
- 71 labeled keys excluded from acquisition;
- normalized component bounds and zero rank-shift contribution;
- largest-remainder quota counts and deterministic tie-breaking;
- unique selected keys and deterministic diversity coverage;
- no HPC/job action in CLI or batch manifest;
- upstream/output hash rejection, atomic cleanup, dry-run non-writing, and immutable output rejection.

## Phase 5 acceptance gate

Phase 5 passes only when scoring covers all 401,856 candidates, acquisition contains the confirmed number of unique unlabeled candidates with exact quotas, every applicability limitation and uncertainty definition is explicit, all hashes and independent readback pass, and no external computation or server action occurred.

The gate passed on 2026-07-22. Exact runtime identities and findings are recorded in `SCORING_V001_MANIFEST.json`, `ACQUISITION_V001_MANIFEST.json`, and `PHASE5_REPORT.md`.
