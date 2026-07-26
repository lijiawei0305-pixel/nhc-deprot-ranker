# Phase 9B Paired AIMNet2 / Direct-PySCF Smoke Plan

## Status

Plan only. Phase 9B is **not authorized** by this document. Execution requires a
successful Phase 9A-R read-only preflight, a new authority chain, and separate
explicit user authorization.

## Purpose

Measure, on one candidate, whether AIMNet2 preoptimization makes the
high-fidelity pipeline cheaper without changing what it computes.

This is a controlled paired comparison, not a model bake-off. The frozen
decision to use AIMNet2 is not revisited here. Direct PySCF appears only as the
necessary scientific baseline; including it is not model reselection.

## Candidate selection

The candidate is drawn from the **three remaining** Phase 7 strongly validated
smoke candidates. Phase 7 validated four; `QXHIEGFUWOLQIJ-UHFFFAOYSA-N` is
excluded because its Phase 8B authority chain is permanently retired.

The specific candidate, its selection reason, and both endpoint input SHA256
values are frozen in the Phase 9B authorization request before any execution.
Runtime substitution is prohibited.

Reusing the QXH request, attempt, permit, bundle, or remote root is prohibited
in every form. Phase 9B requires:

```text
new candidate selection record
new request ID
new attempt ID
new remote root
new source closure
new one-shot permit
new local invocation record
new preflight
new acceptance/rejection contract
```

## The two routes

Both routes begin from the **identical** frozen Phase 7 initial structure.

### Route D — direct PySCF baseline

```text
Phase 7 initial cation XYZ
  -> PySCF B3LYP-D3(BJ)/def2-SVP
  -> geomeTRIC optimization to frozen convergence
  -> final cation electronic energy

Phase 7 initial neutral XYZ
  -> (same)
  -> final neutral electronic energy
```

### Route A — AIMNet2-assisted PySCF

```text
same Phase 7 initial cation XYZ
  -> AIMNet2 preoptimization (total_charge = +1)
  -> structure validation gates
  -> PySCF B3LYP-D3(BJ)/def2-SVP
  -> geomeTRIC residual optimization to the SAME frozen convergence
  -> final cation electronic energy

same Phase 7 initial neutral XYZ
  -> AIMNet2 preoptimization (total_charge = 0)
  -> structure validation gates
  -> (same)
  -> final neutral electronic energy
```

## Controlled variables

Everything except the presence of the AIMNet2 stage must be identical:

```text
initial structure          identical
atom order                 identical
charge                     identical per endpoint
multiplicity               identical (1)
method                     B3LYP
basis                      def2-SVP
dispersion                 D3(BJ)
SCF convergence            identical
geometry convergence       identical
geomeTRIC maxsteps         identical
wall-time limit            identical
hardware                   identical
thread configuration       identical
CPU affinity               identical
memory limit               identical
failure semantics          identical
```

A configuration difference between the routes invalidates the comparison and is
failure class `G6_route_config_mismatch`.

## Execution order and independence

The two routes are separate attempts under the same authorization, each with
its own attempt identity and its own result tree. Neither may read the other's
intermediate state, reuse its wavefunction, or inherit its convergence history.
Route A must not be seeded by Route D's converged geometry, and Route D must
not be run second "to confirm" Route A.

## Measurements

Recorded separately for cation and neutral.

### AIMNet2 stage

```text
optimizer steps
energy evaluations
force evaluations
wall-time
initial max force
final max force
converged (bool)
ensemble energy mean
ensemble energy std
ensemble force disagreement
device and peak memory
structural integrity result
proton identity result
failure reason if any
```

### PySCF stage

```text
geometry optimizer steps
energy/gradient evaluations
total SCF cycles
wall-time
CPU/GPU resources and peak memory
SCF failure count
geometry convergence status
final max gradient
final electronic energy
final structure
timeout status
```

### End to end

```text
total_assisted_time = aimnet2_time + assisted_pyscf_time
direct_pyscf_time
```

The comparison is `total_assisted_time` against `direct_pyscf_time`. Reporting
a reduction in PySCF time alone, without the AIMNet2 cost included, is
prohibited.

## Scientific consistency comparison

Between Route D and Route A:

- final cation electronic energy;
- final neutral electronic energy;
- final deprotonation electronic energy;
- final structure RMSD;
- key bond lengths;
- NHC ring geometry;
- proton position;
- chemical connectivity;
- whether both routes reached the same local minimum;
- whether either found a distinct, lower PySCF minimum;
- evidence of basin dependence.

Pointwise coordinate identity is **not** required. Different minima are
reported honestly, are not automatically a failure, and do not license
selecting the lower-energy route as the production answer. The preregistered
basin rule in `docs/AIMNET2_PROMOTION_GATES.md` governs.

## Label handling

A label may be produced only if **both** endpoints of a route satisfy every
acceptance gate. The label is computed only from PySCF electronic energies:

```text
dft_deprot_electronic_kcal =
    (E_neutral_hartree - E_cation_hartree) * 627.509474 - 6.28
```

with the accompanying constant-free difference retained and
`lower_is_better=true`.

Two distinct tolerances apply and must not be confused:

```text
runner self-consistency (two_endpoint.py)  abs_tol = 1e-12
legacy label ingest     (constants.py)     abs_tol = 0.02 kcal/mol
```

The runner recomputes its own label from its own endpoint energies and holds
itself to `1e-12`; the postflight repeats that check at the same tolerance. The
`0.02 kcal/mol` constant is `LABEL_FORMULA_ATOL_KCAL_MOL`, used by the data
layer to validate *harvested legacy* labels against stored source values. It
does not govern runner output. Applying the looser ingest tolerance to fresh
runner results would silently permit arithmetic drift the runner is designed to
reject.

AIMNet2 energies never enter this formula.

A Phase 9B label is a smoke result. It does not join the production label table
by virtue of existing; the data-contract protocol and conflict rules govern
that separately.

## Stopping conditions

Phase 9B stops immediately and fails closed on:

- any failure class in `docs/AIMNET2_FAILURE_TAXONOMY.md`;
- any drift between planned and actual protocol identity;
- any attempt to alter frozen thresholds mid-run;
- any resource increase requested at runtime;
- any second attempt for the same endpoint.

There is no retry. As in Phase 8B, the permit is consumed irreversibly before
spawn, and a consumed permit is never restored.

## Explicit non-goals

Phase 9B does not compare other machine-learning potentials, does not tune
AIMNet2, does not calibrate AIMNet2 against DFT, does not compute Hessians or
frequencies, does not claim frequency-verified minima, and does not promote the
pipeline to production. Promotion requires the Phase 9C pilot.
