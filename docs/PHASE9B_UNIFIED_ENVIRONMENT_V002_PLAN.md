# Phase 9B-U2 — Unified Environment v002 Plan

## Authorization and stopping boundary

This document preregisters one independent environment-build attempt named
`nhc-phase9b-unified-v002`. It authorizes construction and bounded capability
validation of a new unified interpreter. It does **not** authorize Phase 9B
scientific execution, Item 9 postflight, Item 10 full-chain rehearsal, request
or permit mutation, deployment, launch, optimization, a PySCF kernel or
gradient, D3 evaluation, or label generation.

All eleven public execution gates remain false. Production high-fidelity
labels remain 71.

Phase 9B-U1 remains `failed_incomplete_environment`. Its prefix, wheelhouse,
cache, logs, receipts, and evidence are immutable retained failure evidence.
They may not be deleted, repaired, completed, retried, cloned, copied,
hardlinked, or reused by U2.

## Document-first gate

Before any server write, this plan, the calculator-semantics contract, the U2
remote harness, and their local tests must be reviewed through a gate-closed
pull request and merged to `main`. Local tests exercise the staged receipt
controller with fakes only; they run no chemistry and contact no server.

The server phase cannot start until that merge. The first server interaction
afterward is read-only.

## New identities and exclusive roots

```text
logical name    nhc-phase9b-unified-v002
prefix          <REMOTE_PROJECT_ROOT>/env/conda/phase9b_unified_v002
wheelhouse      <REMOTE_PROJECT_ROOT>/private/wheelhouse/phase9b_unified_v002
attempt cache   <REMOTE_PROJECT_ROOT>/private/cache/phase9b_unified_v002
```

Each path must be absent, non-symlinked, below its registered parent, absent
from the conda registry, and disjoint from every v001 inode before the first
write. U2 shares no writable cache with v001 or an existing environment. If any
root already exists, U2 stops without deletion, repair, reuse, fallback, or
automatic v003 substitution.

## Protected state

The project MLFF, project AIMNet2, project GPU-PySCF, shared molecular, U1 v001
prefix, and U1 v001 wheelhouse are read-only. Before and after U2, the harness
uses the same key set for each protected snapshot:

- interpreter and executable identity;
- conda history and explicit specification;
- `pip freeze`;
- critical distribution METADATA and RECORD hashes;
- file count, regular-file bytes, and mtime summary;
- canonical digest.

Every protected before/after digest must be equal. No drift is repaired.

## Build supply chain

The only clone source is project MLFF, cloned offline into the new v002 prefix.
The ML stack is not solved again. U2 newly obtains and verifies its own bytes
for exactly:

```text
PySCF 2.13.1 official wheel
27b991d37ff16137d28b7210f678f8a027264cb66590afdd2002c5b69001f8b3

geomeTRIC 1.1.1 official sdist
c712c4102bb9db4afab4c7a482289a13d04989735cc1430c89ebb73d587d1d8b

pyscf-dispersion 1.5.0 official wheel
c65aa46f24005794bf8198205a0d83f3431a23333868fbafff43bd82efc2294d
```

The geomeTRIC wheel is rebuilt inside v002; its actual new digest is recorded
and need not equal U1's built-wheel digest. All packages are installed offline
with `--no-index --no-deps`. `pip check`, independent metadata dependency
validation, exact versions, and protected-package zero drift are mandatory.

## Append-only evidence protocol

Every receipt is canonical JSON with its own digest, written exclusively,
fsynced with its parent directory, re-read, and compared before control
continues. Existing receipt names are never overwritten.

Stage 0 writes `attempt_header.json` before any import. It binds the attempt,
new roots, clone source, package/artifact plan, frozen counters, expected
terminal files, timestamp, and canonical digest.

Stage 1 writes `build_receipt.json` immediately after clone and installation.
It records exact versions, artifact hashes, the newly built geomeTRIC wheel,
`pip check`, metadata validation, protected-package comparison, and target-tree
digest.

Stage 2 runs ML-first and PySCF-first in separate processes. Each child writes
and verifies its own `import_ml_first.json` or `import_pyscf_first.json` before
exit. The parent writes an acknowledgement immediately after receiving each
summary. Receipts include module paths and versions, status and stderr digest,
normalized `/proc/<pid>/maps` classifications, OpenMP/BLAS/CUDA/Torch/PySCF/
dispersion libraries, environment digest, and external-network observations.
Native-map receipts must be durable and classified `compatible` before the
capability smoke starts. A zero return code alone is insufficient; unexplained
duplicate runtimes produce `unresolved` and stop.

Stage 3 writes `capability_cation.json` immediately after cation data is
collected and `capability_neutral.json` immediately after neutral. A persisted
cation receipt survives a neutral failure. Each binds endpoint chemistry, atom
order, input/output coordinate digests, coordinate invariance, energy and force
checks, property-read and calculate-call sequences, cumulative ledgers, one
shared model identity, distinct wrapper identity, weight/GPU/process identity,
network evidence, and its receipt digest. Facts are durable before terminal
count assertions.

Stage 4 is a `finally` path. Success or failure attempts writing
`global_cache_after.json`, `weight_after.json`,
`target_environment_after.json`, and `terminal_receipt.json`. The terminal
receipt lists completed and missing stages and the exact failing assertion. If
the finally evidence itself cannot be made durable, the status is
`indeterminate_evidence_failure`.

## Cache and network contract

Before/after snapshots use one identical registered key set covering the
attempt-local cache, project MLFF global cache, v002 home/cache view,
TorchInductor, Triton, CUDA ComputeCache, Torch Hub, Hugging Face,
`__pycache__`, source tree, and weight directory. Only registered files in the
v002 attempt-local cache may be created. Source, weight, bytecode, and global
cache drift are forbidden.

Receipts report attempt-local files/bytes, global-cache drift, external
Internet connect/send calls, and local socket activity separately. Acceptance
requires zero external Internet connect/send and `global_cache_drift=false`;
it does not falsely claim zero network syscalls.

## Frozen capability sequence and counts

The exact terminology and expected ledger are defined in
`PHASE9B_CALCULATOR_INVOCATION_SEMANTICS.md`. Cation `+1/1` runs before neutral
`0/1`; each fresh Atoms object reads energy then forces through a distinct
endpoint wrapper. Acceptance requires exactly four property reads and exactly
four observed `AIMNet2ASE.calculate()` entries across both endpoints, one base
model load, two wrappers, finite results, `(N,3)` forces, and unchanged
coordinates. `base_model_forward_calls` is `unmeasured`.

There is no optimizer, PySCF kernel/gradient, D3 calculation, or label.

## Terminal decision

`validated` requires every build, native, capability, cache, network,
protected-state, and target-after condition in this plan. A fully evidenced
contract mismatch is `rejected_environment`. An incomplete environment is
`failed_incomplete_environment`. Missing critical finally evidence is
`indeterminate_evidence_failure`.

Any failure is terminal for v002: no retry, repair, deletion, expectation
change, combined call, alternate GPU, fallback, reuse, or v003 creation.

On success the public evidence defines `UnifiedExecutionEnvironmentIdentity
v2`, but does not bind it to v8. The sole permitted successor is a separate
Unified Environment Identity Integration that fixes the documented invocation
semantics and binds the interpreter through resources/request/permit, honestly
rebasing runner source to v9. Only after that later phase may postflight and a
closed-gate rehearsal be considered.

## Local and server quality gates

Before the contract PR merges: U2 targeted tests, all listed count and staged
durability mutations, full pytest three times, Ruff lint and format,
compileall, strict mypy with no new errors, diff/privacy/gate scans, frozen
Phase 8B hash, and an independent v8 closure recomputation.

After server validation: all protected before/after comparisons, v001
before/after, fresh-path proof, artifact rehash, build/import/native/endpoint/
cache/terminal receipts, no-external-Internet proof, and no-unregistered-file
proof must be present before sanitized public evidence is prepared.

## Terminal outcome

U2 completed as `rejected_environment`. The build, native, capability, cache,
weight, target-after, and endpoint receipts were durable, and the frozen four
property reads/four calculator calls matched. The formal protected snapshot
gate failed because the Stage 0 helper omitted a top-level `state` key while
the Stage 4 helper emitted `state=present`. No retry, repair, reinterpretation,
deletion, reuse, v003 creation, identity integration, or scientific execution
followed. See `PHASE9B_UNIFIED_ENVIRONMENT_V002_BUILD_REPORT.md`.
