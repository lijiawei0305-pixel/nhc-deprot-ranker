# Acquisition Specification and v001 Result

## Boundary

`nhc-deprot acquire` selects candidates from an already verified full-score result. It writes a local suggestion only: it does not run PySCF, connect to a server, copy inputs, or submit an HPC job.

Phase 5 uses B0 raw xTB as the formal rank. B1 contributes only a companion coefficient-bootstrap interval. H1 family corrections are not used. Because every stored B1 bootstrap slope is positive, B1 preserves B0 order and the rank-shift component is exactly zero.

## Registered score

All components are normalized to `[0,1]` and their weights come from `configs/acquisition.yaml`:

```text
acquisition_score =
    w_top            * probability_top_50
  + w_uncertainty    * uncertainty_percentile
  + w_rank_shift     * 0
  + w_family_novelty * family_novelty
  + w_cutoff         * cutoff_proximity
  + w_diversity      * diversity_score
```

Family novelty depends on label support across the exchange-invariant axis-A and axis-B families. Diversity uses deterministic categorical coverage of combined/axis families and N1/N3/C4/C5 fragments. Missing validated size is exposed as `size_unavailable`; it is not fabricated as a molecular-size score.

The exact 50-row largest-remainder allocation is:

| Bucket | Fraction | Rows |
| --- | ---: | ---: |
| Predicted top region | 0.30 | 15 |
| Cutoff region | 0.25 | 13 |
| Chemical-family diversity | 0.25 | 12 |
| Uncertain/OOD/conflict | 0.20 | 10 |

Selection proceeds in configuration order without replacement. Stable ties use acquisition score descending, production rank ascending, and InChIKey ascending. Already labeled keys are excluded before selection; any bucket shortfall must be reported.

## v001 result

`results/acquisition_v001` contains 50 unique suggestions and excludes all 71 labels with zero overlap. Exact quotas were realized without shortfall/fill. The batch spans ranks 1–69 and 46 combined families. All 50 are baseline extrapolations, high under the limited B1 coefficient-uncertainty threshold, unseen on axis A, and missing validated size; 24 are also unseen on axis B.

These warnings are why the result is an information-gathering proposal, not a claim that any candidate is experimentally best or DFT-accurate.

## Outputs

- `acquisition_candidates.csv`: score components, bucket, ranks, interval, family fields, applicability fields, reasons, and priority;
- `high_fidelity_batch_manifest.json`: InChIKey/SMILES, registered B3LYP-D3(BJ)/def2-SVP electronic protocol, reason codes, and explicit no-action flags;
- `acquisition_summary.json`: pool/exclusion counts, quotas, coverage, and applicability summary;
- `acquisition_manifest.json` and `_SUCCESS`: input/output hashes, source identity, and immutable completion;
- four audit figures covering quotas, rank/uncertainty, family coverage, and applicability.

The interoperability manifest records `hessian_computed=false`, `submit_hpc=false`, and `server_write_authorized=false`. Generating or reviewing it does not authorize a calculation campaign.

## Phase 6 local handoff

Phase 6 freezes these same 50 rows into `results/dft_input_plan_v001` without rescoring or reselection. The plan preserves exact candidate order and SMILES, partitions the four acquisition buckets into five registered ten-row batches, and chooses one batch-01 smoke row per bucket.

`candidates.csv` uses the legacy M2 column names, but the plan is not M4 execution-ready: no complete cation/neutral XYZ pairs exist, and the audited legacy no-Hessian runner would perform extra ωB97X-D/def2-TZVP single points. The checked-in evidence therefore retains `blocked_no_xyz` and `blocked_runner_extra_steps`, with every execution/server flag false. See `PHASE6_REPORT.md` and `DFT_INPUT_PLAN_V001_MANIFEST.json`.
