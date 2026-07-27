# Phase 9B-U4 Unified Environment v004 Build Report

Phase 9B-U4 已在只读 measurement qualification 阶段 fail closed；新的 symlink-aware helper 保存了精确 capture diagnostic，未创建 v004 资源，也未进入环境构建或科学执行。

## Terminal result

```text
status                         failed_before_environment_creation
Q4 qualification               failed
failed objects                 all six protected objects
registered failure code        CONDA_EXPLICIT_FAILED
v004 prefix/wheelhouse/cache   absent before and after
build/import/capability        not started
scientific execution           none
```

PR #54 merged the document-first contract before the only SSH call. The call
used helper SHA256
`4e80ea845692223542a33a0bc18aae3b2363017d652f0b674c81f76bcfcc8aa5`,
captured every protected object A/B, and performed no server write, artifact
download, computational-package import, or GPU operation.

The code audit confirmed U3's pre-probe `python.is_symlink() → invalid` branch.
Q4 progressed beyond launcher resolution and the Python probe to the conda
stage for all six objects; every result reported root containment true and the
specific code `CONDA_EXPLICIT_FAILED`. Thus U4 did not repeat U3's reason-free
symlink rejection.

Every A/B pair had equal snapshot/projection keysets, projection bytes/SHA,
launcher identity decision, and resolved-executable identity decision. Those
equalities compare stable failed captures, not qualified present captures.
Every A/B state was `invalid`, so Q4 failed.

The qualification summary retained object IDs, exact registered failure code,
containment, state, hashes, and equality decisions. It did not promote the
observation-level launcher kind/chain or per-command return/stderr evidence:
failed snapshot rows carried the sentinel `launcher_kind=invalid`, depth zero,
and `resolved_executable_relative_path=invalid`. Therefore the portable record
does not distinguish `conda_executable_identity` from `conda_list_explicit` or
publish the real chain. This evidence limitation is retained, not repaired,
recomputed, or hidden; no second SSH was used.

## Frozen questions answered

1. U3's code root cause is confirmed. Q4 additionally proved the U4 helper got
   past launcher resolution, but the portable summary did not retain the real
   chain details.
2. Launcher resolution was root-contained; public launcher type/chain is
   unavailable because the failed snapshot summary emitted sentinels.
3. None of the six Q4 objects qualified as present; all A/B states were invalid
   with `CONDA_EXPLICIT_FAILED`.
4. v004 was not created.
5. No U4 package or artifact identity exists; build/download never started.
6. Import-order and native gates did not run.
7. Model loads, property reads, and calculator calls were zero;
   `base_model_forward_calls=unmeasured`.
8. No endpoint energy, force, or coordinate operation ran.
9. No v004 cache/network capability gate ran; v004 cache stayed absent.
10. Formal protected before/after did not run. Q4 A/B failed projections were
    equal but not acceptable.
11. Target lifecycle remained initial absent and did not begin.
12. Terminal failure is `CONDA_EXPLICIT_FAILED` at
    `measurement_qualification`, covering all six objects; portable diagnostic
    completeness is false and explicitly recorded.
13. No environment canonical SHA256 exists.
14. Runner source remains v8 with SHA256
    `5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2`.
15. Unified Environment Identity Integration cannot begin.
16. All eleven public execution gates remain false.
17. Production high-fidelity labels remain **71**.
18. The only allowed action is publication of this retained U4 failure and
    stop. Any future attempt requires new explicit authorization and identity;
    U4 may not be repaired or rerun.

No optimizer, PySCF kernel/gradient, D3, Postflight, rehearsal, permit, or
label ran.

## Forward link (U4 remains immutable)

The separately authorized U5 design is
`PHASE9B_UNIFIED_ENVIRONMENT_V005_PLAN.md`. It replaces external-CLI authority
with direct, read-only prefix metadata capture under a new helper/schema/Q5 and
possible v005 identity. This link does not resolve U4's unknown command
subfailure or modify its status, receipts, evidence limitation, or conclusion.
