# AIMNet2 to PySCF Handoff Contract

> Item 10/12 implementation note: the authoritative cross-process handoff is
> now the immutable A1 proposal → supervisor verification → A2 admission chain.
> Durable XYZ bytes, never an in-memory coordinate object, are the sole carrier.
> A2 rereads the same bytes before the shared PySCF parser. Item 11/12 must add
> Postflight verification; no scientific execution occurred here.

## The boundary

Only a structure that passed every gate in
`docs/AIMNET2_PREOPTIMIZATION_CONTRACT.md` and
`docs/AIMNET2_STRUCTURE_VALIDATION.md` may cross into the PySCF stage.

The handoff must be **lossless and provable**. Losslessness is not a stylistic
goal here: the entire authority chain of this project is hash-closed, so a
geometry that cannot be hash-matched across the boundary cannot be part of a
valid attempt at all.

## Where the preoptimizer must live

This is the central architectural constraint, and it is dictated by the existing
runner rather than chosen.

The two-endpoint runner defines a **source closure of exactly 14 files**, hashed
in order into `runner_source_sha256`. That digest is validated at request load,
again before the compute import, and again at capability issue. It is bound into
the permit, the payload manifest, and every artifact's identity block.

```text
nhc_deprot_ranker/__init__.py
nhc_deprot_ranker/constants.py
nhc_deprot_ranker/data/__init__.py
nhc_deprot_ranker/data/provenance.py
nhc_deprot_ranker/quantum/__init__.py
nhc_deprot_ranker/quantum/linux_guardian.py
nhc_deprot_ranker/quantum/phase8b_authority.py
nhc_deprot_ranker/quantum/phase8b_execution.py
nhc_deprot_ranker/quantum/phase8b_permit.py
nhc_deprot_ranker/quantum/phase8b_runtime.py
nhc_deprot_ranker/quantum/two_endpoint.py
nhc_deprot_ranker/quantum/worker.py
nhc_deprot_ranker/quantum/worker_bootstrap.py
nhc_deprot_ranker/quantum/process_supervisor.py
```

**Therefore the AIMNet2 preoptimizer is built outside this closure**, under
`preparation/`, as an upstream producer. It writes optimized XYZ files and
regenerates the request; the runner consumes them exactly as it consumes Phase 7
geometry, and `two_endpoint.py` is treated as an opaque consumer that is not
modified.

Placing the preoptimizer inside the closure would change `runner_source_sha256`
and invalidate the request, manifest, and permit chain on every edit to the
preoptimizer. It would also import a heavy ML stack into the guarded worker's
source identity. Both are unacceptable, and neither is necessary.

An equivalent statement of the rule: **the ML stack never becomes a dependency
of the guarded quantum worker.**

## The handoff mechanism

The runner accepts geometry only as files referenced from the request:

```text
endpoints.cation.xyz_path    POSIX-relative, resolved against request.json's directory
endpoints.cation.xyz_sha256  lowercase SHA256 of the raw XYZ file bytes
endpoints.neutral.xyz_path
endpoints.neutral.xyz_sha256
```

The preoptimizer therefore:

1. writes the AIMNet2-optimized cation and neutral XYZ files;
2. computes their SHA256 values;
3. emits a fresh `request.json` carrying those paths and hashes;
4. records the handoff linkage described below.

No inline coordinate array is accepted, and no in-process geometry object
crosses the boundary.

## Required linkage fields

```text
parent_aimnet2_task_id
aimnet2_final_xyz_sha256
pyscf_input_xyz_sha256
```

with the enforced closure:

```text
aimnet2_final_xyz_sha256 == pyscf_input_xyz_sha256
```

If a formatting difference is unavoidable, byte equality may be replaced by a
canonicalized-coordinate hash, but only if all of the following are separately
proven and recorded:

```text
atom order identical
elements identical
coordinate values identical
charge identical
endpoint identical
```

A canonical hash that hides a reordering is worse than no hash, because it
converts a detectable failure into a silent one.

## Units

Ångström, at every point of the boundary. The runner declares Ångström in its
XYZ parser, passes `unit="Angstrom"` into PySCF, and reads coordinates back in
Ångström. Bohr appears nowhere.

Because AIMNet2's own input and output units must be confirmed against the
installed API in Phase 9A-R, the handoff records the unit explicitly rather than
relying on a shared assumption. A silent Bohr/Ångström confusion scales every
structure by about 1.89 and would still produce a converged, plausible-looking
DFT result.

## Invariants the preoptimizer must not break

These are enforced by the runner and by the Phase 7 validator. Violating any of
them makes the geometry unusable regardless of its quality.

**Atom order and identity.** The runner compares the *ordered* heavy-element
sequences of cation and neutral and rejects any difference. It re-checks that
PySCF did not reorder atoms, and re-checks again after optimization. The
preoptimizer therefore must not sort, canonicalize, or renumber atoms — not even
into a more conventional order.

**Endpoint pair relationship.** The cation must have exactly one more atom than
the neutral, and the element-count difference must be exactly one protium.
Deuterium and tritium do not satisfy it.

**Electron count.** Recomputed from atomic numbers minus charge; must be even,
and must match between endpoints. The frozen Phase 8B pin was 120 electrons.

**Positional ring pin.** The Phase 8B authority check requires `N`, `C`, `N` at
indices 3, 4, 5. Any permutation breaks it.

**Coordinate bounds.** The runner allows `|coord| <= 10000 Å`. The stricter
Phase 7 validator allows `|coord| <= 100 Å` and requires a minimum interatomic
distance of `0.20 Å`. The preoptimizer must satisfy the stricter set.

**Charge and multiplicity.** Both are hard-pinned by endpoint name in the
request: cation must declare `charge = 1`, neutral `charge = 0`, and both must
declare `multiplicity = 1`. These are validated as literal `int`, so `True` and
`1.0` are rejected. Internally the runner maps `multiplicity = 1` to PySCF
`spin = 0` — the count of unpaired electrons, not `2S+1`.

## What regenerating the request implies

Changing the geometry changes `xyz_sha256`, which changes `request_sha256`,
which for a Phase 8B-style guarded attempt propagates into the payload manifest
and the one-shot permit.

The Phase 8B chain is deliberately hostile to modification, and its pinned
hashes belong to a retired attempt. Phase 9B therefore does not edit that chain:
it builds a **new** request, manifest, and permit under a new authority chain,
as required by `docs/PHASE9B_AIMNET2_SMOKE_PLAN.md`.

## Prohibited between the stages

No unregistered geometry modification of any kind may occur after AIMNet2 output
and before PySCF input:

```text
re-running MMFF or UFF
running xTB
manual coordinate editing
re-centering, re-orienting, or rotating
sorting or renumbering atoms
rounding or truncating coordinates
substituting a different conformer
```

Any such step must be an explicit, hashed, registered pipeline stage or it is
failure class `E2_unregistered_intervention`. A silent re-orientation is
especially dangerous because it preserves chemistry, passes casual inspection,
and still breaks the hash closure that proves provenance.

## What the handoff does not transfer

The AIMNet2 energy, forces, trajectory, ensemble statistics, and convergence
flags stay on the AIMNet2 side of the boundary. They are diagnostic and
quality-control data.

Crossing the boundary, **only the geometry and its identity** transfer. PySCF
recomputes energy and gradients from scratch on the transferred structure. It
does not warm-start from AIMNet2 output, does not accept an AIMNet2 energy as an
initial value, and does not shorten any convergence test because AIMNet2
reported convergence.

## D1 cross-process binding

A1 writes one authoritative `output.xyz` per endpoint and hashes it in its
preoptimization receipt and immutable `A1HandoffProposalReceiptV1`. After A1 and
all descendants are reaped, the campaign supervisor independently opens and
hashes those files, validates the exact allowed tree and scientific identities,
and writes an immutable `SupervisorHandoffVerificationReceiptV1`. Only an
accepted verification permits a separate immutable `StageA2AdmissionReceiptV1`.
A2 then independently opens the files
again before importing PySCF and proves that its parser receives those exact
bytes.

No in-memory rebound request, coordinate object, pickle, JSON coordinate array,
environment variable, CLI floats, or reserialization crosses from A1 to A2. The
exact equality and failure rules are frozen in
`PHASE9B_CROSS_PROCESS_HANDOFF_CONTRACT.md`.
