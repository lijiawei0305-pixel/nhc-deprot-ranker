# Phase 9B-U1 — Unified Environment Build and Audit Report

## Outcome

**Phase 9B 统一环境构建或验证已 fail closed；所有既有环境保持不变，未运行科学计算，也未进入 Phase 9B 执行。**

The new prefix was created by offline-cloning the verified project MLFF
environment and the exact PySCF stack was installed successfully, but the
capability-smoke harness rejected the environment before validation. The target
is retained at `<PHASE9B_UNIFIED_ENV_ROOT>` with status
`failed_incomplete_environment`. It is not a validated environment, is not
usable by Phase 9B, and may never be deleted, repaired, retried, or reused under
this authorization.

Machine-readable public evidence:

- `docs/PHASE9B_UNIFIED_ENVIRONMENT_MANIFEST.json`
- `docs/PHASE9B_UNIFIED_ENVIRONMENT_CAPABILITY_SMOKE.json`
- `docs/PHASE9B_UNIFIED_ENVIRONMENT_ARTIFACTS.json`

The independently authorized successor attempt is planned in
`docs/PHASE9B_UNIFIED_ENVIRONMENT_V002_PLAN.md`, with preregistered counter
definitions in `docs/PHASE9B_CALCULATOR_INVOCATION_SEMANTICS.md`. Those links
do not amend this report, complete its missing evidence, or change U1's
`failed_incomplete_environment` result.

## Why MLFF was cloned

The project MLFF prefix is the only audited project environment that already
carries the exact V100-tested ML stack: Python 3.11.15, Torch 2.8.0+cu128,
CUDA 12.8 with `sm_70`, AIMNet 0.2.0, and ASE 3.29.0. Cloning it preserves that
base while leaving all audited environments immutable. Cloning gpupyscf would
require adding the much larger Torch/AIMNet/CUDA stack; shared `molecular`
would require adding both Torch and AIMNet and changing ASE 3.28.0. Both were
outside the frozen architecture decision.

## Pre-write gate

Before the first write, a complete read-only audit established:

```text
target prefix absent                         yes
wheelhouse absent                            yes
same-name conda registry entry absent        yes
staging residue absent                       yes
target parent is registered project env root yes
available disk                               about 119 GiB
available memory                             about 215 GiB
networkx / six addition needed               no
protected resolver changes                   none
```

MLFF NumPy 2.4.6, SciPy 1.17.1, h5py 3.16.0, setuptools 83.0.0,
networkx 3.6.1, and six 1.17.0 satisfy the frozen dependency plan. No package
resolver was allowed to choose a version.

## Artifact supply chain

Three artifacts were selected from official PyPI metadata, downloaded only
from `files.pythonhosted.org`, exclusively created in `<PRIVATE_WHEELHOUSE>`,
and re-read for full SHA256:

```text
pyscf 2.13.1 wheel
  27b991d37ff16137d28b7210f678f8a027264cb66590afdd2002c5b69001f8b3
geometric 1.1.1 sdist
  c712c4102bb9db4afab4c7a482289a13d04989735cc1430c89ebb73d587d1d8b
pyscf-dispersion 1.5.0 wheel
  c65aa46f24005794bf8198205a0d83f3431a23333868fbafff43bd82efc2294d
```

The geomeTRIC sdist was built inside the new prefix with no dependencies and no
build isolation. The resulting wheel is
`geometric-1.1.1-py3-none-any.whl`, 408,348 bytes, SHA256
`c1d00c5c9e3f248783e8c50289c2480075092c1878be354cf01d185429a93443`.
Its canonical build-command SHA256 is
`4ae0a5e0aaa4a27a01181fce33009fa470376a08e168b5083cdd46879eb84d25`;
the 117-entry wheel-contents manifest hashes to
`4dbad505d485f8041ba4146c19f327c3e6d5ea69051b0156c530dfc653e2989c`.
No model, ensemble member, or Hugging Face asset was downloaded.

## Clone and package state

The clone completed offline. Before adding the PySCF stack it proved:

```text
Python             3.11.15
Torch metadata     2.8.0
Torch runtime      2.8.0+cu128
CUDA               12.8
sm_70              present
GPU model          Tesla V100-SXM2-32GB
AIMNet             0.2.0
ASE                3.29.0
```

geomeTRIC, PySCF, and pyscf-dispersion were then installed in the frozen order
with `--no-index --no-deps`. The final installed versions are 1.1.1, 2.13.1,
and 1.5.0 respectively. `pip check` returned “No broken requirements found”,
and the independent metadata validator passed all nine requirements. No
protected package changed.

The failed target's post-install tree remains byte-metadata-identical to the
tree recorded before the import/capability smokes: 49,435 entries,
8,250,263,715 regular-file bytes, listing SHA256
`9a66962e8a7a6c08ccaf52653b0dacdd8c1578f8a55e3e8304f099358188c7d4`.
Its incomplete-state canonical digest is
`b3468a9f2319e61cd15d45256aef6a19b8bb06093867361141558f9d75b3f996`.
This is deliberately named a failed-environment state digest, not a validated
`environment_canonical_sha256`; the latter is unavailable.

## Import and native-library smokes

Both fresh import-order processes completed with return code zero and empty
stderr:

```text
ML-first     torch -> aimnet -> ase -> pyscf -> geometric -> dispersion
PySCF-first  pyscf -> geometric -> dispersion -> torch -> aimnet -> ase
```

Their strace records show zero external AF_INET/AF_INET6 connect/send calls.
However, the structured payload carrying module paths and `/proc/<pid>/maps`
remained in the orchestration process and was not written before the later
capability assertion failed. Therefore the import processes are evidence that
the orders did not crash or raise a symbol error, but the native-library gate is
**not accepted**: its portable map evidence is incomplete.

## Capability-smoke failure

The capability process used the currently lowest free V100, the existing exact
local `_0` weight, explicit cation `charge=+1, mult=1`, and neutral
`charge=0, mult=1`. It reached the assertion after both endpoint energy and
force property reads and reported:

```text
model invocation count drifted: 4
```

The harness had preregistered two calculator invocations, assuming one combined
model execution per endpoint. The real ASE access sequence called
`get_potential_energy()` and `get_forces()` separately and the counting wrapper
observed four calculator executions. That distinction was not closed in the
plan or harness, so the environment cannot be promoted by reinterpreting the
result after the fact.

No retry occurred. The failure happened before the structured per-endpoint
payload, global-cache after-snapshot, and native maps were durably committed.
Consequently, finite/shape/coordinate assertions that control flow had already
passed are not promoted into accepted portable evidence, and global-cache
before/after equality is recorded as unavailable. The current weight still has
8,836,941 bytes and the frozen SHA256, but a complete attempt-local before/after
receipt was not produced.

The attempt-local cache retained 67 files / 10,414,745 bytes under registered
`build` and `capability` roots. Network tracing observed local Unix-domain
connections and one IPv6 loopback socket bind, but zero outbound Internet
connect/send call. This is reported precisely rather than simplified to “no
network syscalls”.

The final private retained-file manifest covers 94 files / 76,776,836 bytes
excluding the manifest itself and has SHA256
`c498e44c0269147c3b2dc22000efbc76e5a6b1eddfaa93c79d18f09b5945ae17`.
The separate failure read-only audit hashes to
`5893f2bce0ddd4b52502bb127378b1190a0443092dcce0a1f013e2ab2d97da0f`.

## Existing-environment protection

After failure, all four environments were snapshotted again with the same key
set used before the build. Each full snapshot — Python executable identity,
conda history, explicit spec, pip freeze, critical METADATA/RECORD hashes, file
count, total bytes and mtime summary — is identical:

```text
<PROJECT_MLFF_ENV>       unchanged
<PROJECT_AIMNET2_ENV>    unchanged
<PROJECT_GPUPYSCF_ENV>   unchanged
<SHARED_MOLECULAR_ENV>   unchanged
```

No repair was attempted because no repair was needed, and the contract forbids
trying to “fix back” an existing environment.

## Identity and execution consequences

The failed prefix does not resolve the Phase 9B execution blocker. The current
v8 preflight still invokes an unbound `python3`, and the current
request/resources/permit do not bind a unified environment identity. This round
changed no runner source, so the source schema remains v8 and SHA256 remains
`5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2`.

All eleven public execution gates remain false. No Phase 9B payload was
deployed, no permit was generated, placed, or consumed, no guardian or worker
was launched, no geometry optimization or PySCF kernel ran, no label was
created, and the production high-fidelity label count remains **71**.

## Repository quality gate

The gate-closed public change passed:

```text
targeted identity tests                 15 passed
full pytest, run 1                      1282 passed
full pytest, run 2                      1282 passed
full pytest, run 3                      1282 passed
Ruff lint                               passed
Ruff format                             passed, 158 files formatted
strict mypy                             passed, 88 source files
compileall                              passed
package wheel build                     passed
git diff --check                        passed
privacy/hostname/credential scan        passed
execution gates                         eleven, all false
independent v8 source-closure digest     matched
Phase 8B frozen artifact digest         matched
document-contract mutation              killed and restored byte-identically
```

`pre-commit --all-files` reproduced the already recorded baseline-only failure:
its pinned Ruff 0.12.4 reports `UP038` at the untouched
`tests/test_phase8b_runtime.py:770`. The repository's configured current Ruff
0.15.16 passes the complete `src tests` tree. The historical Phase 8B test was
not changed as part of this U1 documentation/evidence PR.

## Only safe next action

Stop. Any retry requires a new explicit authorization and a new `v002` prefix
and wheelhouse. Its document-first contract must distinguish calculator
invocations from requested energy/force properties and predefine whether each
endpoint uses one combined `calculate(properties=["energy", "forces"])` call or
two ASE property accesses. The existing `v001` prefix and wheelhouse are retained
failure evidence and cannot be reused.
