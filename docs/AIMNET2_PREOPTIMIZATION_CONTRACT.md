# AIMNet2 Preoptimization Contract

## Role of this stage

AIMNet2 performs the bulk of the geometry relaxation, starting from an RDKit
ETKDGv3 + MMFF94 (UFF fallback) structure and ending at a structure close to a
quantum-chemical minimum.

It exists to:

1. remove high forces and unphysical geometry left by the force field;
2. bring the structure near a quantum-chemical local minimum;
3. reduce the number of PySCF energy and gradient evaluations;
4. reduce PySCF optimization steps and wall-time;
5. raise throughput for batch high-fidelity label production.

It is **not** responsible for, and must never be described as:

- replacing the final PySCF optimization;
- replacing the final PySCF electronic energy;
- producing a deprotonation label;
- contributing energy to the label formula;
- proving that an AIMNet2 minimum is a B3LYP minimum;
- proving any structure is a frequency-verified minimum.

## Endpoint definitions

Frozen and identical to the rest of the project:

```text
cation:   total_charge = +1,  multiplicity = 1
neutral:  total_charge =  0,  multiplicity = 1
reaction: NHC-H+ -> NHC + H+
```

Both endpoints are closed-shell singlets. The neutral is a divalent
N-heterocyclic carbene.

## Charge handling — the critical interface

Total molecular charge must be passed **explicitly** to AIMNet2 for every task.

Prohibited:

- inferring charge from a filename;
- inferring charge from a directory name;
- inferring charge from atom count;
- defaulting to neutral;
- passing the cation as neutral;
- passing the neutral as cation.

This is the single most dangerous silent failure available in this pipeline.
Both endpoints are the same heavy-atom skeleton differing by one proton, so a
charge mix-up produces a plausible-looking optimized structure on the wrong
potential energy surface. Nothing downstream would flag it: PySCF would then
optimize honestly from a subtly wrong starting point, converge, and emit a
well-formed energy for a structure that was preoptimized as the wrong species.

Therefore, before any AIMNet2 call, the pipeline verifies:

```text
electron count consistent with the declared endpoint charge
endpoint is the project's closed-shell singlet definition
atomic composition matches the reaction definition
neutral has exactly one fewer target proton than cation
atom mapping consistent between endpoints
```

Any inconsistency is failure class `B3_endpoint_charge_mismatch` or
`B4_endpoint_identity_mismatch` and fails closed before inference.

If the installed AIMNet2 interface accepts total charge but **not**
multiplicity, then:

- no spin parameter is fabricated;
- the field actually accepted by the interface is recorded verbatim;
- multiplicity is retained as endpoint provenance;
- the PySCF stage continues to set `multiplicity = 1` explicitly.

## Input contract

Every AIMNet2 task carries an immutable input record:

```text
aimnet2_task_id
inchikey
candidate_id
endpoint                  (cation | neutral)
charge
multiplicity
atomic_numbers
coordinates_angstrom
atom_order
atom_order_sha256
input_xyz_sha256
parent_geometry_id
geometry_source
model_family
model_member_ids
model_weight_sha256
aimnet_version
torch_version
ase_version
device
dtype
optimizer
optimizer_settings
stopping_settings
walltime_limit
protocol_id
```

`endpoint` admits exactly two values, `cation` and `neutral`.

Coordinate units are recorded explicitly as Ångström. The model's actual input
and output units must be confirmed against the installed API during Phase
9A-R, not assumed from documentation or memory. A silent Bohr/Ångström
confusion would scale every structure by roughly 1.89 and is precisely the kind
of error that produces confidently wrong results.

`optimizer_settings` and `stopping_settings` are part of `protocol_id`. A run
whose optimizer settings are not inside protocol identity is failure class
`G2_optimizer_settings_absent`.

## Optimizer design

Phase 9A designs; it does not execute.

The first smoke uses exactly **one** frozen optimizer configuration. The
preferred interface is the ASE optimization interface with `LBFGS`, subject to
confirmation against the installed AIMNet2 version's actual, documented
interface. If that version offers a better-validated optimization entry point,
an alternative may be proposed — but only with code and documentation evidence,
not preference.

Frozen before execution:

```text
optimizer
fmax
maximum steps
maximum wall-time
trajectory interval
restart policy
deterministic settings
device
dtype
calculator model ID
ensemble handling
failure policy
```

Running several optimizers and keeping the best result is prohibited.

### On the `fmax` threshold

The threshold should be a **moderate preoptimization criterion**, not an
attempt at extreme convergence on the AIMNet2 surface.

The reasoning is that tightening `fmax` past the point where AIMNet2 and
B3LYP-D3(BJ)/def2-SVP disagree buys nothing. Beyond that point the optimizer is
refining toward a minimum of the wrong surface, spending time to move away from
the DFT minimum. The useful stopping point is where residual force is dominated
by theory-level difference rather than by unrelaxed force-field artifacts.

The specific numeric value is preregistered in the Phase 9B plan with its
justification drawn from official examples, numerical stability, the
preoptimization purpose, downstream PySCF cost, and structural deviation risk.
It is fixed before execution and is never adjusted afterward to improve the
appearance of a result.

## Output contract

Every AIMNet2 task records:

```text
aimnet2_task_id
status
failure_reason
initial_xyz
final_xyz
initial_xyz_sha256
final_xyz_sha256
trajectory
trajectory_sha256
optimizer_log
optimizer_steps
energy_evaluations
force_evaluations
initial_energy
final_energy
initial_max_force
final_max_force
converged
walltime_seconds
device
peak_gpu_memory
model_member_ids
model_weight_sha256
ensemble_energy_mean
ensemble_energy_std
ensemble_force_disagreement
connectivity_check
proton_identity_check
atom_order_check
charge_check
```

These energies serve optimization, quality control, uncertainty quantification,
and failure diagnosis **only**. They never enter the deprotonation label.

Because the carbene center is the least certain region of the AIMNet2 surface
for this chemistry, `ensemble_force_disagreement` should be retained per atom
rather than only as a scalar, so that disagreement localized at C2 is visible.

## Element admission

A candidate enters AIMNet2 preoptimization only if **both** of its endpoints
consist entirely of elements within the installed model's declared coverage.

On an unsupported element the pipeline fails closed. It must not:

- ignore the element;
- map it to another element;
- silently fall back to MMFF, UFF, or xTB;
- silently skip AIMNet2 while still reporting the run as AIMNet2-assisted;
- count the candidate in AIMNet2 success statistics.

Audited demand is recorded in `docs/AIMNET2_MODEL_IDENTITY.md`. The union
across all 401,856 candidates is `H C N O F S Cl Br`; the four Phase 7 smoke
candidates need only `H C N O F`.

## Determinism

The run must be reproducible: fixed device, fixed dtype, fixed member list,
deterministic settings where the stack supports them, and a stable
`aimnet2_task_id` derived from the input identity. Identical input must yield an
identical task ID.

## Stage boundary

A task that passes every gate here proceeds under
`docs/AIMNET2_PYSCF_HANDOFF_CONTRACT.md`. A task that fails any gate produces
no handoff, no PySCF input, and no label, and is recorded with its failure class
from `docs/AIMNET2_FAILURE_TAXONOMY.md`.
