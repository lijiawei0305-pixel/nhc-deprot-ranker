# Phase 9A-I Candidate Selection Record

## Selected candidate

```text
inchikey: LBNPGYISTSLAHY-UHFFFAOYSA-N
source:   Phase 7 strongly validated geometry smoke
```

## Selection basis

Four candidates carry strongly validated Phase 7 geometry.
`QXHIEGFUWOLQIJ-UHFFFAOYSA-N` is excluded outright: its Phase 8B authority chain
is permanently retired and no artifact of it may be reused.

Among the three remaining, selection was by fewest atoms and simplest element
set:

| InChIKey | Cation atoms | Elements | Selected |
| --- | --- | --- | --- |
| `LBNPGYISTSLAHY-UHFFFAOYSA-N` | 26 | `C F H N` | yes |
| `HQKHXILTVGYEGE-UHFFFAOYSA-N` | 27 | `C F H N O` | no |
| `IJWCXRPLHNQISE-UHFFFAOYSA-N` | 30 | `C F H N O` | no |

`LBNPGYISTSLAHY` wins on both criteria simultaneously: it has the fewest atoms
and it is the only one of the three without oxygen.

This is an infrastructure-characterization choice. It is **not** a claim that
this candidate is scientifically preferable, chemically representative, or a
better ranking prospect than any other.

## Frozen endpoint identities

```text
cation   atoms 26   composition C9 F9 H5 N3   charge +1   multiplicity 1
neutral  atoms 25   composition C9 F9 H4 N3   charge  0   multiplicity 1
```

Endpoint XYZ SHA256, read from the tracked Phase 7 manifest and independently
reverified against the local immutable product:

```text
cation   543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286
neutral  af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8
```

Supporting Phase 7 artifacts:

```text
legacy atom map      ce0e2fc05b44e7e18a8be445ff23e398b0f6302dcfb0fe48da8f9522a1b48ab1
endpoint atom map    f614486a6ae18afed109cd0bcf52efb27b290558e758f5c2e85c8f192b70d9ab
```

## Atom mapping

```json
{"C2_carbene": 14, "N1": 8, "N3": 15}
```

**These indices are not 3, 4, 5.** The positional `N, C, N` pin at indices 3/4/5
in the Phase 8B authority module is specific to the retired QXH candidate and
does not generalize. For this candidate the ring atoms sit at 8, 14, and 15, and
any check must read the atom map rather than assume fixed positions.

Recording this explicitly prevents a plausible and expensive mistake: reusing
the QXH positional assertion here would fail on a correct structure, and
"fixing" it by reordering atoms would silently destroy the atom-order invariant
the whole pipeline depends on.

## Element admission

Required element set for this candidate:

```text
C F H N
```

The run may proceed only if the loaded weight's actual `implemented_species`
covers all four. Coverage is read from the model at load time with
`validate_species=True`; it is not assumed from published documentation.

Elements needed by other candidates are recorded as future limitations and do
not widen this phase's scope.

## Prohibitions for this candidate

```text
do not regenerate the XYZ
do not edit coordinates
do not reorder atoms
do not re-embed or re-minimize
do not substitute a conformer
do not reuse any Phase 8B QXH request, attempt, permit, bundle, or remote root
```

The geometry is consumed exactly as Phase 7 produced it, byte for byte, and its
hash is reverified immediately before use.
