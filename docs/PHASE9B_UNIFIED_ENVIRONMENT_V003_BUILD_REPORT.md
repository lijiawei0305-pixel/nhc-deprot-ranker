# Phase 9B-U3 Unified Environment v003 Build Report

Phase 9B 统一环境 v003 已 fail closed；measurement qualification 或后续冻结 gate 未通过，没有进行事后修补、重解释或自动重试，也未进入 Phase 9B 科学执行。

## Terminal result

```text
status                         failed_before_environment_creation
measurement qualification      failed
v003 prefix created             no
v003 wheelhouse created         no
v003 cache created              no
artifact download               none
environment build               not started
scientific execution            none
```

The document-first contract merged as PR #52 before this read-only server
operation. One remote process then used the exact merged helper source (SHA256
`194f628d6182b96ee268e7a172cd4ca617aabb0f8a66a4023ced24cd5e11eb0b`)
to capture the frozen six protected objects twice each. The three registered
v003 paths were absent before and after qualification.

All six A/B pairs had exact schema-keyset, projection-keyset,
projection-byte, and projection-SHA equality. Nevertheless, every pair had the
stable capture state `invalid`, not the required `present`, so all six
qualification results were `failed`. The state was decoded locally from the
retained projection SHA against the helper's three explicit sentinel states;
this did not rerun or alter the remote qualification.

The structured terminal failure is:

```text
code       PROTECTED_SNAPSHOT_CAPTURE_FAILURE
stage      measurement_qualification
assertion  all protected qualification snapshots have state == present
objects    all six frozen protected objects
```

This is a measurement-system qualification failure. It is not an environment
dependency, native-library, package, or AIMNet2 incompatibility result, because
v003 was never created and none of those gates ran.

## Frozen questions answered

1. Measurement qualification did not pass.
2. v003 was not created.
3. Prefix, wheelhouse, and cache stayed absent.
4. U1, U2, and source environments received no U3 write. Their formal
   before/after content comparison did not run because qualification stopped
   before resource creation.
5. U3 package versions were not observed; installation did not start.
6. No U3 artifact bytes were downloaded or hashed.
7. Import-order and native gates did not run.
8. Model load, property reads, and calculator calls were all zero; capability
   did not run. Base-model forward calls remain `unmeasured`.
9. No endpoint energy, force, or coordinate operation ran.
10. No capability cache or network trace ran. The qualification itself created
    no v003 cache and performed no artifact/network download.
11. Every A/B keyset comparison was true, but each capture state was `invalid`;
    the required `present` state failed.
12. All six A/B projection equality checks were true, but they compare stable
    invalid-state observations and therefore do not qualify the metrology.
13. Target lifecycle did not begin; initial v003 state remained absent.
14. The public terminal record carries a non-empty code, stage, assertion,
    object list, and details digest.
15. No environment canonical SHA256 exists.
16. Runner source remains v8 with SHA256
    `5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2`.
17. U3 cannot enter Unified Environment Identity Integration.
18. All eleven public execution gates remain false.
19. Production high-fidelity labels remain **71**.
20. No further work is authorized for U3; a new attempt would require new
    explicit authorization and a new identity. U3 must not be repaired or
    rerun.

No optimizer, PySCF kernel/gradient, D3 calculation, Postflight, closed-gate
rehearsal, permit, or label ran.

## Forward link (U3 remains immutable)

The separately authorized U4 design is
`PHASE9B_UNIFIED_ENVIRONMENT_V004_PLAN.md`. It introduces a new helper identity
and explicit symlink/capture diagnostics. This link does not change U3's
status, helper, receipt, manifest, or conclusion and does not authorize a v003
retry.

Forward link only: the unified-environment strategy is now closed after U5; see
`PHASE9B_UNIFIED_ENVIRONMENT_STRATEGY_CLOSEOUT.md`. U3 remains
`failed_before_environment_creation` without reinterpretation.
