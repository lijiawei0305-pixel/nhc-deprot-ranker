# Phase 9B-U3 — Qualified Unified Environment v003 Plan

## Scope and retained predecessors

U3 is a new environment attempt plus a new qualified metrology schema. It is
not an altered U2 expectation or a retry.

```text
U1  failed_incomplete_environment  calculator-call metrology contract
U2  rejected_environment           protected-snapshot metrology contract
```

Both remain immutable. Their prefixes, wheelhouses, caches, logs, receipts,
native maps, and capability evidence may not be deleted, repaired, completed,
retried, copied, hardlinked, reused, or reinterpreted.

This phase authorizes only measurement qualification, a new environment build,
and bounded environment capability validation. It does not authorize direct or
assisted Phase 9B science, request/resources/permit changes, deployment,
placement, launch, optimization, PySCF kernel/gradient, D3, postflight,
rehearsal, or labels. All eleven public execution gates remain false and labels
remain 71.

## Document-first gate

Before any server write, this plan, the protected snapshot schema, measurement
qualification contract, one production capture helper, structured terminal
schema, U2 retained fixture, and regression/mutation tests must be merged to
`main` through a gate-closed PR. The PR must pass the complete local quality
gate in the authorization.

## Mandatory measurement qualification

After merge, six protected conda environments are each captured twice in one
read-only process. Qualification uses the exact single helper and stable
projection described in the schema documents. All twelve captures must be
`present`, schema-valid, and pairwise projection-identical.

Qualification happens before the v003 prefix, wheelhouse, or cache exists. Any
failure ends U3 as `failed_before_environment_creation`; no artifact is
downloaded and no v003 path is created.

## New identities

Only after qualification passes:

```text
logical name    nhc-phase9b-unified-v003
prefix          <REMOTE_PROJECT_ROOT>/env/conda/phase9b_unified_v003
wheelhouse      <REMOTE_PROJECT_ROOT>/private/wheelhouse/phase9b_unified_v003
attempt cache   <REMOTE_PROJECT_ROOT>/private/cache/phase9b_unified_v003
```

All must be previously absent, non-symlinked, under the registered parent, and
absent from conda registry. None may share writable files or regular-file
hardlinks with v001 or v002. Any existing target stops U3; v004 is not created.

## Build

Project MLFF is the only clone source. The clone is offline and copy-mode. U3
newly downloads and verifies its own official bytes:

```text
PySCF 2.13.1 wheel
27b991d37ff16137d28b7210f678f8a027264cb66590afdd2002c5b69001f8b3

geomeTRIC 1.1.1 sdist
c712c4102bb9db4afab4c7a482289a13d04989735cc1430c89ebb73d587d1d8b

pyscf-dispersion 1.5.0 wheel
c65aa46f24005794bf8198205a0d83f3431a23333868fbafff43bd82efc2294d
```

geomeTRIC is rebuilt inside v003. Installation uses `--no-index --no-deps`.
Exact versions, `pip check`, independent metadata validation, protected-package
zero drift, and zero v001/v002 hardlinks are mandatory.

## Frozen environment and capability

```text
Python 3.11.15; Torch 2.8.0+cu128; CUDA 12.8; sm_70
AIMNet 0.2.0; ASE 3.29.0
PySCF 2.13.1; geomeTRIC 1.1.1; pyscf-dispersion 1.5.0
```

U3 reuses the already-correct U2 semantics without alteration: cation then
neutral, fresh Atoms, energy then forces, one model load, two distinct endpoint
wrappers, two property reads and two `AIMNet2ASE.calculate()` entries per
endpoint, four of each overall, and `base_model_forward_calls=unmeasured`.
Optimizer steps, PySCF kernels/gradients, D3 calculations, and labels are zero.

## Evidence order

Evidence is exclusive-create, no-follow, fsynced, re-read, SHA256-bound, and
manifested in this order:

1. attempt header;
2. measurement qualification receipt;
3. protected before observations;
4. build receipt;
5. ML-first import receipt;
6. PySCF-first import receipt;
7. native maps;
8. cation endpoint receipt;
9. neutral endpoint receipt;
10. cache after;
11. weight after;
12. target after;
13. protected after observations;
14. protected comparison receipt;
15. terminal receipt;
16. validated environment identity, only on success.

Assertions occur only after the evidence they assess is durable.

## Protected and target gates

Protected before/after call the exact qualified helper. Every object records
schema-keyset, projection-keyset, projection-byte, and projection-SHA equality.
No overall Boolean substitutes for per-object results.

The v003 target is not a protected object. Its independent
`TargetEnvironmentLifecycleReceiptV1` proves initial absent, post-build present,
and equality of the post-build baseline versus post-capability final identity.
Pre-build absent is never compared with post-build present as unchanged state.

## Existing successful U2 gates retained

U3 does not reduce U2 evidence: both import orders, compatible normalized native
maps, exact free V100, exact weight, both single-point endpoints, cache
before/after, external connect/send tracing, local socket accounting, and target
post-build/post-capability comparison all remain mandatory. Global cache drift
must be false and external Internet connect/send must be zero.

## Terminal decision

Qualification failure is `failed_before_environment_creation`; build failure is
`failed_incomplete_environment`; a complete but rejected environment is
`rejected_environment`; missing critical after evidence is
`indeterminate_evidence_failure`. Every failure has the structured non-null
failure object frozen by the qualification contract.

Only all twenty-one success conditions in the authorization permit `validated`
and `UnifiedExecutionEnvironmentIdentity v3`. Its path-independent canonical
SHA binds package/artifact identities, native manifest, capability, protected
comparison, target lifecycle, cache, and network evidence.

Any failure is terminal: no retry, repair, deletion, reuse, expectation change,
v004, integration, postflight, permit, or science.

Even if validated, U3 stops. The only authorized successor would be a separate
Unified Environment Identity Integration that binds the v003 interpreter,
corrects invocation prose, moves the runner schema honestly, supersedes v8
before execution, then develops postflight and the closed-gate rehearsal before
any paired-smoke authorization.

## Retained outcome

The document-first contract merged as PR #52. The one authorized read-only
measurement qualification then failed: six A/B stable projections were
pairwise identical, but every capture state was `invalid`, not `present`.
Accordingly U3 terminated as `failed_before_environment_creation`; all v003
resource paths stayed absent and no later stage in this plan ran. See
`PHASE9B_UNIFIED_ENVIRONMENT_V003_BUILD_REPORT.md`. This plan and helper may not
be modified and retried under the U3 identity.
