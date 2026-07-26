# Phase 9B Single-Member Safeguards

## Why this document exists

The Phase 9A design assumed an ensemble. Phase 9A-R found only member `_0`
present, and downloading the others is prohibited. Both frozen ensemble
strategies are therefore unavailable: mean-force optimization needs four
members, and single-member-plus-validation has nothing to disagree with.

This removes the designed early-warning signal — per-atom ensemble disagreement
at the C2 carbene centre, aimed at exactly the chemistry AIMNet2 is least likely
to have seen.

Phase 9B does not proceed as if that signal merely happened to be absent. It
replaces the lost statistical check with **deterministic structural checks**,
which are stricter than what an ensemble run would have needed.

## The honesty rule

```text
ensemble_members_available     = 1
ensemble_uncertainty_available = false
```

Single-member repeatability — measured in Phase 9A-I at `2.4e-7 eV` — is a
reproducibility number, not an uncertainty estimate. Every report, manifest,
figure, and summary must state that no ensemble uncertainty exists. Presenting
repeatability as uncertainty would misrepresent a known blind spot as a measured
confidence.

## Safeguard 1 — bounded displacement

Preregistered before the run:

```text
max_total_rmsd_angstrom          preoptimized vs input, per endpoint
max_single_atom_displacement     any one atom, per endpoint
max_preopt_steps
max_preopt_walltime_seconds
```

Exceeding any bound fails closed and hands nothing to PySCF.

Rationale: with no ensemble to flag an unreliable region, the only remaining
defence against the model wandering off is to refuse to travel far. A
preoptimizer that moves a 26-atom molecule a long way is either fixing a badly
broken force-field geometry or inventing a different one, and without
uncertainty we cannot tell which. Bounding displacement makes that ambiguity
non-fatal.

Numeric values are fixed in the Phase 9B execution request, justified from the
Phase 9A-I measured starting forces and the candidate's size, and never adjusted
after seeing a result.

## Safeguard 2 — explicit C2, N1, N3 bond checks

Per endpoint, before and after preoptimization, using the atom map
`{C2_carbene: 14, N1: 8, N3: 15}` rather than assumed positions:

```text
C2-N1 bond length, before and after, and its change
C2-N3 bond length, before and after, and its change
N1-C2-N3 angle, before and after, and its change
C2 coordination number
C2 attached hydrogen count   cation 1, neutral 0
```

Preregistered tolerances bound each change. The carbene centre is where the
model is least trustworthy and where the reaction is defined, so it is measured
directly rather than inferred from a global RMSD that a local distortion could
hide.

The Phase 9A-I observation that the neutral endpoint carries **2.6x** the
cation's maximum force is a hypothesis this safeguard tests, not a finding it
assumes.

## Safeguard 3 — proton identity and migration

The acidic proton is identified **by index** before preoptimization, and its
bonded heavy atom is recorded. After preoptimization the same index must remain
bonded to the same heavy atom.

Counting hydrogens is insufficient: a migration preserves the count. A proton
that moves to a ring nitrogen or a substituent heteroatom yields a tautomer that
looks clean and converged, and PySCF would then honestly optimize the wrong
molecule and emit a well-formed energy for a different reaction.

For the neutral endpoint the complementary check applies: C2 must remain
hydrogen-free, and no proton may be acquired.

## Safeguard 4 — index-preserving connectivity comparison

Connectivity inferred from the optimized coordinates must match the initial
graph **under the identity permutation** — same atom indices, not merely
isomorphic under some relabelling.

An isomorphic-but-relabelled structure would silently break the atom map, the
handoff hash closure, and the endpoint ordering invariant, while passing any
check that only asks "is it the same molecule".

Allowed: bond-length change, torsion, ring pucker, substituent reorientation.
Not allowed: bond formation, bond breaking, proton transfer, ring
rearrangement.

## Safeguard 5 — the direct-PySCF control is mandatory

Route D is not optional and is not a formality. With no ensemble uncertainty,
the direct control is the **only** independent check that Route A reached a
chemically equivalent answer.

Both routes start from the identical frozen initial XYZ and must share every
PySCF setting, resource, and failure rule. A configuration difference is failure
class `G6_route_config_mismatch` and invalidates the comparison outright.

## Safeguard 6 — residual-step and basin comparison

Recorded and compared:

```text
Route D  geomeTRIC steps, energy/gradient evaluations, SCF cycles, walltime
Route A  the same, for the residual optimization only
final electronic energy, both routes, both endpoints
final structure RMSD between routes
C2-N1 and C2-N3 bond lengths, both routes
same local minimum, or not
```

Pointwise coordinate identity is not required. Different minima are reported
honestly, are not automatically a failure, and **do not** license adopting
whichever route gave the lower energy. The preregistered basin rule governs;
picking the prettier number would convert an optimization-path artifact into a
fabricated scientific preference.

## Safeguard 7 — honest cost accounting

Phase 9A-I measured a warm-up cost that must not be hidden:

```text
first AIMNet2 call in a process   21.9 s   (includes torch.compile)
subsequent calls                   1.6 s   cation
                                   0.2 s   neutral
```

Route A's cost is therefore:

```text
total_assisted = aimnet2_process_startup
               + aimnet2_compile
               + aimnet2_optimization_steps
               + handoff_and_validation
               + pyscf_residual_optimization
```

compared against `direct_pyscf_time`. Reporting only the reduction in PySCF time
is prohibited. The roughly 20-second compile is a fixed per-process cost that
amortizes across many steps but is real for a single candidate, and it must
appear in the accounting rather than being written off as warm-up.

## What must be recorded even on success

```text
ensemble_members_available     = 1
ensemble_uncertainty_available = false
element_coverage_verified      = C F H N only
element_coverage_unverified    = O S Cl Br
carbene_training_domain        = unverified
prior_expectation              = legacy median 1.10x, non-promotion likely
```

These stay attached to any Phase 9B result. A successful run does not retire
them; it is a result obtained despite them.
