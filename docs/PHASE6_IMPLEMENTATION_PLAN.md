# Phase 6 Local DFT Execution-Plan Specification

## Objective and authorization boundary

Phase 6 converts the frozen 50-candidate Phase 5 acquisition into an immutable local handoff plan. It prepares legacy-compatible candidate/screen CSV files, a balanced batch assignment, a four-bucket smoke subset, protocol identity, expected future artifacts, and complete provenance.

This phase does not generate molecular geometry and does not execute chemistry. It must not run RDKit conformer generation, force fields, xTB, PySCF, Hessians, or any legacy runner; connect to SSH/HPC; copy files to a server; inspect live server resources; or submit a job. Its result is `execution_ready=false` by design.

The user authorized this documentation-first local planning boundary after Phase 5. Geometry and execution require a new explicit decision after this plan passes.

## Frozen inputs

```text
data/processed/v001/
results/acquisition_v001/
docs/PROCESSED_V001_MANIFEST.json
docs/ACQUISITION_V001_MANIFEST.json
configs/dft_plan.yaml
```

The generator must rehash every registered dataset/acquisition artifact, verify the Phase 5 `_SUCCESS` and manifest identities, check the 50 selected keys against all 71 labels, and refuse any version, protocol, key, order, SMILES, quota, or no-action mismatch.

## Legacy interface audit

The authoritative local legacy snapshot was inspected read-only. The relevant files match commit `44a68bf70031bd75799f42c4a02adf71f1b99d31`; unrelated legacy worktree changes were not read as Phase 6 inputs and were not modified. The equivalent server-knowledge worktree has byte-identical relevant interfaces.

| Relative legacy path | SHA256 | Contract used here |
| --- | --- | --- |
| `scripts/mol/dft_runner.py` | `45b3bbb8118a749b7e453b414d22edb42c5fe7d19861bcf184711ed3e12ce832` | endpoint protocol and skip-Hessian semantics |
| `scripts/mol/dft_batch.py` | `9641125099c2f95f6566cb76bc2b24525d2b784dbde936403893433ae702a71b` | `InChIKey`, screen, XYZ, result schema |
| `scripts/mol/dft_robust_driver.py` | `9172fc97be8bdf92935b7de41e673c42a49e50bf26ed63ca4518708964af1a6a` | timeout/backfill interface only |
| `scripts/mol/gen_3d.py` | `d23c7ad9a6e35948949f6485b53caafb0f3f5705148f642e3a4a30fb589a946a` | legacy M2 CSV entry point |
| `scripts/mol/structure_gen.py` | `a50b50b9967ac9e8203b398fe69f3daebf40a144f37dae8e0aa086e613ad1365` | expected XYZ/atom-map names |

Legacy M2 requires exact CSV columns `InChIKey`, `SMILES_cation`, and `SMILES_neutral`, then would create `<key>_cation.xyz`, `<key>_neutral.xyz`, and `<key>_atom_map.json`. Legacy M4 reads `InChIKey` from a screen CSV and requires both XYZ files.

The audit found no complete cation/neutral XYZ pair for any of the selected 50. A partial cache contains only seven cation geometries, without matching neutral geometry/atom maps, and is rejected as non-uniform evidence. Therefore Phase 6 may prepare an M2 handoff but not an M4-ready input.

`dft_batch --skip-hessian` means Hessian/frequency is skipped, `G=E`, `n_vfreq=-1`, and `freq_computed=false`. It still performs cation/neutral B3LYP-D3(BJ)/def2-SVP optimization plus cation/neutral/radical ωB97X-D/def2-TZVP single points. The latter are outside the minimum electronic-label request, so compatibility is also blocked until the user accepts the extra work or authorizes a dedicated two-endpoint runner.

## Confirmed batching policy

The 50 candidates are divided into five batches of ten. Within every acquisition bucket, rows retain deterministic Phase 5 order `(acquisition_score desc, production_rank asc, InChIKey asc)`. Rows are assigned by this registered matrix:

| Batch | Top | Cutoff | Diversity | Uncertain/OOD | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| 01 | 3 | 3 | 2 | 2 | 10 |
| 02 | 3 | 3 | 2 | 2 | 10 |
| 03 | 3 | 3 | 2 | 2 | 10 |
| 04 | 3 | 2 | 3 | 2 | 10 |
| 05 | 3 | 2 | 3 | 2 | 10 |
| Total | 15 | 13 | 12 | 10 | 50 |

Batch 01 contains a preregistered four-row smoke subset: the first assigned row from each bucket. Smoke selection is metadata only and does not authorize execution.

## Scientific protocol

The plan locks the same electronic-energy label contract as the 71 existing labels:

```text
reaction: NHC-H+ -> NHC + H+
method: B3LYP
dispersion: D3(BJ)
basis: def2-SVP
geometry optimizer: geomeTRIC
phase: gas
cation: charge +1, multiplicity 1
neutral: charge 0, multiplicity 1
hessian_computed: false
label: (E_neutral - E_cation) * 627.509474 - 6.28 kcal/mol
lower_is_better: true
```

No ZPE, entropy, thermal correction, Gibbs free energy, frequency-confirmed minimum, DFT convergence, or synthesis outcome may be inferred from the plan.

## Immutable output tree

`nhc-deprot prepare-dft-plan` creates the following atomically:

```text
results/dft_input_plan_v001/
├── candidates.csv
├── screen_full.csv
├── smoke.csv
├── batch_plan.csv
├── expected_outputs.csv
├── protocol_manifest.json
├── validation_report.json
├── HANDOFF.md
├── batches/
│   ├── batch_01/screen.csv
│   ├── batch_02/screen.csv
│   ├── batch_03/screen.csv
│   ├── batch_04/screen.csv
│   └── batch_05/screen.csv
├── package_manifest.json
└── _LOCAL_PLAN_SUCCESS
```

`candidates.csv` is directly compatible with legacy M2 and includes acquisition provenance. Every screen file uses `InChIKey,pass_filter` with `pass_filter=true`. `expected_outputs.csv` lists relative future paths only; it does not claim those files exist. `HANDOFF.md` is non-executable, contains no SSH/server destination, and states all unresolved gates.

No `.xyz`, `.molden`, `freq.json`, quantum result, environment activation script, upload script, or scheduler script is permitted anywhere in the output tree.

## Required manifest state

The output must record:

```text
geometry_generated = false
geometry_status = not_generated
quantum_chemistry_run = false
hessian_computed = false
execution_ready = false
server_write_authorized = false
submit_hpc = false
legacy_compatibility = [blocked_no_xyz, blocked_runner_extra_steps]
```

The package manifest hashes every pre-manifest output, all registered upstream inputs, the current source tree, the 50-key set and order, every batch membership, and the configuration. Existing `dft_input_plan_v001` is immutable and `--overwrite` is rejected.

## Tests before real local output

- strict typed configuration and exact no-action literals;
- registered batch-matrix totals and per-batch size;
- strict InChIKey format plus unique/nonblank key and SMILES checks;
- upstream evidence, `_SUCCESS`, protocol, quota, order, and label-exclusion mismatch rejection;
- deterministic bucket ordering, 5×10 partition, and four-bucket smoke identity;
- expected legacy column names and relative path inventory;
- no forbidden extensions/files/absolute paths in the result;
- dry-run non-writing, atomic cleanup, immutable-output rejection, and full hash readback;
- a small synthetic end-to-end fixture independent of production Parquet, RDKit, PySCF, xTB, and HPC.

## Phase 6 acceptance gate and mandatory pause

The local plan passes only if all 50 frozen suggestions are represented exactly once, the five batches and smoke subset match this specification, every protocol and blocker is explicit, all hashes independently read back, and no geometry/external/quantum action occurred.

After the gate, work must pause for one interactive decision: choose the authorized initial-geometry source and whether a dedicated two-endpoint B3LYP runner should replace the legacy extra-single-point workflow. Until then, the package remains deliberately non-executable.
