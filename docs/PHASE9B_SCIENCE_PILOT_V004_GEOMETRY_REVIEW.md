# Phase 9B science pilot v004 corrected geometry review

## Outcome

**Stage A: `SAME_BASIN_LIKELY`.** The identical retained v002 XYZ bytes were
reanalyzed after correcting only the signed-dihedral convention. Atom identity,
bond topology, the mapped five-membered ring, collision checks, global geometry,
and local C2 geometry all pass the preregistered review criteria.

This means the available geometry supports preserved connectivity, reaction-centre
identity, and continuous local relaxation. It is not a mathematical proof that the
two structures occupy one potential-energy basin. v002 remains **FAIL under the
unchanged production 10-degree gate**.

## Convention correction

The old adjudicator treated `abs(phi)` as non-planarity. Under its signed torsion
convention, planar sequences can be near 0 or plus/minus 180 degrees. v004 retains
the raw and normalized signed angle, then uses:

```text
dplanar(phi) = min(|phi|, |180 - |phi||)
```

The threshold remains 30 degrees. The final ring's largest raw absolute torsion is
`179.825572°`, while the corrected maximum distance from planar is only
`0.933197°`. Best-fit-plane evidence independently agrees: ring RMS out-of-plane
falls from `0.020469 Å` to `0.003564 Å`.

## Global neutral geometry

Kabsch alignment used the frozen atom order, with no remapping or same-element
exchange.

| Metric | Initial | Final | Criterion | Outcome |
| --- | ---: | ---: | --- | --- |
| atom count | 25 | 25 | exact | pass |
| aligned RMSD | — | 0.604592 Å | <=1.0 Å | pass |
| maximum aligned displacement | — | 1.170238 Å, F13 | <=2.5 Å | pass |
| independent ring-only RMSD | — | 0.110358 Å | diagnostic | continuous |
| shortest pair | 1.096000 Å | 1.081625 Å | >=0.20 Å | pass |
| shortest nonbonded pair | 1.751991 Å | 1.769173 Å | no collision | pass |
| connected components | 1 | 1 | exactly 1 | pass |
| added/removed bonds | 0/0 | 0/0 | none | pass |

The five largest globally aligned displacements are F13 (`1.170238 Å`), C2
index 14 (`0.969943 Å`), F20 (`0.940953 Å`), F12 (`0.931892 Å`), and F18
(`0.925922 Å`).

## Ring and C2 geometry

The fixed ring is `N1(8)-C2(14)-N3(15)-C(2)-C(3)`. Its five bonds remain present.

| Bond | Initial | Final | Absolute delta |
| --- | ---: | ---: | ---: |
| N1-C2 | 1.454191 Å | 1.362710 Å | 0.091481 Å |
| C2-N3 | 1.452501 Å | 1.355208 Å | 0.097293 Å |
| N3-C(2) | 1.415730 Å | 1.386032 Å | 0.029698 Å |
| C(2)-C(3) | 1.361133 Å | 1.357222 Å | 0.003911 Å |
| C(3)-N1 | 1.436555 Å | 1.380221 Å | 0.056334 Å |

| Ring angle centre | Initial | Final | Signed delta |
| --- | ---: | ---: | ---: |
| N1(8) | 100.136799° | 112.833742° | +12.696943° |
| C2(14) | 114.828608° | 102.462533° | -12.366075° |
| N3(15) | 99.938861° | 112.721563° | +12.782701° |
| C(2) | 113.472943° | 106.036164° | -7.436780° |
| C(3) | 111.380472° | 105.937641° | -5.442831° |

The angle sums are `539.757684°` and `539.991643°`; the C2 change is coordinated
by the other ring angles rather than accompanied by ring opening.

| Planarity metric | Initial | Final | Outcome |
| --- | ---: | ---: | --- |
| RMS out-of-plane | 0.020469 Å | 0.003564 Å | more planar |
| maximum out-of-plane | 0.028964 Å | 0.004896 Å | more planar |
| C2 height over other-four plane | 0.070760 Å | 0.012483 Å | closer to plane |
| maximum corrected torsion deviation | 5.088289° | 0.933197° | pass |
| plane-normal change | — | 17.204197° | no ring flip |

C2 is two-coordinate after deprotonation, so a three-substituent
pyramidalization metric is not directly defined. The available plane-height,
torsion, and bond evidence shows continuous local relaxation. Geometry alone
does not establish an electronic bonding mechanism.

## Side chains and cation reference

The largest heavy-atom dihedral change is `45.330671°`; the largest
ring-to-side-chain change is `44.330364°`. No >=120-degree substituent flip or
new abnormal contact occurs. The closest final fluorine/reaction-centre distance
is `2.756984 Å`.

Deleting only cation H23 preserves the exact common 25-atom sequence. The final
cation/neutral independently aligned ring RMSD is `0.036535 Å`; the all-common
RMSD is `1.494645 Å`, consistent with larger flexible side-chain motion. No
cross-charge AIMNet2 energy comparison was made.

## The production 10-degree gate

The threshold first appears in commit
`dfcc14d4962f1cc975bd9c23ab27b8f77f96ebde`, in
`src/nhc_deprot_ranker/preparation/phase9b_preopt.py`. No literature or
candidate-specific evidence establishes 10 versus 12.366075 degrees as a
physical basin boundary. It remains a preregistered conservative engineering
gate and was not changed.

## Evidence

| Private evidence | SHA256 |
| --- | --- |
| v002 result | `b1362a3b...d7071` |
| corrected review source | `659021fb...d97f` |
| corrected review result | `f8f5cd80...f86e` |
| neutral geometry metrics | `715d1263...514a` |
| ring/local geometry | `8bce0b33...42d8` |
| per-atom displacement CSV | `9af88deb...c59` |
| review file manifest | `6dcdb8a9...01379` |

Stage B was therefore allowed and completed in the separate
`science_pilot_lbn_pyscf_v004` continuation. No AIMNet2 calculation was rerun.
