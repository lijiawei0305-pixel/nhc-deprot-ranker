# Phase 9B science pilot v002 geometry review

## Outcome

**Stage A: `INCONCLUSIVE`. Stage B was not started.**

The retained v002 neutral geometry is finite, connected, collision-free, and
more planar after AIMNet2 relaxation. Its atom order, complete bond graph, and
mapped five-membered ring are unchanged. Those observations do not support a
`DIFFERENT_BASIN_OR_INVALID` conclusion.

However, the one-shot review implementation used an incorrect torsion
convention in its final adjudication: it compared `abs(dihedral)` with 30
degrees although a planar ring under the implemented signed convention has
torsions near plus or minus 180 degrees. It therefore produced a raw
`ring_plane_continuity=false` that contradicts its own best-fit-plane evidence.
Under the frozen failure semantics, an unreliable analysis implementation is
`INCONCLUSIVE`; it does not authorize PySCF.

The raw review output is retained and bound by SHA256. It was not overwritten
or rerun. v002 remains **FAIL under the unchanged production 10-degree gate**.

## Starting identity

| Item | Identity |
| --- | --- |
| Candidate | `LBNPGYISTSLAHY-UHFFFAOYSA-N` |
| Review source commit | `16968e549bebde0f69b7cdfe91a0505344fc4c47` |
| Review source SHA256 | `4c7a8e43...dfc3e` |
| v001 result SHA256 | `769e64a2...1915` |
| v002 result SHA256 | `b1362a3...d7071` |
| v002 terminal | `FAIL` under frozen 10-degree gate |
| Review execution | local, read-only geometry analysis; no SSH |

All four XYZ files and `result.json` were regular, non-symlink, single-link
files. Their before/after file identities were stable. Cation input/final have
26 atoms; neutral input/final have 25. All coordinates are finite, all endpoint
element sequences are unchanged, and cation minus H23 has exactly the neutral
element sequence.

## Global neutral geometry

Kabsch alignment preserved the frozen atom order; it did not perform atom
matching or same-element exchange.

| Metric | Initial | Final | Delta/observation | Criterion | Outcome |
| --- | ---: | ---: | ---: | --- | --- |
| atom count | 25 | 25 | 0 | exact | pass |
| aligned all-atom RMSD | — | 0.604592 Å | — | ≤1.0 Å | pass |
| maximum aligned displacement | — | 1.170238 Å, F13 | — | ≤2.5 Å | pass |
| ring-only aligned RMSD | — | 0.110358 Å | — | diagnostic | continuous |
| shortest pair | 1.096000 Å | 1.081625 Å | −0.014375 Å | ≥0.20 Å | pass |
| shortest nonbonded pair | 1.751991 Å | 1.769173 Å | +0.017182 Å | no collision | pass |
| maximum absolute coordinate | 3.759072 Å | 4.373513 Å | +0.614441 Å | ≤100 Å | pass |
| connected components | 1 | 1 | 0 | exactly 1 | pass |
| added/removed bonds | 0/0 | 0/0 | none | none | pass |

The five largest globally aligned displacements are F13 (`1.170238 Å`), C2
index 14 (`0.969943 Å`), F20 (`0.940953 Å`), F12 (`0.931892 Å`), and F18
(`0.925922 Å`). This indicates substantial relaxation involving the
fluorinated substituents as well as the reaction centre, without a topology
change.

## Connectivity and ring identity

The review reproduced the v002 covalent-radius × `1.30` index-preserving bond
criterion.

```text
mapped five-membered cycle:
N1(8) – C2(14) – N3(15) – C(2) – C(3) – N1(8)
```

Initial and final neutral graphs each contain 25 bonds and one connected
component. There are no added or removed bonds.

```text
C2 neighbours: initial/final = [8, 15]
N1 neighbours: initial/final = [3, 9, 14]
N3 neighbours: initial/final = [2, 14, 16]
```

### Five ring bonds

| Bond | Initial | Final | Absolute delta |
| --- | ---: | ---: | ---: |
| N1(8)–C2(14) | 1.454191 Å | 1.362710 Å | 0.091481 Å |
| C2(14)–N3(15) | 1.452501 Å | 1.355208 Å | 0.097293 Å |
| N3(15)–C(2) | 1.415730 Å | 1.386032 Å | 0.029698 Å |
| C(2)–C(3) | 1.361133 Å | 1.357222 Å | 0.003911 Å |
| C(3)–N1(8) | 1.436555 Å | 1.380221 Å | 0.056334 Å |

Both C2–N bonds remain continuous and lie within the preregistered bond-change
limit. Their shortening is geometrically consistent with local relaxation
after removal of C2–H, but geometry alone does not prove an electronic bonding
mechanism.

### Five ring interior angles

| Centre | Initial | Final | Signed delta |
| --- | ---: | ---: | ---: |
| N1(8) | 100.136799° | 112.833742° | +12.696943° |
| C2(14) | 114.828608° | 102.462533° | −12.366075° |
| N3(15) | 99.938861° | 112.721563° | +12.782701° |
| C(2) | 113.472943° | 106.036164° | −7.436780° |
| C(3) | 111.380472° | 105.937641° | −5.442831° |

Angle sums are `539.757684°` initially and `539.991643°` finally. The C2
change is not isolated: it is coordinated mainly by compensating N1 and N3
angle changes. No edge is lost and the ring remains closed.

## Ring plane and C2 local geometry

| Metric | Initial | Final | Observation |
| --- | ---: | ---: | --- |
| ring RMS out-of-plane | 0.020469 Å | 0.003564 Å | more planar |
| ring maximum out-of-plane | 0.028964 Å | 0.004896 Å | more planar |
| C2 height above other-four ring plane | 0.070760 Å | 0.012483 Å | closer to plane |
| maximum torsion deviation from 0/180° | 5.088289° | 0.933197° | more planar |
| aligned plane-normal angle | — | 17.204197° | no geometric ring flip indicated |

Neutral C2 is two-coordinate, so a three-substituent pyramidalization angle is
not directly defined. The available plane-height and ring-torsion evidence
shows C2 moving toward the ring plane, not anomalously leaving it.

The raw executed adjudicator instead used maximum **absolute signed torsion**,
which was `179.825572°` for the nearly planar final ring. That convention bug
caused its false planarity rejection and is why the formal Stage A result is
`INCONCLUSIVE` rather than `SAME_BASIN_LIKELY`.

## Side chains and cation common atoms

The largest heavy-atom dihedral change was `45.330671°`; the largest
ring-to-side-chain change was `44.330364°`. No ≥120° substituent flip was
observed. The closest fluorine/reaction-centre separation was `2.756984 Å`, and
there was no new abnormal nonbonded contact.

After deleting only cation H23, the 25 common atoms have the exact neutral
element order and graph. The cation/neutral final ring-only RMSD is small
(`0.036535 Å`), while the final all-common-atom RMSD is `1.494645 Å`; the
difference is concentrated in flexible fluorinated side chains. AIMNet2 total
energies were not compared across charge/atom-count endpoints.

## Review of the 10-degree gate

The 10-degree limit first appeared in commit
`dfcc14d4962f1cc975bd9c23ab27b8f77f96ebde`, in
`src/nhc_deprot_ranker/preparation/phase9b_preopt.py`, before the first real
geometry optimization. The source comment says the mapped angle is near
101–104 degrees; it cites no paper, candidate-specific distribution,
same-basin benchmark, or physical transition analysis. The frozen neutral
input itself is `114.828608°`.

The correct evidence grade is:

```text
source-preregistered engineering heuristic / mutation-frozen
```

The 10-degree threshold is a preregistered conservative engineering structure
gate. It is not a demonstrated physical phase transition, reaction, or
potential-basin boundary, and there is no evidence that 10.000° versus
12.366075° separates two physical basins for this candidate.

The gate was **not modified**. v002 remains failed under it.

## Stage A terminal and Stage B

```text
Stage A classification = INCONCLUSIVE
failure code           = RING_DIHEDRAL_CONVENTION_MISMATCH
Stage B allowed        = false
PySCF                   = not run
```

No `science_pilot_lbn_pyscf_v003` root, handoff, PySCF input, SCF kernel, D3
calculation, endpoint energy, or deprotonation value was created.

## Evidence identities

| Private review evidence | SHA256 |
| --- | --- |
| file manifest | `1093f63d...cbc69` |
| neutral geometry metrics | `15718a0a...146e4` |
| ring/local geometry | `14563f77...5445` |
| per-atom displacement CSV | `9af88deb...c59` |
| two-frame raw-byte overlay XYZ | `d3eb7b89...f505` |
| raw executed review result | `0fb4432f...e5d4` |
| fail-closed Stage A terminal | `5b7b4341...f93b3` |

PNG was not generated because the Stage A allowed-library set did not include
a raster renderer; this does not affect the classification.

## Historical state and next step

- v001 remains `INCONCLUSIVE` and unchanged;
- v002 remains `FAIL` under the frozen 10-degree gate and unchanged;
- the production 10-degree gate and runner v9 are unchanged;
- all eleven public execution gates remain false;
- production labels remain 71;
- this review produced no label.

The only next step is to correct the single signed-dihedral planarity metric,
add a regression for planar torsions near plus/minus 180 degrees, and obtain a
new authorization for a fresh read-only adjudication. PySCF remains blocked
until a future terminal classification is exactly `SAME_BASIN_LIKELY`.
