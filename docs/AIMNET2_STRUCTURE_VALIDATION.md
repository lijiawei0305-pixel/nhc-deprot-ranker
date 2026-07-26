# AIMNet2 Structure Validation

## Purpose

Define what must be checked before and after AIMNet2 preoptimization, and how
to distinguish **allowed geometric relaxation** from **changed reaction
identity**.

A preoptimizer is a program that deliberately moves every atom. The validation
problem is therefore not "did anything change" — everything changed — but "did
the molecule stay the same molecule".

## The inherited invariants

These come from the existing pipeline and are not negotiable. The audit
established each from code.

**Atom order is per-endpoint and load-bearing.** For each endpoint, XYZ row *i*
is RDKit `AddHs` atom index *i* for that endpoint's own SMILES. The Phase 7
validator enforces this directly; the DFT stage re-checks that neither PySCF nor
geomeTRIC reordered atoms.

**The two endpoints are built independently.** The cation and neutral are
parsed, hydrogenated, and embedded from **two separate SMILES columns**. No
code removes a proton programmatically. There is therefore **no guaranteed
index correspondence between the endpoints** — and historically, 3 of 8 audited
examples had cation-map/neutral-index mismatches.

This is the least intuitive fact in the pipeline. The Phase 7 smoke's endpoint
maps happen to agree numerically, but that was coincidence, and acceptance
rested on independent per-endpoint graph validation rather than on the
agreement.

**Phase 7 and the DFT gate check different things.** Phase 7 compares heavy
atoms as an unordered **multiset**; the DFT gate compares the **ordered**
heavy-element sequence. A candidate can pass Phase 7 and fail the DFT gate. Any
new validator must therefore adopt the stricter ordered check rather than
inheriting the Phase 7 one.

**Positional ring indices are pinned at the DFT gate**, which requires `N`, `C`,
`N` at indices 3, 4, 5.

## Pre-AIMNet2 checks

Before any inference:

```text
incoming XYZ SHA256 matches the registered value
upstream validation_status == "passed"
elements and order match the endpoint's recorded atom symbols
formal charge is +1 (cation) / 0 (neutral)
electron count is even and consistent with the declared charge
cation has exactly one more protium than neutral
atom map indices are in range and point at C / N / N
every element is inside the installed model's declared coverage
```

Failure here is failure class `B*` and prevents the AIMNet2 call entirely.

## Post-AIMNet2 checks

After optimization, before any handoff:

| Check | Requirement |
| --- | --- |
| Atom count | unchanged |
| Element sequence | unchanged, in order |
| Atom mapping | C2/N1/N3 still valid |
| Coordinates | all finite, no NaN, no Inf |
| Coordinate bounds | `\|coord\| <= 100 Å` (stricter Phase 7 policy) |
| Minimum distance | `>= 0.20 Å` between any pair |
| Dissociation | no fragment separated beyond the frozen threshold |
| Cation proton | still present, still on its original heavy atom |
| Neutral proton | still absent; not regained |
| Ring skeleton | NHC five-membered ring connectivity intact |
| Key substituent bonds | intact |
| Bonds broken | none |
| Bonds formed | none |

## Distinguishing relaxation from identity change

A single distance cutoff cannot make this distinction, and using one would
either reject normal relaxation or accept a rearrangement. The decision uses
five sources together:

1. **the initial molecular graph** — the reference connectivity;
2. **covalent-radius candidate connectivity** — bonds inferred from the
   optimized coordinates;
3. **the atom mapping** — C2, N1, N3 identity;
4. **the key-bond list** — ring bonds and substituent attachment bonds;
5. **proton identity** — which heavy atom carries the acidic proton.

A structure passes only when the inferred connectivity of the optimized
geometry is graph-isomorphic to the initial connectivity **under the identity
permutation** — that is, with atom indices unchanged, not merely isomorphic
under some relabelling. Index-preserving comparison is required precisely
because a relabelling that "looks the same" would silently break the atom map
and the positional ring pin.

Bond-length changes, torsional rotation, ring puckering, and substituent
reorientation are expected and allowed. Bond formation, bond breaking, proton
transfer, and ring rearrangement are not.

## The proton-migration check

This is the failure the pipeline most needs to catch, and it deserves its own
treatment.

Both endpoints are the same heavy-atom skeleton differing by one proton. If
preoptimization moves the acidic proton to a different heavy atom — most
plausibly onto a basic ring nitrogen or a substituent heteroatom — the result is
a tautomer. It will look like a clean, converged, chemically reasonable
structure. PySCF will then optimize it honestly and produce a well-formed
electronic energy.

The resulting label would be arithmetically correct and scientifically wrong: it
would describe a different reaction than `NHC-H+ -> NHC + H+`.

The check must therefore identify the acidic proton **by index**, record which
heavy atom it is bonded to before optimization, and require the same bond after.
Counting hydrogens is insufficient, because a migration preserves the count.

## The carbene centre deserves extra scrutiny

The neutral endpoint is a singlet N-heterocyclic carbene: a divalent carbon with
a lone pair. General-purpose organic training sets under-represent this
structure, and the legacy project recorded the same concern from the AIMNet2
literature, which self-describes reactions and open-shell species as unresolved.

The project's chemical domain — closed-shell cation plus closed-shell singlet
carbene — deliberately avoids the open-shell weakness, but not the carbene
itself. Consequences:

- validation must confirm the neutral C2 remains a two-coordinate ring carbon
  with **zero** attached hydrogens;
- the C2–N1 and C2–N3 bond lengths are recorded and compared before and after,
  because distortion there is the most likely systematic error;
- where an ensemble is available, per-atom force disagreement at C2 is recorded
  rather than only a scalar aggregate.

## Provenance labels must be updated honestly

The current pipeline carries two labels that are re-checked at the DFT gate:

```text
geometry_quality          = initial_force_field_geometry
force_field_convergence   = unavailable_legacy_m2
```

After AIMNet2 preoptimization, the first is **no longer true** — the geometry is
not an initial force-field geometry any more. Emitting the old value would be a
false provenance claim, and the DFT gate would accept it.

A new, explicit label value is therefore required, together with a versioned
successor to the endpoint-atom-map schema. Whatever value is chosen must:

- state that the structure was preoptimized on a machine-learned potential;
- name the model identity;
- record the AIMNet2 convergence status honestly;
- **not** claim a validated local minimum;
- **not** claim frequency verification.

Convergence on the AIMNet2 surface is convergence on a different surface. It is
not evidence of a stationary point on the B3LYP-D3(BJ)/def2-SVP surface, and the
label must not imply that it is.

## Failure behaviour

Any failed check fails closed. A failed structure produces no handoff, no PySCF
input, and no label, and is recorded with its class from
`docs/AIMNET2_FAILURE_TAXONOMY.md`.

A structure that fails validation is never repaired, re-minimized, re-embedded
with a different seed, or replaced with a different conformer in order to
proceed. Those are new inputs, and they require a new registered task.

## Test design

All tests are local, no-chemistry, and use a mock calculator plus fixture XYZ
files. No test invokes real AIMNet2, real PySCF, or the network.

Required cases, all asserting fail-closed behaviour rather than happy paths:

```text
cation total charge is passed as +1
neutral total charge is passed as 0
endpoint/charge inconsistency fails closed
unsupported element fails closed
atom order change fails closed
coordinate NaN fails closed
force NaN fails closed
non-convergence is not marked success
broken connectivity fails closed
proton migration fails closed
AIMNet2 energy cannot reach the label function
PySCF input hash closes against AIMNet2 output hash
unconverged PySCF creates no endpoint
either endpoint failing creates no label
retired Phase 8B authority cannot be reused
missing weight SHA256 blocks execution
model ID drift blocks execution
direct and assisted routes share identical PySCF configuration
total cost accounting includes AIMNet2 time
manifests regenerate reproducibly
identical input yields a stable task ID
no silent fallback path exists
no automatic install or download path exists
the ensemble member list is fixed
optimizer settings are inside protocol identity
```

The eleventh case is structural and is the most important: it asserts that no
code path allows an AIMNet2 energy to reach the label computation.
