# Phase 9B Worker Binding Gap

## Why this document exists

`docs/PHASE9B_AUTHORITY_CHAIN.md` listed three implementation blockers and
described the remaining work as "a new authority module and supervisor entry,
then closure wiring together with permit generation".

Two of those are now done. Attempting the third revealed that **the plan
understated the work**: the guarded worker is bound to Phase 8B far more deeply
than "closure wiring" implies. This document records the exact binding inventory
and the resulting architecture decision, which belongs to the user.

Recording the understatement rather than quietly absorbing it is the point. A
plan that says "one step remains" when three architectures are viable would make
the next estimate wrong too.

## What is already done

```text
quantum/phase9b_authority.py    candidate-parameterized endpoint authority   PR #18
quantum/phase9b_supervisor.py   route-parity supervisor entry                PR #19
```

Both sit outside the runner source closure by design, so neither has yet changed
`runner_source_sha256`.

## The binding inventory

Every Phase 8B-specific dependency inside `quantum/worker.py`, the guarded
worker that performs in-process re-validation before compute:

| Line | Binding | Nature |
| --- | --- | --- |
| 24 | imports `phase8b_execution` | module-level |
| 85 | `_require_phase8b_arguments` | argument contract |
| 152–156 | `ExactPhase8BAuthority` / `ConsumedPhase8BPermit` type checks | isinstance gate |
| 240–245 | `validate_exact_phase8b_authority`, `load_consumed_phase8b_permit` | validation path |
| 254 | `_validate_frozen_120_electron_pair` | **hard-coded 120 electrons** |
| 257 | `validate_exact_phase8b_authority(...)` | authority binding |
| 275 | `expected_allowed_cpus=frozenset({0, 1, 2, 3})` | frozen CPU affinity |
| 296 | `_issue_phase8b_compute_capability` | capability issue |

The electron pin at line 254 is decisive on its own: the Phase 9B candidate has
**160** electrons, so the worker would reject a correct structure before any
other check ran.

`worker.py` is inside the closure, as is `two_endpoint.py`. Any change to either
alters `runner_source_sha256`, which the permit binds. The permit must therefore
be generated **after** all source work is complete and frozen, never before.

## Three viable architectures

### Option A — branch inside `worker.py` on phase

Add a phase selector that dispatches to Phase 8B or Phase 9B validation.

Cheapest in lines changed. It is also the worst place in the codebase to add a
branch. The worker's trustworthiness rests on there being exactly one validation
path with no alternatives; a dispatch bug could let a Phase 9B request satisfy
Phase 8B checks or the reverse, and that class of bug is invisible in a passing
test suite that only exercises each branch separately.

### Option B — a parallel `phase9b_worker.py`

Leave `worker.py` byte-identical and give Phase 9B its own worker.

Preserves the existing proofs exactly. It duplicates the pre-import handshake,
scratch isolation, compute-claim validation, and capability issue — the same
duplication objection that was explicitly rejected for the supervisor, where
delegation was chosen precisely so one copy of the safety logic exists. Two
workers are free to drift, and the drift would be in safety code.

### Option C — parameterize the worker's authority (recommended)

Do to `worker.py` what was already done to the authority module: replace the
hard-coded electron count, CPU set, and authority type with values carried by a
profile that is itself inside the hash closure.

Largest diff and the most test work. It is also the only option that leaves
**one** validation path, no phase branch, and no duplicated safety logic — and
it generalizes, so a Phase 9C or Phase 10 candidate needs no further surgery.

It is consistent with the two components already built, both of which took the
parameterization route and are covered by mutation tests.

The cost is honest: it is surgery on the most safety-critical file in the
project, and it must be accompanied by tests proving that a Phase 8B-shaped
request cannot satisfy a Phase 9B profile or the reverse.

## Recommendation

**Option C**, for consistency with the completed components and because it is
the only one that avoids both a branch in the validation path and a second copy
of the safety logic.

It should be done as its own reviewed change, with the gate closed, before any
request, manifest, or permit exists — not folded into permit generation.

## Revised remaining sequence

```text
1. worker authority parameterization        Option C, gate closed
2. closure wiring, schema version bump, source hash freeze
3. request, payload manifest, one-shot permit generation
4. separate explicit execution authorization
```

Step 2 must bump `RUNNER_SOURCE_SCHEMA_VERSION` from `nhc-two-endpoint-runner-source-v3`,
because the closure's file set changes and a digest over a different file set
should not silently share a schema version with the old one.

Steps 2 and 3 remain a single indivisible action: the permit binds the source
hash, so freezing and binding cannot be separated.

## What must not be done to close this gap

```text
edit phase8b_authority.py or any Phase 8B frozen artifact
reorder atoms to satisfy the Phase 8B positional pin
relax the electron-count check instead of parameterizing it
generate a permit before the source hash is final
open any execution gate
```

## Step 1 status — worker authority parameterization complete

The user selected Option C, and step 1 is implemented. `worker.py` now carries a
source-frozen `WorkerAuthorityProfile` table — inside the closure file itself,
so profile values are hash-bound exactly like code — selected by exact, unique
attempt identity. The electron-count check calls the pre-existing generic
validator with `profile.electron_count`, and the compute-claim CPU expectation
flows from `profile.allowed_cpus`. The Phase 8B profile reproduces the
historical constants verbatim and remains the only live path; the Phase 9B
profile (160 electrons, both route attempts) is registered but refuses execution
before any permit read.

Resolved bindings from the inventory above: line 254 (the 120-electron pin) and
line 275 (the literal CPU set).

Remaining bindings, deliberately deferred to the wiring step because each
requires the Phase 9B permit and capability designs that are generated together
with the closure change:

```text
load_consumed_phase8b_permit          permit schema and loader
                                      -> Phase 9B counterpart now exists:
                                         quantum/phase9b_permit.py (render,
                                         parse, consumed-load; profile-driven,
                                         per-route one-shot; outside the
                                         closure until wiring)
validate_exact_phase8b_authority      authority validation and its types
                                      -> Phase 9B counterpart now exists:
                                         validate_exact_phase9b_authority +
                                         Phase9BExactAuthority in
                                         quantum/phase9b_permit.py (real
                                         isinstance gate on the consumed permit
                                         type; profile-driven; outside the
                                         closure until wiring)
_issue_phase8b_compute_capability     capability issue, including the frozen
                                      worker-authority match in two_endpoint.py
                                      -> the capability validator is now
                                         parameterized: it compares against a
                                         registered CapabilityIdentityExpectation
                                         selected by the capability's own
                                         identity key, instead of module
                                         constants. Phase 8B behavior is
                                         unchanged. Phase 9B has NO registry
                                         entry yet and therefore cannot be
                                         claimed -- see the two prerequisites
                                         below.
_require_phase8b_arguments            name and message kept: the message is
                                      pinned by an existing test and the
                                      argument shape is already phase-agnostic
```

## Two prerequisites before Phase 9B gets a capability expectation

Attempting the capability parameterization surfaced a gap in the earlier Phase 9B
design that must be closed before a registry entry can exist:

**Resources are not frozen yet.** **Resolved.** The budget is now frozen in
`quantum/phase9b_resources.py`, digest
`0fec2c1914f413a2762e1fafc7daa9900551981b5af72897746864edffac7df8`.

The PySCF envelope reuses the Phase 8B values verbatim — one worker, 4
computational threads, CPU affinity `0-3`, PySCF `max_memory=12000 MB`, 7200 s
hard wall-time, 10 s TERM grace, 64 KiB per stream. Two reasons, both about
interpretability: Route D and Route A must share an identical PySCF envelope or
any measured speedup is uninterpretable, and reusing a budget already exercised
in a real attempt avoids adding an unvalidated variable next to the one being
tested.

The AIMNet2 stage carries its **own separate budget**: one free GPU or fail
closed, one ensemble member, `ensemble_uncertainty_available=false`,
`compile_model=false`, the measured 21.9 s first-call cost recorded explicitly, a
60 s compile allowance, a 900 s preoptimization ceiling, and the mandatory
cache-isolation variable list. It deliberately carries **no**
`hard_wall_timeout_seconds`, so preoptimization cost cannot be hidden inside the
PySCF number being compared. A regression enforces that separation.

**`Phase9BExactAuthority` carries no geometry-validation binding.**
**Resolved.** `CandidateProfile` and `Phase9BExactAuthority` now carry
`legacy_atom_map_sha256`, `endpoint_atom_map_sha256`, and
`geometry_validation_sha256`, all validated as lowercase SHA256 by profile
self-consistency. The authority populates them from the **profile**, never from
the permit, so a permit cannot assert its own geometry provenance.

Both routes bind all three. For Route D they describe its actual inputs; for
Route A they describe the parent lineage, which stays meaningful because atom
order is index-preserving across preoptimization and the permit separately binds
the initial geometry hashes.

The frozen values were read from the tracked Phase 7 manifest and independently
reverified against the local immutable product. The geometry-validation anchor
`35e99683...39f90` covers all four smoke candidates, so it is deliberately not
candidate-specific.

Both prerequisites are now closed, so the Phase 9B capability expectation is
registered. The registry holds exactly two chains, and a capability presenting
any other identity key still fails closed with `no frozen identity expectation`
rather than falling back to a chain.

## Current state

All three execution gates remain closed, the closure remains at 14 files with no
Phase 9B module wired in, `phase8b_authority.py`, `phase8b_permit.py`, and
`two_endpoint.py` are untouched, `PHASE8B_DFT_SMOKE_V001.json` is unchanged, and
the suite passes at 696.
