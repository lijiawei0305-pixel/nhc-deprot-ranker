# Phase 9B-U4 — Symlink-Aware Metrology and Unified Environment v004 Plan

## Immutable predecessors and scope

```text
U1  failed_incomplete_environment
U2  rejected_environment
U3  failed_before_environment_creation
```

All predecessor resources, evidence, code identities, and conclusions remain
unchanged. U4 is a new helper, qualification, request, attempt, logical name,
prefix, wheelhouse, cache, receipts, and possible identity—not a v003 retry.

This phase authorizes only read-only qualification and, only after it passes,
environment build and bounded capability validation. It does not authorize
runner/request/resources/permit edits, deployment, launch, optimization,
PySCF kernel/gradient, D3, Postflight, rehearsal, or labels.

## Document-first and Q4 gates

Before any SSH, the U4 helper, tests, V3 snapshot schema, diagnostic contract,
qualification V2 contract, and this plan must pass the full local gate and
merge to `main`. The exact merged helper bytes then run once as Phase 9B-U4-Q
over all six protected environments. No v004 resource exists during Q4.

Q4 failure is terminal `failed_before_environment_creation`. Only six present,
diagnostic-free, projection-identical A/B pairs may unlock resource creation.

## New v004 resources

```text
logical name  nhc-phase9b-unified-v004
prefix        <REMOTE_PROJECT_ROOT>/env/conda/phase9b_unified_v004
wheelhouse    <REMOTE_PROJECT_ROOT>/private/wheelhouse/phase9b_unified_v004
cache         <REMOTE_PROJECT_ROOT>/private/cache/phase9b_unified_v004
```

All three must be absent and non-symlinked. U4 cannot clone or reuse v001/v002,
their artifacts, built wheels, caches, logs, or receipts. Project MLFF remains
the sole clone source; copy mode and zero shared regular-file hardlinks are
mandatory.

## Build and capability

After Q4 only, U4 repeats the proven U2 route: copy-mode offline clone, fresh
official PySCF 2.13.1/geomeTRIC 1.1.1/pyscf-dispersion 1.5.0 artifacts with the
frozen SHA256 values, fresh geomeTRIC wheel, `--no-index --no-deps`, `pip check`,
independent metadata validation, and protected-package zero drift.

The frozen stack remains Python 3.11.15, Torch 2.8.0+cu128, CUDA 12.8/sm_70,
AIMNet 0.2.0, ASE 3.29.0, PySCF 2.13.1, geomeTRIC 1.1.1, and
pyscf-dispersion 1.5.0.

Capability retains every successful U2 gate: both import orders and compatible
native maps, exact idle V100, exact local weight, one model load, two wrappers,
cation then neutral, energy then forces, four property reads and four
`AIMNet2ASE.calculate()` calls, finite energy/forces, `(26,3)`/`(25,3)`,
unchanged coordinates, zero optimizer/PySCF/D3/labels, no global-cache drift,
zero external Internet connect/send, and separately reported local sockets.
`base_model_forward_calls` remains `unmeasured`.

## Protected, target, and evidence ordering

The exact Q4 helper bytes capture protected before and after. All six must stay
present, diagnostic-free, and identical in schema, projection, launcher, and
resolved executable identity. Target v004 is excluded from that equality and
uses initial-absent, post-build-present, post-capability-present lifecycle with
post-build/final projection equality.

Evidence is durable before assertion in this order: attempt header, Q4 receipt,
protected before, artifacts, build, target post-build, both imports/native
maps, cation, neutral, cache/network after, weight after, target final,
protected after, comparisons, terminal, and validated identity only on success.
Every file is exclusive-create, no-follow, fsynced, re-read, hashed, and entered
in the evidence manifest.

## Terminal decisions

Q4 failure is `failed_before_environment_creation`; build failure is
`failed_incomplete_environment`; a complete built environment failing a gate is
`rejected_environment`; missing critical evidence is
`indeterminate_evidence_failure`. Failure prohibits retry, repair, deletion,
reuse, v005, Integration, Postflight, permit, and science.

Only complete success issues `UnifiedExecutionEnvironmentIdentity v4` and a
path-independent environment canonical SHA256. Even then, U4 stops; the only
possible successor is separately authorized Unified Environment Identity
Integration. Runner source remains v8 at
`5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2`,
all eleven public execution gates remain false, and production labels remain
71.
