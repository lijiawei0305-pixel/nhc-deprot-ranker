# Phase 9B-U2 — Unified Environment v002 Build Report

## Outcome

**Phase 9B 统一环境 v002 已 fail closed；预注册计数语义未被事后修改，所有能够持久化的 build、native、endpoint 和 cache 证据均已保留，未进入 Phase 9B 科学执行。**

The retained terminal status is `rejected_environment`. The environment was
not retried, repaired, deleted, reused, reinterpreted, or replaced by v003.
Its prefix, wheelhouse, attempt cache, receipts, traces, and built wheel remain
private retained evidence.

The calculator capability itself matched every frozen U2 count. Rejection came
from the protected-state canonical snapshot gate: Stage 0's snapshot helper did
not emit a top-level `state` field, while the Stage 4 helper emitted
`state="present"`. The canonical payload SHA therefore differed for all six
protected objects even though their tree digest, file count, regular bytes,
mtime summary, Python identity, conda history/specification, pip freeze, and
critical METADATA/RECORD content matched.

This is a preregistered metrology-contract failure, not evidence of dependency
incompatibility, native-library failure, AIMNet2 failure, or actual protected
package drift. It cannot be fixed or reinterpreted inside U2.

## New resources

```text
logical name    nhc-phase9b-unified-v002
prefix          <REMOTE_PROJECT_ROOT>/env/conda/phase9b_unified_v002
wheelhouse      <REMOTE_PROJECT_ROOT>/private/wheelhouse/phase9b_unified_v002
attempt cache   <REMOTE_PROJECT_ROOT>/private/cache/phase9b_unified_v002
```

All three were absent before U2 and are retained after rejection. The clone
used project MLFF only, offline and in copy mode. It shared zero regular-file
inodes with v001. No v001 prefix, wheel, cache, log, receipt, native map, or
capability output was copied or reused.

## Build and artifacts

Exact installed versions:

```text
Python              3.11.15
Torch metadata      2.8.0
Torch runtime       2.8.0+cu128
CUDA                12.8
GPU architecture    sm_70
AIMNet               0.2.0
ASE                  3.29.0
PySCF                2.13.1
geomeTRIC            1.1.1
pyscf-dispersion     1.5.0
NumPy                2.4.6
SciPy                1.17.1
h5py                 3.16.0
```

U2 newly downloaded its own official artifacts from `files.pythonhosted.org`:

```text
PySCF wheel
27b991d37ff16137d28b7210f678f8a027264cb66590afdd2002c5b69001f8b3

geomeTRIC sdist
c712c4102bb9db4afab4c7a482289a13d04989735cc1430c89ebb73d587d1d8b

pyscf-dispersion wheel
c65aa46f24005794bf8198205a0d83f3431a23333868fbafff43bd82efc2294d
```

The newly rebuilt v002 geomeTRIC wheel is 408,348 bytes, SHA256
`9595f639e2ad7c6d1b6afed681b8a898196978319741a8a309b7ae405d904f42`.
It was not required to match U1's built wheel and did not reuse it. Installation
used `--no-index --no-deps`; `pip check` and independent metadata dependency
validation passed. Protected packages showed zero version drift.

## Import-order and native-library results

Both fresh processes returned zero with empty stderr:

```text
ML-first       compatible, 29 normalized native entries
PySCF-first    compatible, 29 normalized native entries
```

The cross-order native manifests were equal. Each carried 2 OpenMP, 5 BLAS,
5 CUDA, 8 Torch, 8 PySCF, and 1 dispersion-classified mapping. No v001 path,
source-environment site-packages, GPU-PySCF/molecular site-packages,
unregistered `LD_LIBRARY_PATH`, symbol error, or crash appeared. The two OpenMP
and multiple BLAS mappings were recorded and were deterministic across both
orders; the gate did not accept solely on return code.

## Capability results

The selected device was the current lowest free exact Tesla V100-SXM2-32GB,
with 32,768 MiB total, 5 MiB used, and 0% utilization immediately before the
smoke. Its private device identity is omitted.

The base model loaded once. Cation and neutral used distinct endpoint wrappers
in frozen order. Each created fresh Atoms, read energy, then read forces:

| Endpoint | Charge/mult | Atoms | Energy (eV) | Force shape | Property reads | `AIMNet2ASE.calculate()` | Coordinates |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| cation | +1 / 1 | 26 | -38353.04313413836 | `(26, 3)` | 2 | 2 | unchanged |
| neutral | 0 / 1 | 25 | -38341.635253577624 | `(25, 3)` | 2 | 2 | unchanged |

Both energies and all forces were finite. Totals were exactly four property
reads and four observed entries to `AIMNet2ASE.calculate()`. The call triggers
were `energy, forces` for each endpoint. The count was not combined, relaxed,
or renamed.

`base_model_forward_calls` is `unmeasured`: U2 instrumented the ASE calculator
boundary, not the lower-level model-forward boundary. One model load and four
calculator calls do not prove any forward count.

No optimizer, PySCF kernel, PySCF gradient, D3 calculation, or label ran.

## Cache, network, and target environment

Before/after cache snapshots used one registered key set. The attempt-local
cache created 123 files and wrote 10,062,629 bytes. Global-cache drift was
false; source, `__pycache__`, weight directory, Torch/Hugging Face, and CUDA
global views did not drift.

Independent strace recorded zero external Internet connect/send calls. It also
recorded two local socket activities, so this report does not claim zero
network syscalls.

The exact weight remained 8,836,941 bytes with SHA256
`f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28`.
The target environment remained unchanged during imports and capability:
49,435 entries, 8,250,263,709 regular-file bytes, tree digest
`2708981006f36f8a1b25916f4f887babcf9633ad1669f9f2af68266efab90618`.

That digest is retained rejected-target evidence. Because the formal protected
snapshot gate failed, no `UnifiedExecutionEnvironmentIdentity v2` was issued
and `environment_canonical_sha256` is unavailable.

## Protected-state rejection

For all six protected objects, the actual evidence below matched:

- Python executable identity and version where applicable;
- conda history and explicit specification;
- pip freeze;
- critical METADATA/RECORD hashes;
- file count and regular bytes;
- mtime-based canonical tree digest.

The formal snapshot object did not match because only the after helper added
`state="present"`. Thus `all_six_canonical_snapshot_sha256_equal=false` and
the frozen acceptance gate rejected U2. The immutable terminal receipt is
durable, has no finally-write error, and remains `rejected_environment`.

The terminal payload carries `protected_environments_unchanged=false`, which
unambiguously identifies the failed gate, but its generic `failure_assertion`
field remained null because the mismatch was detected in the parent finally
comparison rather than the capability-child exception path. This terminal-field
defect is retained rather than patched. It does not remove the complete
`protected_after` evidence, but it is another reason the receipt must never be
presented as a validated identity.

## Execution consequences

Runner source schema remains v8 and its independently recomputed SHA256 remains
`5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2`.
No request, resources, permit, deployment, placement, launch, postflight, or
closed-gate rehearsal changed or ran. All eleven public execution gates remain
false. Production labels remain **71**.

U2 cannot enter Unified Environment Identity Integration because it was not
validated. The only allowed action after publishing this retained failure
evidence is to stop. A future attempt would require a new explicit
authorization and a new identity; this report does not create or authorize
v003.
