# Phase 7 Report

## Outcome

Phase 7 passed on 2026-07-22. The exact four preregistered smoke candidates received cation and neutral initial geometries from the audited legacy M2 workflow on the HPC. All 12 legacy core files passed the strong graph, coordinate, atom-map, file-set and SHA256 validator, and all 27 remote-run files matched the downloaded local mirror byte for byte.

The dedicated two-endpoint B3LYP-D3(BJ)/def2-SVP runner was implemented and mock-tested, but its source-level execution gate remains false. No PySCF, xTB, Hessian, legacy M4, extra single point, radical calculation, scheduler submission or background job ran in this phase.

Checked-in machine-readable evidence is `docs/GEOMETRY_SMOKE_V001_MANIFEST.json`. The large geometry bundle and result mirror remain ignored under `results/`.

## Scope and frozen inputs

Phase 7 read the immutable Phase 6 plan and no other candidate source:

- `results/dft_input_plan_v001/`
- `docs/DFT_INPUT_PLAN_V001_MANIFEST.json`
- `configs/geometry_smoke.yaml`

The canonical legacy M2 CSV contained exactly the following four keys in order:

1. `IJWCXRPLHNQISE-UHFFFAOYSA-N`
2. `LBNPGYISTSLAHY-UHFFFAOYSA-N`
3. `QXHIEGFUWOLQIJ-UHFFFAOYSA-N`
4. `HQKHXILTVGYEGE-UHFFFAOYSA-N`

It was exactly 542 LF bytes with SHA256 `f486f93a2d58fb144c05a7340fd432334eeec46385c9319aca34d2e1b5c4cc87`. No row was replaced, backfilled, reordered or expanded to the remaining 46 candidates.

## Implementation

The local implementation added:

- strict Phase 7 geometry and private remote-route configuration models;
- an immutable portable bundle builder and `prepare-geometry-smoke` CLI;
- a standalone validator that lazy-loads RDKit only on the HPC;
- a host-free legacy M2 wrapper locked to one project namespace, `parallel=1`, ten conformers and bytecode-free execution;
- a dedicated protocol-locked cation/neutral runner with lazy PySCF loading, explicit D3(BJ), geomeTRIC and SCF convergence checks, one same-protocol SOSCF retry, atomic attempt state and strict resume validation.

The bundle contained eight registered files. Its package manifest SHA256 was `2c4d776ab009a1c265d080dc55392fc7cdf38137a62200fa4b67a38f79746ae9`. It contained no SSH alias, host, user, private absolute path or credential.

## Server preflight and transfer

The user confirmed the Mac was on the WHUT campus network, so the direct passwordless route was selected. The first read-only probe stopped before any write because the deployed server tree did not contain the local audited Git commit object. The two executable legacy files had already matched their exact registered hashes. The corrected complete preflight therefore treated those file hashes as the authoritative runtime identity and recorded the missing server Git history instead of treating a deployment-layout difference as source drift.

The passing preflight established:

- Python 3.11.15, RDKit 2025.03.6, pandas 3.0.3 and NumPy 2.4.6;
- `ETKDGv3` available in the molecular environment;
- the two legacy source hashes exactly matched `d23c7ad...a946a` and `a50b50b...d1365`;
- the isolated target did not exist and its real parent was writable;
- 211,502,164 KiB disk and 252,734,664 KiB memory were available;
- 112 CPUs were online and 95 existing processes had a CWD below the project tree.

The smoke remained serial and lightweight at `parallel=1`; no existing process was altered. A unique run root was created below the dedicated `data/runs/nhc_deprot_ranker_phase7_smoke_*` namespace. Eight files were uploaded to explicit full destinations, with no full deployment, delete, overwrite or `rsync --delete` operation. Remote hashes were checked before execution.

## Geometry generation and validation

Legacy M2 used ETKDGv3, seed 42, ten conformers per endpoint, `useRandomCoords=false`, MMFF94 with the legacy UFF-on-exception fallback, and one candidate worker. It processed 4/4 candidates successfully, skipped zero, failed zero and emitted zero fallback warnings. The failure log was empty.

The validator required all 12 core files and rejected symlinks or extras. It checked strict XYZ syntax, finite and bounded coordinates, collision distance, endpoint charges, exact `Chem.AddHs()` element order, heavy-element equality, the one-C2-proton difference, the legacy C/N/N atom map and an independently graph-derived neutral C2 in the shared five-membered NHC ring.

| InChIKey | Atoms cation/neutral | Minimum distance cation/neutral (Å) | Endpoint map |
| --- | ---: | ---: | --- |
| `IJWCXRPLHNQISE-UHFFFAOYSA-N` | 30 / 29 | 1.0870 / 1.0934 | passed |
| `LBNPGYISTSLAHY-UHFFFAOYSA-N` | 26 / 25 | 1.0872 / 1.0960 | passed |
| `QXHIEGFUWOLQIJ-UHFFFAOYSA-N` | 22 / 21 | 1.0878 / 1.0950 | passed |
| `HQKHXILTVGYEGE-UHFFFAOYSA-N` | 27 / 26 | 1.0869 / 1.0951 | passed |

Corrected endpoint-specific maps were emitted for all four candidates. Their numeric indices happened to agree with the legacy cation indices in this smoke, but acceptance depended on independent endpoint graph validation rather than that coincidence.

The validation report SHA256 is `35e99683a32e416752014c6e1ecb8121e2bc06d5407911435e5c1250fd639f90`. The 27-file remote mirror and local mirror matched exactly, with result-tree SHA256 `644f027e276902dc1ab105f02f08864967f69ae87dc8883f608f5e4d17a372ad`.

## Scientific interpretation and limitations

These are initial force-field geometries, not DFT geometries and not verified local minima. Legacy M2 ignores force-field minimizer return codes, so every result remains explicitly labeled:

```text
force_field_convergence = unavailable_legacy_m2
geometry_quality = initial_force_field_geometry
```

The absence of fallback warnings does not upgrade that quality statement. M2 has no automatic random-coordinate retry, writes its own core files non-atomically and can fall back to UFF on an exception. The strong downstream validator establishes structural and provenance completeness, not stationary-point character.

The dedicated runner is implemented but unexecuted. It supports only the two locked singlet endpoints and the electronic-energy formula `(E_neutral - E_cation) * 627.509474 - 6.28`. Its current deadline checks cannot interrupt a hung compute call. A process- or signal-level hard wall-time mechanism and new explicit user authorization are mandatory before Phase 8 may execute PySCF.

## Files read and changed

In addition to the frozen Phase 6 inputs, the phase read the audited local legacy M2 source, server knowledge and molecular environment contract. Tracked changes include `AGENT.md`, `PHASE_STATUS.md`, Phase 7 configs, preparation/validation modules, the quantum runner, CLI integration, tests, this report, the test report and the checked-in evidence manifest.

Ignored private/runtime files include `configs/phase7.local.yaml`, `results/geometry_smoke_bundle_v001/` and `results/geometry_smoke_result_v001/`. The private configuration and runtime results are not staged for publication.

## Commands and safety controls

The workflow used the local dry-run and creation forms of `nhc-deprot prepare-geometry-smoke`, one corrected combined read-only server preflight, explicit directed transfers, the generated synchronous M2 wrapper, a one-run-only download and independent remote/local hash readback. Every SSH and transfer used the passwordless identity and direct campus route. No command sourced `.bashrc`, used `--delete`, installed software, changed the legacy tree, deleted a remote file or touched another run.

## Gate conclusion and next action

The Phase 7 geometry and runner-development gates pass. `blocked_no_xyz` is resolved only for these four smoke candidates; the remaining 46 still have no generated geometry. `blocked_runner_extra_steps` is replaced by `dedicated_runner_implemented_unexecuted`.

Phase 8 remains stopped. Before any DFT smoke, the hard wall-time blocker must be implemented and the user must explicitly authorize real PySCF execution.
