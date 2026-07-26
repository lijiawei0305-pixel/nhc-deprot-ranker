# PySCF Residual Final Optimization Contract

## What "final optimization" means here

PySCF is the **final high-fidelity optimization stage**, starting from the
AIMNet2-preoptimized structure and continuing until the frozen convergence
criteria are met.

It is explicitly **not** "run one geomeTRIC step and stop". If residual
optimization needs many steps to converge, it must be allowed to take them. The
word *residual* describes where the stage starts, not how much work it is
permitted to do.

This is the stage that produces every number this project reports.

## Frozen protocol

Unchanged from the existing runner, and identical between Route D and Route A:

```text
phase                gas
method               B3LYP
dispersion           D3(BJ)
basis                def2-SVP
grid level           3
geometry optimizer   geomeTRIC
geometry maxsteps    100
scf conv_tol         1.0e-9
cation               charge +1, multiplicity 1
neutral              charge  0, multiplicity 1
target               electronic_deprotonation_energy
label quality        electronic_energy_only
hessian_computed     false
```

The protocol is a canonically serialized dict whose SHA256 is bound into the
request, the permit, and every artifact. A request whose protocol block is not
byte-identical to the locked protocol is rejected at load.

Internally `multiplicity = 1` becomes PySCF `spin = 0` (unpaired electrons, not
`2S+1`), and only RKS is constructed. An odd electron count is rejected.

## Required behaviour

PySCF must:

1. rebuild the molecule from the AIMNet2-preoptimized structure;
2. set the endpoint charge explicitly;
3. set multiplicity 1 explicitly;
4. use the frozen B3LYP-D3(BJ)/def2-SVP settings;
5. use the frozen geomeTRIC settings;
6. dynamically verify D3(BJ) is active;
7. recompute the high-fidelity electronic energy;
8. recompute analytic gradients;
9. continue optimizing to frozen convergence;
10. explicitly verify SCF convergence;
11. explicitly verify geometry convergence;
12. retain per-step coordinates;
13. retain per-step electronic energies;
14. retain per-step nuclear gradients;
15. write the final XYZ;
16. write the final electronic energy;
17. write complete provenance.

## Prohibited behaviour

PySCF must not:

- execute a single literal geometry step and declare completion;
- skip gradient acceptance because AIMNet2 already converged;
- use an AIMNet2 energy as an initial or final value;
- register an unconverged structure as an endpoint;
- silently relax convergence criteria;
- silently raise `maxsteps`;
- silently change the SCF algorithm;
- silently restart a failed task.

The second item deserves emphasis. AIMNet2 convergence is convergence on a
different potential energy surface. It carries no information about the
B3LYP-D3(BJ)/def2-SVP gradient at that structure, and treating it as a reason to
weaken any DFT-side check would substitute the cheap surface's opinion for the
expensive one — which is exactly the error the two-stage design exists to avoid.

## Convergence must be explicit

Convergence flags are required to be **literal booleans**. A truthy proxy is
rejected as a malformed state rather than accepted, and a non-boolean value is
deliberately not retryable.

SCF convergence is checked at four independent points: inside the per-step
optimizer callback, on the last optimization SCF, on the final SCF, and again on
the returned result object. Geometry convergence is asserted by the optimizer
and re-checked explicitly afterward.

## Retry policy

Exactly one retry exists, and it is narrow:

```text
retryable:      SCF non-convergence, one SOSCF retry per endpoint, same protocol
not retryable:  geometry non-convergence
not retryable:  timeout
not retryable:  any unclassified backend error
```

Failures are classified structurally, never by inspecting an exception message.
A failed endpoint writes a failure envelope and produces no success marker.

## Dispersion must be proven, not configured

Setting a dispersion flag is not evidence that dispersion ran. The runner proves
it dynamically, and that requirement is unchanged by preoptimization:

- the dispersion adapter version is pinned;
- live activation is queried on the actual energy owner;
- under SOSCF the true inner owner is located, because the Newton wrapper
  delegates energy evaluation inward and observing the wrapper would miss the
  real hook;
- energy and gradient hooks are instrumented, and their call counts must be
  greater than zero, with finite and nonzero energies and correctly shaped
  finite gradients;
- the energy decomposition must sum to the total within tolerance, with a
  nonzero dispersion component;
- an independent SCF-free dispersion evaluation must reproduce that component.

This evidence is regenerated per endpoint per attempt. Static evidence from an
earlier phase never substitutes for it.

## Resource and identity discipline

Thread counts, thread environment, CPU affinity, memory limits, and wall-time
are frozen before the attempt and verified at runtime; a mismatch is a
configuration error rather than a warning. Runtime resource escalation is
prohibited.

Resume is prohibited: an existing output root causes refusal rather than
continuation.

For a valid comparison, Route D and Route A must run under identical resources
and identical settings. A difference is failure class
`G6_route_config_mismatch` and invalidates any measured speedup.

## Label computation

Only after both endpoints satisfy every acceptance gate:

```text
electronic_difference_kcal = (E_neutral - E_cation) * 627.509474
dft_deprot_electronic_kcal = electronic_difference_kcal - 6.28
lower_is_better            = true
```

Both quantities are retained: the label including the gas-phase proton constant,
and the constant-free electronic difference.

The runner recomputes and self-checks this arithmetic at `abs_tol = 1e-12`, and
the postflight repeats the check at the same tolerance. The separate
`0.02 kcal/mol` constant governs ingest validation of harvested legacy labels
against their stored source values and must not be applied to fresh runner
output.

Only PySCF electronic energies enter this formula. AIMNet2 energies are never
added, mixed, corrected, or spliced in.

## Honesty constraints on the result

The label is a **gas-phase electronic energy difference**, not a Gibbs free
energy, and must never be named or described as one.

No Hessian and no frequency calculation is performed. The result therefore
records `hessian_computed = false`, `frequency_status = not_computed`, and
`n_imaginary = null`. The absence of a Hessian does not invalidate an electronic
energy label, but it does mean the structure must never be described as a
frequency-verified minimum, by either stage.

Convergence of the geometry optimizer establishes that a stationary point was
reached on the B3LYP-D3(BJ)/def2-SVP surface. It does not establish that the
point is a true local minimum, and no wording in any report may imply otherwise.
