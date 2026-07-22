# Phase 1 Implementation Plan

## Objective

Convert the audited read-only legacy sources into one immutable, normalized dataset version without copying raw legacy files into this repository. Phase 1 implements import, validation, provenance, and family canonicalization only; it does not fit B0, B1, or H1.

## Input policy

- Real roots and the SSH alias remain only in ignored `configs/legacy.local.yaml`.
- Local sources are opened directly and read only.
- HPC-only CSVs are streamed over non-interactive SSH into the importer; raw bytes are not persisted under this repository.
- Every source is identified by logical location, project-relative path, byte size, and SHA256.
- Remote source metadata is checked before import; SSH never runs an environment activation, calculation, or write command.

## Output layout

For dataset version `v001`:

```text
data/processed/v001/
├── candidates.parquet
├── labels.parquet
├── label_source_membership.csv
├── source_manifest.json
├── protocol_manifest.json
├── data_quality.json
└── _SUCCESS
```

The directory is built in a sibling temporary directory and atomically renamed only after all files and hashes succeed. Existing version directories are never silently replaced. `--overwrite` remains a recognized common option but does not waive processed-dataset immutability; a changed dataset requires a new version.

## Candidate import

1. Read and validate the v3 graph and v4-new fragment tables.
2. Reject blank/duplicate keys, missing fragment cells, source overlap, or conflicting fragment assignments.
3. Stream the authoritative full xTB table and require finite key, SMILES, endpoint energies, and target.
4. Recompute every xTB target from endpoints with `627.509474` and `-6.28`; reject differences over `0.02 kcal/mol`.
5. Join family codes by InChIKey and require exact bidirectional key coverage.
6. Assign explicit `skeleton=imidazolium` from versioned source metadata.
7. Build exchange-invariant axis and combined families.
8. Sort by `(xtb_deprot_kcal, inchikey)` ascending; assign deterministic ordinal ranks and percentile `(rank-1)/(n-1)`.

The processed table stores no legacy Hessian claim. The audited xTB `n_imaginary=0` value is ignored because the same rows explicitly skipped Hessian.

## Label import

1. Load gold, blind-round-1, and blind-round-2 column mappings from `configs/data.yaml`.
2. Require finite endpoints and stored target for the current sources.
3. Recompute `electronic_difference_kcal` and `dft_deprot_electronic_kcal`; reject differences over `0.02`.
4. Attach the normalized B3LYP-D3(BJ)/def2-SVP/geomeTRIC protocol and deterministic protocol ID.
5. Record `electronic_energy_only`, successful endpoints, skipped Hessian, and null `n_imaginary`.
6. Permit numerically consistent duplicate labels with the same protocol through deterministic source membership merging; reject target, endpoint, or protocol conflicts.
7. Require every label key to occur in the candidate table.

## Manifests and reports

- `source_manifest.json`: exact source/config hashes, sizes, row counts, and logical paths.
- `protocol_manifest.json`: normalized protocol and protocol ID.
- `data_quality.json`: counts, missingness, duplicates, formula checks, family coverage/support, overlaps/conflicts, and output hashes.
- `label_source_membership.csv`: one row per label-source membership, retaining all source provenance even when consistent duplicates merge.
- `_SUCCESS`: small JSON completion marker containing dataset version and manifest hashes.

## Failure behavior

- No partial final version directory.
- No silent row dropping, coercion, duplicate resolution, unknown family, or formula repair.
- Parsing/convergence/provenance failures identify the source and row/key where possible.
- Remote connection failure is reported as a source-access error and never interpreted as missing scientific data.

## Tests before production build

- local and mocked/command-plan source resolution;
- candidate duplicate, missing family, formula mismatch, and rank direction;
- family exchange invariance;
- label formula, consistent duplicate merge, and conflict rejection;
- deterministic protocol/source hashes;
- atomic output, immutable existing version, and dry-run non-writing behavior;
- end-to-end synthetic fixture from legacy CSVs to Parquet/manifests.

## Phase 1 gate

Phase 1 passes only when the real `v001` build reports:

- 401,856 unique candidates and zero target/formula failures;
- 100% fragment coverage and deterministic canonical families;
- 71 unique labels, 71 formula checks, zero conflicts, one protocol ID;
- all labels match candidate keys;
- complete output/source hashes and `_SUCCESS` marker;
- pytest, Ruff, mypy, pre-commit, and CLI smoke pass.

Phase 2 does not start automatically after this gate.
