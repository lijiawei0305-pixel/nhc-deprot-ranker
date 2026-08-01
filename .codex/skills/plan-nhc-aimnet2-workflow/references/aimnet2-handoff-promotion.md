# AIMNet2 Stopping, Handoff, Preconditioner, and Single-Point Promotion Contract

## Purpose and scientific boundary

Freeze one of two different route modes before optimizing any validation or
final-test structure:

```text
PRECONDITIONER_FULL_PARENT_OPT
SINGLE_POINT_ONLY_CANDIDATE
```

The first mode uses AIMNet2 only to condition the starting geometry for a
mandatory full parent-level PySCF/geomeTRIC optimization. The second mode is the
more demanding candidate route described below. A result from the first mode
must never inherit the claims or stopping predicates of the second mode.

For `PRECONDITIONER_FULL_PARENT_OPT`, the frozen Phase 9B pilot contract is:

```text
frozen initial XYZ
-> AIMNet2 / ASE LBFGS, Fmax <= 0.10 eV/Angstrom, at most 100 steps
-> exact-byte geometry handoff
-> full Parent-Level P01 PySCF/geomeTRIC geometry optimization
-> Parent-Level P01 final electronic-energy evaluation
```

The AIMNet2-side `GAU_LOOSE` profile requires all five quantities on the
AIMNet2 potential-energy surface: absolute energy change, gradient RMS,
gradient maximum, displacement RMS, and displacement maximum. The exact values
and units are uniquely owned by `docs/PHASE9B_AIMNET2_GAU_LOOSE_V001.yaml`.
The ASE force cap `Fmax <= 0.10 eV/Angstrom` is an additional frozen cap in the
same profile, not a parent-level threshold.

Passing this AIMNet2 profile means only `AIMNET2_PRECONDITIONER_READY`.
It does not mean that the parent-level geometry is converged and it does not
authorize skipping the parent-level optimization.

The preconditioner handoff additionally requires finite energy, coordinates
and complete forces; unchanged ordered atoms, charge, multiplicity and proton
identity; unchanged allowed connectivity; no collision or fragmentation; a
strictly sub-limit accepted step; and exact-byte handoff. Step-limit exhaustion
without the force gate is `AIMNET2_LIMIT_REACHED` and cannot hand off.

Assess preconditioner value with three non-interchangeable comparisons:

- P01 gradient at the AIMNet2 handoff geometry versus P01 gradient at the same
  frozen initial geometry;
- fine-tuned AIMNet2 versus epoch 0/base AIMNet2 under the identical optimizer
  and stopping contract;
- full assisted P01 optimization versus pure P01 optimization starting from
  the identical frozen initial bytes, using optimization steps, energy and
  gradient calls, cumulative SCF cycles, and end-to-end wall time.

Both routes must finish the same parent-level optimization/final-energy
milestone before their labels are compared. The signed label difference is an
accuracy check on the preconditioner path, not an AIMNet2 label. Promotion from
this route is `PRECONDITIONER_VALIDATED`; `single_point_only_eligible` remains
false.

Do not launch a separate parent static calculation to judge the handoff. Reuse
the first successful energy and analytic gradient produced by the same full
PySCF/geomeTRIC optimization that continues to final convergence. Because that
first observation has no preceding parent energy or displacement, call it only
`PARENT_GAU_LOOSE_GRADIENT_CHECK`. Public evidence exposes `profile:
GAU_LOOSE`; its fixed internal expansion is GRMS `1.7e-3 Eh/Bohr`, Gmax
`2.5e-3 Eh/Bohr`, with both required.

If both pass, record `HANDOFF_CALIBRATION_PASS`. If either misses while SCF,
gradient, geometry, identity, topology, charge, and multiplicity remain valid,
record `HANDOFF_CALIBRATION_MISS`. Both states continue the same optimization
to final `GAU`, then the required final parent single point. Any invalid or
unavailable parent SCF/gradient/geometry/identity condition is
`FAILED_PARENT_HANDOFF`, with a specific reason, and stops. Only a completed
final optimization plus final single point may record
`FINAL_PARENT_GAU_CONVERGED`.

The remainder of this contract applies to `SINGLE_POINT_ONLY_CANDIDATE` unless
it explicitly says otherwise.

Promote AIMNet2 only as a geometry generator for this path:

```text
frozen initial XYZ
-> frozen AIMNet2 generation and optimizer
-> exact-byte geometry handoff
-> Parent-Level P01 energy plus analytic-gradient evaluation
-> P01 single-point electronic deprotonation label
```

Never promote AIMNet2 energy as a parent energy or label component. Never call
an AIMNet2 minimum a P01 minimum. Single-point-only promotion does not authorize
production labels, production-table insertion, or silent pooling with
pure-PySCF-optimized references.

## 1. Freeze the AIMNet2 stopping contract

Bind the following before validation or final-test optimization:

- frozen model-generation ID and bundle SHA256;
- explicit endpoint charge, multiplicity, atom map, and initial XYZ SHA256;
- optimizer, all optimizer settings, maximum steps, wall limit, restart policy,
  device, dtype, and deterministic settings;
- external Coulomb and two-body D3(BJ) energy/force definitions;
- complete-force stopping metric, threshold, evaluation interval, and tie rule;
- accepted-step energy-change rule with total and per-atom absolute delta,
  consecutive-pass streak length, and exact reset behavior;
- aligned RMS and maximum displacement bounds from the initial and preceding
  accepted geometries;
- optimizer-health rules for oscillation, repeated/non-progressing frames,
  rejected steps, and numerical exceptions;
- structural, disagreement/applicability, and failure gates.

Calibrate the stopping and handoff rule on training/development validation only.
Do not inherit a base-model `fmax`, step budget, or structural tolerance without
validation under the frozen fine-tuned generation. Do not change a rule after
viewing final-test.

Return exactly one endpoint stopping state:

```text
AIMNET2_CONVERGED
AIMNET2_LIMIT_REACHED
AIMNET2_FAILED
```

Only `AIMNET2_CONVERGED` may request handoff. Treat limit exhaustion,
non-finite values, unsupported species, charge drift, optimizer error,
connectivity change, proton migration, collision, atom reorder, or missing
evidence as fail closed. Do not accept the last available frame as converged.

For `SINGLE_POINT_ONLY_CANDIDATE`, require all stopping predicates on the same
accepted step:

~~~text
finite energy, coordinates, and forces
AND final Fmax passes its frozen threshold
AND total |delta E| passes for the frozen consecutive-step streak
AND per-atom |delta E| passes for the same streak
AND RMS and maximum displacement pass
AND optimizer health passes with no oscillation/non-progress condition
AND atom order, connectivity, collision, proton, and finite-coordinate gates pass
AND accepted step index is strictly less than maximum steps
~~~

Energy stabilization cannot replace the force gate, and the force gate cannot
replace energy stabilization. Reaching the maximum step count is
AIMNET2_LIMIT_REACHED, even if the final frame happens to satisfy a subset of
the predicates.

Track three separate achievement states:

- AIMNET2_CONVERGED: the frozen AIMNet2 stopping and structure contract passed;
- AIMNET2_CLOSE_TO_PURE_PYSCF: validation against closed pure-PySCF references
  also passed the frozen parent-gradient, geometry, endpoint-penalty, and
  label-error gates;
- SINGLE_POINT_ONLY_ELIGIBLE: a frozen model generation passed the same complete
  route on its one-time unopened final-test cohort and every
  applicability/reliability gate.

Never promote directly from the first state to the third.

## 2. Prove the handoff

Transfer durable XYZ bytes only. Require equality of AIMNet2 final XYZ SHA256
and P01 input XYZ SHA256, or an explicitly authorized canonical-coordinate
closure that separately proves identical ordered elements, coordinates, charge,
and endpoint. Do not re-center, rotate, round, reorder, repair, minimize, or
substitute a conformer between stages.

Before P01 evaluation, recheck ordered atom identity, cation/neutral proton
relationship, C2/N1/N3 map, charge, multiplicity, electron count, supported
elements, connectivity, collisions, finite coordinates, and every frozen
structure gate. A handoff pass is per endpoint and per attempt; it is not model
promotion.

## 3. Measure against pure-PySCF references

For validation and final-test candidates, begin both routes from the same frozen
initial XYZ. Compare the assisted single-point route with the closed
`pure_pyscf_reference` route from `reference-data-contract.md`.

Measure and preserve, by candidate and endpoint:

- AIMNet2 optimization completion and failure class;
- P01 analytic-gradient norm and maximum component at the handed-off geometry;
- aligned all-atom, heavy-atom, and reaction-centre geometry metrics;
- connectivity, collision, proton identity, and C2-centred geometry;
- signed endpoint energy penalty
  `E_assisted_geometry_SP - E_pure_PySCF_optimized_SP`;
- signed label error
  `label_assisted_geometry_SP - label_pure_PySCF_optimized_SP`;
- absolute error as a secondary view, without replacing signed quantities;
- candidate-level success rate, systematic direction, and frozen efficiency
  metrics when efficiency is part of promotion authority.

Compute the assisted label only from the two P01 single-point electronic
energies under the repository-frozen formula. AIMNet2 energies and forces remain
diagnostic.

## 4. Apply promotion gates in order

Require all of these independent gates:

1. model/export/runtime identity and external-physics parity;
2. AIMNet2 stopping-contract compliance;
3. exact handoff and chemical-identity preservation;
4. parent-gradient acceptance at both handed-off endpoints;
5. geometry and reaction-centre acceptance;
6. signed endpoint-penalty acceptance;
7. signed deprotonation-label-error and systematic-bias acceptance;
8. validation success relative to unchanged base AIMNet2;
9. one-time final-test acceptance on unopened candidates;
10. any separately frozen reliability, domain, and efficiency requirements.

Use only numerical thresholds frozen before the relevant measurements. If a
required threshold is absent, ambiguous, contradictory, or chosen after seeing
results, return `PROMOTION_BLOCKED`. A good mean cannot override an individual
hard failure. Do not trade a failed chemistry, gradient, or label gate for
speed.

If parent-gradient acceptance fails, produce no single-point-only label. A
separately authorized pure-PySCF optimization may create a reference result,
but it is a different route and must not be counted as assisted-route success or
as a retry.

## 5. Keep protocol and status distinctions explicit

Before promotion, record AIMNet2-geometry/P01-single-point output under a
distinct assisted-geometry protocol ID. Never silently identify it with the
pure-PySCF-optimized P01 protocol. Promotion establishes bounded empirical
acceptability for the registered domain; it does not make the two geometry
histories identical.

Distinguish:

```text
TRAINING_COMPLETE
SCIENTIFICALLY_VALIDATED
SINGLE_POINT_ONLY_PROMOTED
```

The first proves artifact creation, the second proves development-validation
selection, and the third requires frozen-model final-test plus every promotion
gate above. None implies `production_accepted` or permission to modify the
production label table.
