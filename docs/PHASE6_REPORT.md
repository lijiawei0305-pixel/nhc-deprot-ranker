# Phase 6 Local DFT Plan Report

## Outcome

Phase 6 passed its local-planning gate on 2026-07-22. The frozen 50-candidate Phase 5 acquisition was converted into an immutable, legacy-M2-compatible handoff and a deterministic five-batch review plan at `results/dft_input_plan_v001`.

This is deliberately not an executable DFT input set. It contains no molecular geometry, quantum result, job script, server destination, or scheduler setting. Every manifest records `geometry_generated=false`, `quantum_chemistry_run=false`, `hessian_computed=false`, `execution_ready=false`, `server_write_authorized=false`, and `submit_hpc=false`.

## Inputs read

The implementation read and rehashed only these frozen local inputs:

- `data/processed/v001` plus `PROCESSED_V001_MANIFEST.json`;
- `results/acquisition_v001` plus `ACQUISITION_V001_MANIFEST.json`;
- `configs/dft_plan.yaml`;
- the previously audited legacy DFT interface files, read only, for their interface and hash contract.

The Phase 5 evidence, runtime manifest, and `_SUCCESS` pointer chain were all verified before parsing critical candidate/handoff files. The selected 50 InChIKeys are unique and have zero overlap with all 71 labeled keys. Candidate order, two endpoint SMILES, priorities, reason codes, acquisition quotas, and protocol identity agree with the frozen CSV and handoff manifest.

## Legacy interface conclusion

The seven relevant legacy files match commit `44a68bf70031bd75799f42c4a02adf71f1b99d31`. Legacy M2 accepts the exported columns `InChIKey`, `SMILES_cation`, and `SMILES_neutral`, so `candidates.csv` is ready for a future geometry-generation decision.

No selected candidate has a complete, uniformly evidenced cation/neutral XYZ pair. The legacy no-Hessian batch runner also performs additional ωB97X-D/def2-TZVP cation/neutral/radical single points beyond the requested two-endpoint electronic label. The package therefore carries both unresolved blockers:

- `blocked_no_xyz`;
- `blocked_runner_extra_steps`.

Legacy M2 handoff compatibility is true; legacy M4 execution readiness remains false.

## Local plan result

| Check | Result |
| --- | ---: |
| Candidate rows / unique InChIKeys | 50 / 50 |
| Frozen labels / overlap | 71 / 0 |
| Plan batches | 5 |
| Rows per batch | 10 |
| Bucket totals | 15 / 13 / 12 / 10 |
| Smoke rows | 4 |
| Smoke bucket coverage | 1 / 1 / 1 / 1 |
| Files / directories | 15 / 6 |
| Geometry files | 0 |
| Executable files / symlinks | 0 / 0 |
| Quantum or server actions | 0 |

The exact allocation is 3/3/2/2 for batches 01–03 and 3/2/3/2 for batches 04–05 in top/cutoff/diversity/uncertain-OOD order. The four-row smoke set is the first assigned row from each bucket in batch 01. Within every bucket, the Phase 5 stable order is preserved.

The output contains candidates, full/batch/smoke screens, batch metadata, relative expected-future paths, protocol and validation manifests, a non-executable handoff note, a package manifest, and a success marker. An exact file/directory allowlist rejects additions, symlinks, executable bits, binary artifacts, forbidden chemistry/run files, and private absolute paths.

## Scientific protocol

The package preserves the registered gas-phase electronic-energy label:

```text
NHC-H+ -> NHC + H+
B3LYP-D3(BJ)/def2-SVP
geomeTRIC endpoint optimization
cation +1 / singlet; neutral 0 / singlet
(E_neutral - E_cation) * 627.509474 - 6.28 kcal/mol
lower is better; no Hessian
```

This does not establish Gibbs free energy, ZPE/entropy/thermal corrections, a frequency-confirmed minimum, convergence, DFT accuracy, or synthetic feasibility.

## Provenance and independent readback

The checked-in `DFT_INPUT_PLAN_V001_MANIFEST.json` preserves all 15 output hashes, all registered upstream hashes, the source-tree identity, protocol identity, exact counts, key-set/order hashes, package-manifest hash, and no-action state.

Independent readback reproduced:

- candidate key-set SHA256 `0bc6c8ee72192db82743a695f73f8118ab0459c4e07dc2edfff70505969b97e5`;
- candidate order SHA256 `af62a059eb2d6398bbbd6804587a36f58c73a48e08e5748e14e0841456830a85`;
- planned order SHA256 `02d1b8ec3a6bb7527030c6eb21ea290c0f069d883d5538705f9013d2fae2e1ad`;
- source-tree SHA256 `6383232bb2efabf730ba4bd88b79dc7dcb3fe375c9ffd008fcba577de3f41d5b`;
- package-manifest SHA256 `e7524307d6e6d3822b67982a8553ea85b2702554f79eccc9adf2cff4e3205d5e`.

Four exported `acquisition_score` text values differ from the Phase 5 CSV only at floating-point serialization precision; the maximum absolute numeric difference after parsing is `4.44e-16`. All InChIKeys, both SMILES columns, remaining provenance fields, ordering, quotas, and batch assignments are exact, so this does not change selection or plan identity.

## Files created or modified

Phase 6 added typed configuration, the `prepare-dft-plan` CLI, local preparation code, synthetic tests, the implementation plan, this report, the test report, and checked-in evidence. It updated repository constraints, phase status, reproduction instructions, acquisition handoff documentation, project summaries, and the README.

The runtime result directory remains ignored; no large Phase 5 or Phase 6 data is committed.

## External work not performed

No RDKit conformer generation, force-field optimization, xTB, PySCF, Hessian, VASP, or CP2K calculation ran. No SSH/HPC connection, DNS/server probe, file transfer, server write, resource query, scheduler command, or job submission occurred.

## Gate decision and mandatory pause

Phase 6 local planning passes. Work stops before geometry generation and execution. The next phase requires one explicit scientific/operational decision: choose a uniform initial-geometry source and choose whether to implement a dedicated two-endpoint B3LYP-D3(BJ)/def2-SVP runner or accept the legacy runner's additional single-point work.
