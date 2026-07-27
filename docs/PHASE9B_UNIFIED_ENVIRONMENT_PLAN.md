# Phase 9B-U1 — Dedicated Unified Environment Build and Audit

## Status and purpose

This is the document-first plan for one narrowly authorized infrastructure
change: create a new, versioned conda prefix by cloning the verified project
MLFF environment, add the exact frozen PySCF stack, and prove that both stacks
can coexist in one interpreter and one process.

This phase is not Phase 9B scientific execution. It may perform exactly two
AIMNet2 energy-and-force evaluations per endpoint contract (one cation and one
neutral evaluation, with ASE requesting energy and force together) as a
compatibility smoke. It may not optimize a geometry, construct or run a PySCF
kernel, compute a gradient with PySCF, run geomeTRIC or D3, create a label,
deploy a Phase 9B payload, create or place a permit, or launch either route.

## Frozen architecture decision

```text
clone <PROJECT_MLFF_ENV> offline
  -> <PHASE9B_UNIFIED_ENV_ROOT>
  -> add exact frozen PySCF/geomeTRIC/pyscf-dispersion artifacts offline
  -> validate both import orders and native-library coexistence
  -> run the two-call AIMNet2 compatibility smoke
```

The source environment, project AIMNet2 environment, project gpupyscf
environment, and shared molecular environment remain read-only. No environment
is modified in place, no two `site-packages` trees are joined with
`PYTHONPATH`, and no alternate environment or `v002` target is selected if the
registered target already exists.

## Registered private targets

Public documents use placeholders only.

```text
logical environment       nhc-phase9b-unified-v001
target prefix             <PHASE9B_UNIFIED_ENV_ROOT>
target Python             <PHASE9B_UNIFIED_PYTHON>
private wheelhouse        <PRIVATE_WHEELHOUSE>
private build evidence    <PRIVATE_WHEELHOUSE>/evidence
attempt-local cache       <PRIVATE_WHEELHOUSE>/runtime-cache
source prefix             <PROJECT_MLFF_ENV>
```

Every target must be absent before the first write. The target prefix and
wheelhouse are exclusive to this attempt. If either exists, is a symlink, has a
registry entry, or has a staging residue, the phase stops without deleting,
overwriting, reusing, or switching to another version.

## Pre-write audit

Before any server write, one bounded read-only inspection must establish:

- the target prefix and wheelhouse are absent and their parents are the
  registered project-owned roots;
- the logical name has no conda registry entry and no staging residue exists;
- available memory, disk, host load, and GPU occupancy are recorded;
- the source MLFF and gpupyscf package sets are compared into
  `protected_packages`, `missing_packages`, `overlapping_packages`,
  `version_conflicts`, `native_library_risks`, and `install_plan`;
- source MLFF `numpy`, `scipy`, `h5py`, and `setuptools` satisfy the frozen
  requirements without any upgrade or downgrade;
- any missing `networkx` or `six` version is taken exactly from the verified
  gpupyscf environment and assigned one official PyPI artifact and SHA256;
- a dependency simulation proves the plan does not change Python, Torch,
  AIMNet, ASE, NumPy, SciPy, h5py, CUDA packages, Warp, or the nvalchemi
  toolkit;
- all four existing environments have a before snapshot covering prefix,
  Python executable identity, `conda-meta/history`, `conda list --explicit`,
  `pip freeze --all`, critical versions and distribution metadata, file count,
  total bytes, and mtime summary.

The inspection is read-only, runs with `python -I -B` where Python is used, sets
`PYTHONDONTWRITEBYTECODE=1`, and neither imports a chemistry kernel nor loads a
model.

## Frozen artifacts and supply chain

Only official PyPI / `files.pythonhosted.org` artifacts are allowed:

```text
pyscf==2.13.1
  pyscf-2.13.1-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
  27b991d37ff16137d28b7210f678f8a027264cb66590afdd2002c5b69001f8b3

geometric==1.1.1
  geometric-1.1.1.tar.gz
  c712c4102bb9db4afab4c7a482289a13d04989735cc1430c89ebb73d587d1d8b

pyscf-dispersion==1.5.0
  pyscf_dispersion-1.5.0-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
  c65aa46f24005794bf8198205a0d83f3431a23333868fbafff43bd82efc2294d
```

If `networkx` or `six` is missing, its exact version, filename, official URL,
and SHA256 must be added to the private plan before download. No unpinned name,
latest-version resolution, mirror fallback, source dependency download, model
download, Hugging Face access, or registry model alias is allowed.

Artifacts are downloaded into an exclusively created wheelhouse and re-read for
full SHA256. geomeTRIC is built in the new environment only, from the verified
sdist, with `--no-deps --no-build-isolation`; its wheel contents and SHA256 are
recorded. PySCF and pyscf-dispersion must use the registered official wheels.

## Clone and exact installation

The registered conda implementation performs an offline clone equivalent to:

```text
conda create --clone <PROJECT_MLFF_ENV>
             --prefix <PHASE9B_UNIFIED_ENV_ROOT>
             --offline
```

Immediately after cloning and before adding anything, the clone must prove
Python 3.11.15, Torch runtime 2.8.0+cu128, CUDA 12.8, `sm_70`, AIMNet 0.2.0,
ASE 3.29.0, exact protected-package parity with the source, a distinct prefix,
and a Python realpath inside the new prefix. The source snapshot must remain
unchanged.

Installation uses only the wheelhouse and `--no-index --find-links --no-deps`,
in this order: missing `six`/`networkx` if needed, locally built geomeTRIC wheel,
official PySCF wheel, official pyscf-dispersion wheel. A resolver may not change
an existing distribution. `pip check` and an independent metadata dependency
validation must both pass. A failed target is retained as
`failed_incomplete_environment`; it is never deleted or reused.

## Identity and validation

The private `UnifiedExecutionEnvironmentIdentity` records the complete target
identity: schema, sanitized logical prefix, Python executable metadata and
SHA256, Python/conda identities, conda history and explicit spec, pip freeze,
every distribution's version and METADATA/RECORD hashes, native libraries,
Torch/CUDA/architecture data, AIMNet/ASE/PySCF/geomeTRIC/dispersion versions,
weight identity, source snapshot identity, downloaded and built artifacts,
canonical environment SHA256, timestamp, and status.

Status is exactly one of `built_unvalidated`, `validated`, or `rejected`.
`built_unvalidated` is not usable by Phase 9B.

Two fresh `<PHASE9B_UNIFIED_PYTHON> -I -B` processes must pass ML-first and
PySCF-first import orders. Offline flags are set before import; every cache root
is redirected into the registered attempt-local cache. Module paths must remain
inside the new prefix. `/proc/<pid>/maps` evidence records OpenMP, BLAS, CUDA,
Torch, PySCF, and dispersion native libraries. A crash, symbol error, duplicate
incompatible runtime, need for `LD_LIBRARY_PATH`, or path outside the prefix is
terminal.

Only after both import-order/native smokes pass, the capability smoke selects
the currently lowest free V100 once, without waiting, preemption, retry, or card
switching. In one fresh process it imports both stacks, verifies the exact local
weight, constructs one `AIMNet2Calculator(..., compile_model=False)`, constructs
explicit cation `charge=+1, mult=1` and neutral `charge=0, mult=1` wrappers, and
performs exactly one ASE energy-and-force request for each frozen Phase 7 XYZ.
Coordinates remain unchanged. No optimizer or PySCF compute object is created.

The total is two AIMNet model invocations, two reported energies, two reported
force arrays, zero optimizer steps, zero PySCF kernels, zero PySCF gradients,
and zero labels. Global caches and the weight are snapshotted before and after;
all created files must stay in the registered cache and be inventoried.

## Acceptance and hard stops

Validation requires all frozen versions, `pip check`, metadata dependencies,
both import orders, native libraries, V100/`sm_70`, exact weight, both finite
single-point results with `(N, 3)` finite forces, no coordinate change, no
network, no model download, no global-cache drift, no bytecode, no unregistered
file, and byte-identical before/after snapshots for all four old environments.

Any prompt section 16 hard-stop condition ends the phase. There is no retry,
rollback, deletion, repair of an old environment, alternate prefix, alternate
artifact, relaxed version, path joining, or scientific execution.

## Identity effect and next gate

The current v8 request/resources/permit do not bind a unified interpreter
identity, and the current preflight invokes an unbound `python3`. A successful
environment therefore leaves four states deliberately distinct:

```text
environment_built
environment_validated
execution_identity_not_yet_rebased
phase9b_not_authorized
```

This phase does not edit the runner source closure, so the source schema remains
v8 and its digest is not changed merely because an environment was built. It
does not generate or place any permit. A later gate-closed integration phase
must bind the unified environment identity into preflight, resources, request,
and permit, mark the old blocked request/manifest identities
`superseded_before_execution`, and only then proceed to Postflight and the
closed-gate rehearsal.
