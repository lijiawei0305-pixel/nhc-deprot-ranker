# Phase 7 Geometry Smoke and Dedicated Runner Plan

## Decision and authorization boundary

The user approved the recommended next step after Phase 6:

1. generate both endpoint initial geometries for only the four preregistered smoke candidates on the HPC using the audited legacy M2 workflow;
2. develop a dedicated cation/neutral B3LYP-D3(BJ)/def2-SVP geomeTRIC runner that performs no Hessian and no extra single points.

Phase 7 is intentionally split at that boundary. The geometry smoke may execute after the documentation, local validation, network-choice, and read-only HPC gates pass. The dedicated runner may be implemented and mock-tested, but it must not execute locally or remotely in this phase. Running even one PySCF endpoint is Phase 8 and requires a new explicit authorization.

The Phase 6 result was merged to `main` by PR #6 at merge commit `55bfe4780de395aaf2cfeb9d82953795b4a9ed6b` before this phase began.

## Frozen inputs

Phase 7 reads only:

```text
results/dft_input_plan_v001/
docs/DFT_INPUT_PLAN_V001_MANIFEST.json
configs/geometry_smoke.yaml
```

The four rows are the exact `smoke.csv` order and the first assigned batch-01 row from each acquisition bucket:

| Batch position | Bucket | InChIKey |
| ---: | --- | --- |
| 1 | predicted top region | `IJWCXRPLHNQISE-UHFFFAOYSA-N` |
| 4 | cutoff region | `LBNPGYISTSLAHY-UHFFFAOYSA-N` |
| 7 | chemical-family diversity | `QXHIEGFUWOLQIJ-UHFFFAOYSA-N` |
| 9 | uncertain/OOD/conflict | `HQKHXILTVGYEGE-UHFFFAOYSA-N` |

The canonical three-column M2 input must be exactly 542 LF bytes with SHA256 `f486f93a2d58fb144c05a7340fd432334eeec46385c9319aca34d2e1b5c4cc87`. It contains only `InChIKey`, `SMILES_cation`, and `SMILES_neutral`. Reordering, replacement, backfill, or adding the other six batch-01 candidates is prohibited.

Registered upstream identities include:

| Artifact | SHA256 |
| --- | --- |
| Phase 6 smoke CSV | `0b55988527a239ec6b8e83c8879b14ca59e5c3fda457480a5f2acbb329292362` |
| Phase 6 candidates CSV | `18459553187ff9decb24a657405e76149c08800429acb0ec8d8e61af2d0ddef9` |
| Phase 6 package manifest | `e7524307d6e6d3822b67982a8553ea85b2702554f79eccc9adf2cff4e3205d5e` |
| Checked-in Phase 6 evidence | `bc97f21fcc48d43605948d81502636c005ee35b794e5deabace29e2fefedc36f` |

## Legacy M2 audit

The authoritative source remains the read-only legacy checkout at commit `44a68bf70031bd75799f42c4a02adf71f1b99d31`. The local main checkout and server-knowledge worktree have byte-identical relevant files:

| File | SHA256 |
| --- | --- |
| `scripts/mol/gen_3d.py` | `d23c7ad9a6e35948949f6485b53caafb0f3f5705148f642e3a4a30fb589a946a` |
| `scripts/mol/structure_gen.py` | `a50b50b9967ac9e8203b398fe69f3daebf40a144f37dae8e0aa086e613ad1365` |

Actual M2 behavior, not older prose, defines the smoke:

- cation and neutral are parsed and embedded independently with RDKit ETKDGv3;
- ten conformers are requested for each endpoint;
- `randomSeed=42` and `useRandomCoords=false`;
- each conformer attempts MMFF94 and falls back to UFF only on an exception;
- the lowest stored force-field energy is exported;
- the cation supplies legacy `C2_carbene`, `N1`, and `N3` indices;
- `parallel=1` is used for this four-row smoke.

Important limitations are mandatory provenance, not silent assumptions:

- M2 does not automatically retry failed embedding with random coordinates despite an older README claim;
- it ignores the force-field minimizer return code and does not record convergence;
- mixed MMFF/UFF energies would not be physically comparable;
- output files are not atomically written;
- resume checks syntax-level completeness, not chemistry or coordinate validity;
- the atom-map is produced on the cation, while the neutral is independently parsed and can have a different atom order;
- old data contain observed cation-map/neutral-index mismatches in 3 of 8 audited examples.

Therefore `exit 0` and the presence of three files never establish geometry acceptance. Every result must record `force_field_convergence=unavailable_legacy_m2` and `geometry_quality=initial_force_field_geometry`; it must not be called a local minimum or DFT-optimized structure.

## Geometry validation contract

A new validator will run once in the HPC molecular environment and must fail closed on any mismatch. After download, the Mac performs only byte/hash, strict-JSON, file-set and marker readback checks against the remote report; it does not import RDKit or repeat chemistry validation locally.

For the request and file tree it verifies:

- exactly four unique canonical InChIKeys in the preregistered order;
- exactly eight XYZ files and four legacy atom-map JSON files, with no symlink or extra chemistry output;
- every registered input/output hash and regular-file identity;
- exact XYZ line count, four fields per atom, recognized element tokens, finite coordinates, bounded coordinates, and a conservative no-collision distance check;
- both endpoint SMILES parse, cation formal charge is +1, neutral formal charge is 0, and the XYZ element sequence exactly matches `Chem.AddHs()` for its own SMILES;
- cation and neutral heavy-atom element multisets agree and neutral differs by the expected C2 proton only;
- the legacy cation atom-map is a JSON object with exactly valid integer `C2_carbene/N1/N3` indices and the mapped symbols are C/N/N;
- a neutral-specific C2 is independently derived from the neutral molecular graph: carbon, in the same five-membered NHC ring as two nitrogen neighbors, with no attached hydrogen;
- nitro nitrogen neighbors are excluded by the shared five-membered-ring requirement;
- the neutral graph-derived indices agree with the neutral XYZ atom order, and a corrected endpoint map is emitted without overwriting the legacy map.

The validator records Python, RDKit, pandas and NumPy versions, the requested seed/conformer count, actual legacy hashes, charge/atom/count/map checks, coordinate extrema/minimum distances, per-file SHA256 and the unavailable legacy force-field convergence state. Four of four must pass; no automatic replacement candidate is allowed.

## Server and transfer safety

Tracked files use only logical placeholders. The SSH alias, project root, and unique remote run root live in an ignored Phase 7 local configuration. The fixed logical layout is:

```text
<HPC_PROJECT_ROOT>/data/runs/<PHASE7_RUN_ID>/
├── input/
├── tools/
├── logs/
├── m2/xyz/
└── audit/
```

The target must not exist and neither it nor its parent may be a symlink. Existing legacy code, environments, data, results, and processes are never modified.

The server-knowledge rules require:

- ask whether the Mac is currently on the WHUT campus network;
- use direct SSH only on campus; otherwise restore and verify the local SOCKS5 listener before a proxied connection;
- stop repeated attempts after connection closure/timeout and do not diagnose the server from local fake-IP DNS;
- make one combined read-only preflight session before any write;
- verify project root, disk/RAM, relevant processes by CWD, environment scripts, Python/RDKit imports, and the two legacy file hashes;
- explicitly `cd <HPC_PROJECT_ROOT>`, set `PYTHONPATH`, and source only `env/envs/molenv.sh`; never source `.bashrc` or mix environments;
- temporarily disable shell `nounset` only while sourcing the Conda-backed `molenv.sh`, then immediately restore it;
- set `PYTHONDONTWRITEBYTECODE=1` and invoke Python with `-B`, preventing imports from creating `__pycache__` in the read-only legacy source tree or unregistered bundle paths;
- use explicit source and explicit full destination for every small transfer, with no `--delete`, no full deploy, and no absolute-source `--relative` mistake;
- verify every uploaded and downloaded file by SHA256 at its actual destination.

The four-row M2 smoke is short and runs synchronously with `parallel=1`; no detached process, scheduler, xTB, PySCF, or GPU action is needed.

## Local bundle and result trees

Before SSH, `prepare-geometry-smoke` creates an immutable transfer bundle:

```text
results/geometry_smoke_bundle_v001/
├── input/
│   ├── smoke_candidates.csv
│   ├── geometry_request.json
│   └── expected_outputs.csv
├── tools/
│   ├── run_legacy_m2_smoke.sh
│   ├── geometry_validation.py
│   └── validate_geometry_smoke.py
├── package_manifest.json
└── _READY_FOR_REMOTE_GEOMETRY
```

The generated shell script has no host, IP, user, or concrete project/run path. It receives the run root through an explicit argument, requires its resolved location to be exactly one `data/runs/nhc_deprot_ranker_phase7_smoke_*` child of the resolved project root, rechecks all hashes, loads only the molecular environment, runs exactly M2, then invokes the validator. It refuses an existing output directory and never deletes or overwrites a successful result.

After remote validation, only this run is downloaded into a new immutable local result:

```text
results/geometry_smoke_result_v001/
├── input/
├── tools/
├── logs/
├── m2/
│   ├── gen_3d_failed.log
│   └── xyz/
├── audit/
│   ├── geometry_validation.json
│   └── endpoint_atom_maps/
├── package_manifest.json
├── _READY_FOR_REMOTE_GEOMETRY
├── remote_inventory.json
└── _GEOMETRY_SMOKE_SUCCESS
```

The first 27 files are an exact mirror of the isolated remote run. `remote_inventory.json` and `_GEOMETRY_SMOKE_SUCCESS` are local-only hash-closed readback evidence. The local result must independently reproduce every remote hash and retain both the original legacy map and corrected endpoint-specific map.

## Dedicated two-endpoint runner contract

The runner is a new implementation; it must not call legacy `run_candidate`, `dft_batch`, `dft_robust_driver`, or `dft_harvest`.

Its only scientific flow is:

```text
initial cation XYZ -> +1 singlet B3LYP-D3(BJ)/def2-SVP geomeTRIC
initial neutral XYZ ->  0 singlet B3LYP-D3(BJ)/def2-SVP geomeTRIC
electronic_difference_kcal = (E_neutral - E_cation) * 627.509474
dft_deprot_electronic_kcal = electronic_difference_kcal - 6.28
```

No mode switch may enable a Hessian, thermochemistry, radical, Molden export, density-fitted ωB97X-D/def2-TZVP single point, or job submission. Required result flags are:

```text
hessian_computed = false
frequency_status = not_computed
n_imaginary = null
extra_single_points_computed = false
radical_computed = false
molden_written = false
label_quality = electronic_energy_only
```

The PySCF adapter is lazy-loaded and hard-fails if `mf.disp="d3bj"` is unavailable. Both geomeTRIC completion and the final same-method SCF must be explicitly converged and finite. A standard-SCF failure may make one recorded same-protocol SOSCF retry; it may never silently change method, basis, dispersion, charge, spin, or grid.

The core runner supports dependency injection so local tests use a fake backend. This phase ships an execution guard with `execution_authorized=false`; local and HPC execution is rejected before importing PySCF. It validates a future frozen request, atomically writes attempt-scoped JSON/XYZ results, never combines endpoints from different attempts, never backfills a fixed smoke set, and returns nonzero for backend-reported failures and elapsed-deadline checks. Resume requires exact request/protocol/input/source and output hashes; corrupt or drifted success state is a hard stop.

The current deadline check is cooperative and post-call: it cannot interrupt a PySCF or geomeTRIC call that hangs. This is harmless while the public execution gate is closed, but a process- or signal-level hard wall-time mechanism is a mandatory Phase 8 blocker before real execution is authorized; Phase 7 does not claim that hard timeout is implemented.

The implementation lives in `src/nhc_deprot_ranker/quantum/two_endpoint.py`. Its public guard is a source-level constant rather than a request option, so Phase 8 must make and review an explicit source change before a real backend can load. The Phase 7 tests call only the private dependency-injected core with a fake backend; they do not import PySCF or geomeTRIC.

Connection coordinates use the strict schema in `configs/phase7.example.yaml` and `src/nhc_deprot_ranker/preparation/remote_config.py`. The real `configs/phase7.local.yaml` is ignored, keeps DFT authorization false, and is not created until the user identifies the campus-direct versus SOCKS5 route.

## Implementation and test order

1. Update `AGENT.md`, this plan, and `PHASE_STATUS.md` before code or server actions.
2. Add strict typed geometry-smoke and runner policy configuration.
3. Implement the immutable four-row bundle builder and synthetic input/hash/path tests.
4. Implement the RDKit-dependent validator with synthetic fake-RDKit/unit seams; do not import or run RDKit locally.
5. Implement the guarded dedicated runner, PySCF adapter, atomic attempt/result schemas, and mock/static tests; do not execute it.
6. Run all local tests, Ruff, mypy, pre-commit, package build, and private-path checks.
7. Resolve the campus/proxy question, then run one SSH read-only preflight.
8. If the preflight passes, create the unique remote run root, transfer only the registered bundle, rehash, and synchronously run the four-row M2 smoke plus validator.
9. Download only this run, independently validate and hash it, write checked-in evidence/reports, and stop.

## Acceptance and mandatory stop

Phase 7 passes only if the local bundle is immutable, all four remote geometry pairs pass the strong graph/coordinate/hash validator, local and remote results are byte-accounted, the dedicated runner passes mock/static safety tests, and no DFT or other unauthorized calculation occurred.

After Phase 7, `blocked_no_xyz` may be resolved only for the four smoke candidates. The remaining 46 stay ungenerated. `blocked_runner_extra_steps` changes to “dedicated runner implemented but unexecuted,” not to an executed/validated computation claim. Phase 8 must pause for explicit permission before any PySCF smoke.
