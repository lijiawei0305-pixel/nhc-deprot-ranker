# Phase 9B AIMNet2 Preconditioner Route Audit

## Decision

The current target route is frozen conceptually as:

```text
frozen initial geometry
-> AIMNet2 / ASE LBFGS to the frozen AIMNet2 GAU_LOOSE profile
-> identity, topology, and finite-coordinate gates
-> exact-byte handoff
-> full Parent-Level P01 PySCF/geomeTRIC optimization
-> first successful parent energy/analytic gradient classified in place
-> continue the same optimization to final GAU
-> final Parent-Level P01 electronic energies and deprotonation label
```

The AIMNet2-side `GAU_LOOSE` profile requires the five frozen geomeTRIC-style
metrics—energy change, Cartesian gradient RMS and maximum, and Cartesian
displacement RMS and maximum—plus the ASE `Fmax <= 0.10 eV/Angstrom` cap. All
are measured on the AIMNet2 potential-energy surface. Passing them means only
that preconditioning is complete. It does not mean parent-level convergence,
does not authorize a final single point without geometry optimization, and
does not make AIMNet2 energy part of the label.

The first successful parent energy and analytic gradient are taken from the
same cold-start PySCF/geomeTRIC optimization that continues afterward. This is
`PARENT_GAU_LOOSE_GRADIENT_CHECK`, not full parent `GAU_LOOSE`: no preceding
parent energy change or displacement exists. The public profile is
`GAU_LOOSE`; its one fixed internal expansion requires both GRMS `<= 1.7e-3`
and Gmax `<= 2.5e-3 Eh/Bohr`. `HANDOFF_CALIBRATION_PASS` and
`HANDOFF_CALIBRATION_MISS` both continue to final parent `GAU` and the required
final single point. Only invalid SCF, gradient, geometry, identity, charge,
multiplicity, or topology is `FAILED_PARENT_HANDOFF` and stops.

## Corrected baseline semantics

The phrase "relative to epoch 0 or the original initial state" contains three
different comparisons and must not be implemented as one interchangeable
baseline:

| Question | Required baseline |
| --- | --- |
| Did AIMNet2 reduce the parent-level starting gradient? | P01 gradient on the same endpoint's frozen initial geometry |
| Did fine-tuning improve AIMNet2? | unchanged base AIMNet2 (`epoch_0000`) under the identical optimizer/stopping contract |
| Did preconditioning reduce expensive PySCF work? | pure P01 optimization from identical frozen initial XYZ bytes |
| Did the final scientific result change? | signed label difference against the pure-P01-optimized protocol-level reference |

## Frozen and unresolved fields

The user has frozen the role, optimizer, complete AIMNet2 `GAU_LOOSE` profile,
step budget, mandatory full-P01 handoff, first-parent classification, final
parent `GAU`, and `single_point_only=false`. Chemical identity, exact-byte
handoff and fail-closed limit behavior remain hard gates.

Four numeric scientific decisions remain unresolved: the minimum meaningful
parent-gradient reduction, the minimum meaningful PySCF compute-burden
reduction, the wall-time margin under a fair paired benchmark, and the maximum
allowed signed final-label difference. They cannot be inferred from Fmax or
chosen after final-test. Until they are preregistered, a new model generation
remains `BLOCKED_BEFORE_TRAINING` under the current model-generation contract.

## Current execution readiness

The existing V002 generation is terminal `BLOCKED_BEFORE_TRAINING` and cannot
be edited back to `REGISTERED`. Its original nine-candidate collection is also
not closed: one train candidate is a terminal timeout and two parent-level
jobs remain active at the time of this audit. A first calibration or production
model attempt must therefore use a separately registered generation after the
development cohort is closed and its immutable dataset is assembled.
