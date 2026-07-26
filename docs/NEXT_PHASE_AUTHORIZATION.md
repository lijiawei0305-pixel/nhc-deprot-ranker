# Next Phase Authorization

## What Phase 9A did and did not do

Phase 9A produced a read-only audit, a set of contracts, and a phase design. It
ran no AIMNet2, no PySCF, no force field, no server command, and no download. It
wrote no implementation code and opened no gate.

Nothing in Phase 9A is authorization for anything below.

## The authorization ladder

Each step is separate. Passing one never implies the next.

```text
1. document planning        <- Phase 9A, done
2. local implementation     <- write the preoptimizer module and its tests
3. read-only server preflight  <- Phase 9A-R
4. server write             <- upload a new bundle
5. compute                  <- Phase 9B execution
```

A generic "continue", "go ahead", or "as recommended" does not cross any of
these boundaries, and does not revive a consumed authority chain.

## Decision 1 — the environment question

This is the blocking question, and it is a policy decision rather than a
technical one.

The recorded AIMNet2 installation lives in a **separate conda prefix**
(`$WJW/env/conda/mlff`, with torch and ase). This project is currently
restricted by `AGENT.md` to the `molecular` environment via `molenv.sh`, which
has ase but **no torch and no aimnet**, and is forbidden from mixing software
stacks or installing dependencies.

So the AIMNet2 route cannot proceed at all unless the project is permitted to
invoke that second environment, in a separate process, for the preoptimization
stage only.

The options are:

1. permit a separate-process, separate-environment preoptimization stage that
   sources the `mlff` prefix and never mixes stacks within one process;
2. keep the current single-environment restriction, which blocks the AIMNet2
   route entirely;
3. defer until the Phase 9A-R preflight establishes what is actually installed
   today.

Option 3 is the conservative ordering: it costs one read-only inspection and
avoids amending the environment policy for a route that may already be blocked
by missing assets.

## Decision 2 — whether to proceed given the prior negative result

The legacy project measured AIMNet2 preoptimization on this hardware and
chemistry and recorded a **median 1.10x** end-to-end speedup over twelve
candidates, concluding it was a dead end because starting geometry was not the
bottleneck. Full detail is in `docs/PHASE9A_AIMNET2_PLAN.md`, Finding 6.

That measurement is the same quantity as promotion gates E1 and E2. Proceeding
to Phase 9B is still defensible — this project's baseline starts from MMFF94
rather than from an already-good geometry, so the gap being closed is larger —
but the expected outcome should be set before the measurement, not after.

The user should decide explicitly between:

1. proceed to Phase 9A-R and then Phase 9B, accepting that non-promotion is a
   likely and legitimate result;
2. proceed only if the preflight shows assets materially better than the legacy
   record, such as a complete four-member ensemble;
3. do not proceed with the preoptimization route.

## Decision 3 — the ensemble question

Only `aimnet2_wb97m_d3_0.pt` has any recorded evidence. Members `_1`, `_2`, and
`_3` have none, and downloading them is prohibited.

If the preflight confirms a single member, Strategy B (single-member
optimization with ensemble validation) becomes impossible as written, because
there are no other members to disagree with. The user then chooses between
running without ensemble uncertainty, or treating the missing members as a
blocker.

## Decision 4 — the fine-tuned legacy weight

A fine-tuned AIMNet2 derivative exists in the legacy project, trained on the
same 71 molecules that constitute this project's entire high-fidelity label set.

Adopting it would require a separate decision and its own audit, because a model
fine-tuned on all 71 labels has seen every label this project uses for
validation. Using it to generate geometry for new candidates is not
automatically circular, but the overlap is real and must be reasoned about
explicitly rather than inherited by convenience. Phase 9 assumes the base weight
unless the user decides otherwise.

## The single next question

Everything above reduces to one question the user must answer before any further
work:

> Authorize the Phase 9A-R read-only server preflight — a single inspection that
> records whether AIMNet2, torch, ase, and which weights are actually present,
> computes their SHA256 values, and reads the real API for charge handling and
> units? It installs nothing, downloads nothing, loads no model, evaluates no
> energy, writes nothing to the server, and produces a blocked report if the
> assets are absent.

Answering it does not commit to Phase 9B, does not amend the environment policy,
and does not authorize any computation. It only replaces assumptions with facts,
and the facts it returns determine whether the remaining decisions are even
live.
