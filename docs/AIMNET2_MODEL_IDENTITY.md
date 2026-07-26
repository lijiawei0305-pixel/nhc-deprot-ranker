# AIMNet2 Model Identity and Element Coverage

## Purpose

Fix what must be known and recorded about the AIMNet2 model before it may be
used, and record the audited element demand of this project's candidates.

Model choice is frozen: AIMNet2. Model *identity* — which weight, which
version, which ensemble — is not yet frozen and cannot be frozen from
documentation alone.

## Identity is not a name

A model name is not evidence. Before any Phase 9B execution, every field below
must be established from the actual installed environment by the Phase 9A-R
read-only preflight, never from memory, publication, or naming convention:

```text
model registry name
model family
ensemble member IDs
weight file path
weight byte size
weight SHA256
model version string
aimnet package version
torch version
ase version
python version
CUDA version
device support (CPU / GPU)
deterministic-mode support
declared element coverage
charge input mechanism and parameter name
energy output unit
force output unit
ensemble mean energy support
ensemble mean force support
member disagreement availability
license
```

The priority target is the official `wB97M-D3` family with four members:

```text
aimnet2-wb97m-d3_0
aimnet2-wb97m-d3_1
aimnet2-wb97m-d3_2
aimnet2-wb97m-d3_3
```

If the installed environment holds a different official weight, that fact is
recorded and reported; the weight is **not** substituted, and the user decides.
Downloading a weight is prohibited.

### Local audit result: only member `_0` has any evidence

The read-only legacy audit found execution-verified records from 2026-07-14/15
naming exactly one weight:

```text
<HPC_USER_HOME>/.cache/aimnet/aimnet2_wb97m_d3_0.pt      ~9 MB, base pretrained
```

referenced identically in three separate legacy files. The resolved absolute
path stays in the ignored local area and is not recorded in tracked evidence. Members `_1`, `_2`, and
`_3` have **no evidence of any kind** in either project.

This matters for ensemble strategy. A four-member ensemble cannot be assumed
available; on current evidence the honest expectation is a single member, which
would force Strategy B and would make `ensemble_force_disagreement` unavailable
unless the other members are already present. Phase 9A-R must establish which
members actually exist. Downloading the missing three is prohibited.

A fine-tuned derivative also exists in the legacy project
(`nhc_final.pt`, md5 `93751e166e0653128a3306b75429bc47`, trained on the 71
molecules). It belongs to the legacy project, is not a Phase 9 asset, and must
not be adopted without a separate decision — its provenance, training set
overlap with this project's 71 labels, and licence status would all need
independent audit first.

### Environment facts recorded by the legacy audit

Execution-verified on the target host on 2026-07-14:

```text
prefix env     $WJW/env/conda/mlff        (a separate conda prefix)
aimnet         0.2.0
torch          2.8.0+cu128    sm_70 present
ase            3.29.0
h5py           3.16.0
GPU            Tesla V100-SXM2-32GB
```

Three qualifiers apply and none may be dropped:

1. The record is **stale** — nothing re-verified it after 2026-07-15.
2. It describes a conda prefix this project is **not currently permitted to
   use**. `AGENT.md` restricts server work to `molenv.sh` (the `molecular` env),
   which contains `ase` but **no torch and no aimnet**, and forbids mixing
   software stacks or installing anything.
3. This project's own most recent server preflight recorded only PySCF,
   geomeTRIC, and pyscf-dispersion. It recorded **no** torch, ase, or aimnet.

Consequence for the architecture: AIMNet2 and PySCF cannot share one
environment under current rules. The pipeline must run them as **separate
processes in separate environments with a file-based handoff** — which is
independently what `docs/AIMNET2_PYSCF_HANDOFF_CONTRACT.md` requires for
source-closure reasons. Whether using the `mlff` prefix at all is permitted is a
user decision, not an inference, and is listed in
`docs/NEXT_PHASE_AUTHORIZATION.md`.

### Recorded API surface

The legacy code calls the ASE calculator directly:

```text
from aimnet.calculators import AIMNet2ASE
AIMNet2ASE(base_calc, charge=0, mult=1, validate_species=True)
```

Two facts follow, both to be re-verified in Phase 9A-R rather than trusted:

- charge **and** multiplicity are accepted at construction time, so the cation
  and neutral endpoints can both be specified explicitly and neither has to be
  inferred;
- the ASE interface returns **eV and eV/Å**, not Hartree and Hartree/Bohr. Unit
  conversion at the boundary is therefore mandatory and must be explicit.

A separate legacy note records that AIMNet2's internal DFTD3 module also
outputs eV rather than Hartree.

## Audited element demand

Measured directly from local immutable products. Three independent methods were
used — per-row SMILES tokenization, a whole-corpus character census, and
enumeration of the substituent vocabulary — and all three agree.

| Candidate tier | Count | Element set |
| --- | --- | --- |
| Phase 7 strongly validated smoke | 4 | `H C N O F` |
| High-fidelity labels | 71 | `H C N O F Cl Br` |
| Phase 5 acquisition | 50 | `H C N O F Cl Br` |
| Full production pool | 401,856 | `H C N O F S Cl Br` |

Per-element prevalence in the full pool:

| Element | Molecules | Fraction |
| --- | --- | --- |
| C | 401,856 | 100.00% |
| N | 401,856 | 100.00% |
| O | 271,551 | 67.57% |
| F | 163,461 | 40.68% |
| S | 55,328 | 13.77% |
| Cl | 51,153 | 12.73% |
| Br | 28,176 | 7.01% |

In the 71 labels: O in 31, F in 22, Br in 4, Cl in 4, and **S in none**. In the
50 acquisition candidates: F in 46, O in 42, Br in 3, Cl in 1, and S in none.

The skeleton column has exactly one value, `imidazolium`. Sulfur enters only
through the `SMe` and `SO2Me` substituents. No phosphorus, silicon, iodine,
boron, selenium, or metal appears anywhere in the substituent vocabulary; every
`B` character in the corpus belongs to `Br`.

Hydrogen is implicit in the stored SMILES and explicit in the Phase 7 XYZ
files, where each neutral has exactly one fewer hydrogen than its cation.

### What this means

Published AIMNet2 documentation describes coverage of fourteen elements
including `H C N O F S Cl Br`. If the installed weight matches that
description, **element coverage is not a blocker at any tier**, including the
full 401,856-candidate pool.

This is a favorable audit result, and it is also a claim that must not be
trusted until verified. The preflight must read the declared element coverage
from the installed model itself. Until then the correct status is:

```text
element_coverage_status = expected_sufficient_pending_verification
```

## The real domain risk is not elements

Element coverage being satisfied does not make the chemistry in-domain. Two
properties of this project's endpoints deserve explicit attention, and neither
is detectable by an element check.

**Net molecular charge.** Every cation endpoint carries a formal `+1` and
contains `[n+]` centers; a subset also carries `[N+]`/`[O-]` zwitterionic
groups. AIMNet2 accepts total charge as an explicit input, which is the reason
it was selected, but the charge must be passed correctly rather than inferred.
See `docs/AIMNET2_PREOPTIMIZATION_CONTRACT.md`.

**Singlet carbene centers.** Every neutral endpoint is an N-heterocyclic
carbene: a divalent, closed-shell singlet carbon bearing a lone pair. This
electronic structure is uncommon in general-purpose organic training sets. The
project must assume, until measured, that AIMNet2's potential energy surface is
least reliable exactly at the C2 carbene center — which is the chemically
decisive atom for this reaction.

This is not a reason to abandon the route. The final geometry and every
reported energy come from PySCF, so an imperfect AIMNet2 surface costs
efficiency rather than correctness. But it has three concrete consequences:

1. structural validation must check the C2 center specifically, not only global
   metrics;
2. ensemble disagreement localized at C2 is a first-class diagnostic and should
   be recorded per atom, not only as a scalar;
3. if AIMNet2 systematically distorts the carbene geometry, PySCF will spend
   its residual optimization undoing that distortion, and the end-to-end
   speedup may not materialize. That outcome must be reported as a
   non-promotion, not explained away.

## Theory-level boundary

AIMNet2 and the final PySCF stage are different potential energy surfaces and
must never be described as one.

```text
AIMNet2 geometry       = preoptimized starting geometry
PySCF B3LYP-D3(BJ)/def2-SVP geometry = final high-fidelity geometry
```

Convergence on the AIMNet2 surface means only that the structure met the
preoptimization stopping condition on *that* surface. It is not evidence of
convergence on the B3LYP-D3(BJ)/def2-SVP surface, and it never substitutes for
the PySCF gradient acceptance check.

AIMNet2 energies are never added to, mixed with, corrected against, or spliced
into PySCF energies, and never enter the label formula.

## Ensemble handling

One of two strategies is frozen in Phase 9A-R, once the real interface is
known:

**Strategy A — ensemble-mean optimization.** If the installed interface
reliably provides ensemble mean energy and forces, the mean force over the four
frozen members drives the optimization, and member disagreement is recorded.

**Strategy B — single-member optimization with ensemble validation.** If no
verified ensemble optimizer interface exists, one preregistered primary member
drives the optimization, and all members are evaluated on the initial and final
structures to quantify disagreement.

Under either strategy the member list is fixed in advance. Choosing a different
member per candidate, or evaluating several members per step and keeping the
lowest-energy structure, is prohibited: both convert an uncertainty estimate
into a biased selection. Any disagreement threshold is preregistered from smoke
or pilot data and never chosen after seeing results.
