# AIMNet2 Promotion Gates

## Purpose

Define, before any measurement exists, the complete set of conditions the
AIMNet2-assisted pipeline must satisfy before it may be used to produce
production high-fidelity labels.

Preregistration is the point. Every threshold here must be fixed before Phase
9B runs. A gate that is chosen after seeing results is not a gate.

## Gate structure

Promotion is evaluated at three levels, and all three must pass:

1. **Correctness gates** — the pipeline computes the right thing;
2. **Efficiency gates** — the pipeline is actually cheaper end to end;
3. **Reproducibility gates** — the result is not a single lucky candidate.

A failure at any level is a failure overall. There is no partial promotion and
no "promising, promote anyway" outcome.

## Level 1 — correctness gates

| # | Gate | Pass condition |
| --- | --- | --- |
| C1 | Cation charge | `total_charge = +1` demonstrably passed to AIMNet2 |
| C2 | Neutral charge | `total_charge = 0` demonstrably passed to AIMNet2 |
| C3 | Element support | every element of both endpoints inside declared model coverage |
| C4 | Numerical sanity | no NaN or Inf in any coordinate, energy, or force |
| C5 | Chemical identity | ring skeleton, key bonds, and substituent connectivity preserved |
| C6 | Proton identity | no spurious proton migration; cation keeps its proton, neutral does not regain one |
| C7 | Atom order | atom order and atom mapping unchanged end to end |
| C8 | Lossless handoff | AIMNet2 final geometry reaches PySCF with a verified hash closure |
| C9 | SCF convergence | final PySCF SCF explicitly converged for both endpoints |
| C10 | Geometry convergence | final geomeTRIC optimization explicitly converged for both endpoints |
| C11 | Label purity | the label is computed **only** from PySCF electronic energies |

C11 is not a numerical threshold but a structural property, and it is the most
important gate in this document. It is enforced by code and test, not by
inspection: no AIMNet2 energy may reach the label function under any code path.

## Level 2 — efficiency gates

The comparison is against the Route D direct-PySCF baseline measured on the
same candidate, same initial structure, and same hardware.

| # | Gate | Pass condition |
| --- | --- | --- |
| E1 | Honest total cost | `aimnet2_time + assisted_pyscf_time < direct_pyscf_time` |
| E2 | Call reduction | PySCF energy/gradient evaluations materially reduced |

E1 is stated as total cost deliberately. Reporting only the reduction in PySCF
wall-time while omitting the AIMNet2 stage would be a misleading result, and
this document forbids it. If preoptimization costs more than it saves, the
correct conclusion is that the route does not promote — which is a legitimate
scientific outcome, not a failure of the work.

The numeric margin for "materially reduced" in E2 must be preregistered in the
Phase 9B plan before execution, together with the minimum number of candidates
over which it must hold.

## Level 3 — reproducibility gates

| # | Gate | Pass condition |
| --- | --- | --- |
| R1 | Multi-candidate | success repeats on several previously unseen candidates |
| R2 | No systematic bias | no unexplained systematic deviation in final high-fidelity results |
| R3 | Fail-closed proven | induced failures fail closed and never reach the label table |

R1 explicitly forbids promoting on the strength of one successful candidate.
The candidate count and diversity requirement are fixed in the Phase 9C pilot
plan.

## The basin question

Route D and Route A start from the same initial structure but travel different
paths, so they may converge to different local minima. This is expected and is
not automatically a failure.

Preregistered handling:

- final coordinates are **not** required to match pointwise;
- final PySCF electronic energies are compared;
- chemical identity is compared;
- if the two routes reach different minima, that is reported honestly;
- the lower-energy result is **not** automatically adopted as the production
  conclusion;
- basin divergence triggers the preregistered review rule rather than an
  on-the-spot judgement.

Silently keeping whichever route gave the more attractive number would convert
an optimization-path artifact into a fabricated scientific preference.

## Interaction with the existing 71 labels

The existing 71 high-fidelity labels were produced by the legacy pipeline. Any
label produced by the AIMNet2-assisted route is produced by a different
geometry history, even though the final method, basis, dispersion, and label
formula are identical.

Before any assisted label joins the production label set, the protocol-identity
and label-conflict rules in `docs/DATA_CONTRACT.md` apply unchanged: duplicate
InChIKeys, conflicting labels, and protocol mixing must be explicitly audited
and rejected per contract. Promotion of the pipeline is **not** by itself
permission to merge its output into the existing label table.

## Non-promotion outcomes are valid

The honest possible outcomes of Phase 9B and 9C include:

- AIMNet2 preoptimization helps and promotes;
- it works correctly but is not cheaper end to end, and does not promote;
- it is cheaper but distorts chemistry, and does not promote;
- the server lacks the assets, and the route is blocked before measurement.

None of these is to be presented as a partial success, and none may be
converted into promotion by relaxing a gate written here.
