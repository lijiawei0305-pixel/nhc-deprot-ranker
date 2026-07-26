# Phase 9A-I — Minimal AIMNet2 Inference Characterization

## Purpose

Establish, by the smallest sufficient experiment, the facts Phase 9A-R
deliberately left unmeasured because measuring them requires running the model.

This phase is independent of Phase 9B. It performs **no geometry optimization,
no PySCF, and produces no deprotonation label.**

## What it verifies

```text
1. the local _0 weight loads offline from an explicit path
2. which elements the actual weight supports
3. a real NHC cation completes energy and force inference
4. the matching neutral completes energy and force inference
5. the real output units, shapes, and dtypes
6. whether repeated identical inference reproduces adequately
7. whether offline mode plus an explicit path fully blocks downloading
8. whether inference creates unauthorized cache or files
```

## What it is not

Not a geometry optimization, not an accuracy validation, not a PySCF speedup
experiment, not high-precision science, not model promotion, and not label
production.

## Fact baseline

Phase 9A-R passed as a read-only inspection and established:

```text
python 3.11.15, torch 2.8.0+cu128 (sm_70), ase 3.29.0, aimnet 0.2.0
8x Tesla V100-SXM2-32GB on a shared host
AIMNet2ASE accepts charge and mult explicitly
only aimnet2_wb97m_d3_0.pt exists locally
members _1, _2, _3 absent; downloading prohibited
the default registry string exposes a remote-fetch path
```

Phase 8B remains failed closed with zero new DFT labels. High-fidelity labels
remain **71**.

This phase accepts single member `_0` and claims **no ensemble uncertainty**.

## Candidate

`LBNPGYISTSLAHY-UHFFFAOYSA-N` — 26-atom cation, 25-atom neutral, elements
`C F H N`, the fewest atoms and simplest element set among the three candidates
whose authority chain is not retired. Full identities, hashes, and the atom map
are in `docs/PHASE9A_I_CANDIDATE_SELECTION.md`.

Geometry is consumed byte-for-byte as Phase 7 produced it. No regeneration, no
coordinate edit, no reordering, no conformer substitution.

## Authority chain

New and independent. No Phase 8B artifact is reused in any form.

```text
new phase name
new request ID
new attempt ID
new isolated temporary root
new source closure
new model-weight closure
new one-shot permit
new explicit user authorization
```

## The inference matrix

```text
cation,  repeat 1, 2, 3
neutral, repeat 1, 2, 3

2 endpoints
6 energy evaluations
6 force evaluations
0 geometry optimizations
0 PySCF calls
0 labels
```

Three independent clean Python processes, each computing one cation and one
neutral, so repeatability is tested across processes rather than within a warm
one.

`compile_model` stays off unless the installed version cannot run without it.

Coordinates are never modified.

## Permitted and prohibited operations

Permitted: load one existing local weight; build two ASE `Atoms`, one cation and
one neutral; obtain single-point energy and forces; repeat identical inference
for determinism; emit a minimal structured result; read GPU status; write
necessary run cache **inside the authorized isolated root only**.

Prohibited: geometry optimization, any optimizer step, coordinate modification,
PySCF, geomeTRIC, xTB, MMFF, UFF, Hessian, frequencies, MD, training,
fine-tuning, weight download, dependency install or upgrade, global environment
modification, weight modification, and creating any formal scientific label.

## Charge and multiplicity

```text
cation   charge = +1, mult = 1
neutral  charge =  0, mult = 1
```

Passed explicitly at construction. Never inferred from a filename, directory, or
atom count.

If `Atoms.info` carries `charge`, `mult`, or `spin`, those values are read first
and must equal the construction parameters; a mismatch fails closed. ASE's
precedence rules must not be allowed to silently override the intended value —
a cation quietly evaluated as neutral would produce a clean, plausible, entirely
wrong result on the wrong potential energy surface.

Before any calculator call, independently verify atom count, element order,
atom-order SHA256, endpoint, charge, multiplicity, electron-count parity, the
one-proton cation/neutral difference, and the C2/N1/N3 mapping.

## GPU selection

GPU state is re-read immediately before the run. The Phase 9A-R observation is
stale and must not be reused — two devices were already occupied then, and the
shared host's occupancy changes without notice.

Frozen rules:

```text
use exactly one currently free GPU with sufficient memory
never preempt another user's job
never use an occupied GPU
if no GPU qualifies, fail closed
no automatic switch to multi-GPU
no automatic retry on a different card
no background waiting for a GPU to free up
```

Recorded: GPU index, model, pre-run memory usage, running processes, and CUDA
device identity.

Failing closed on a busy machine is the correct outcome. Waiting for a device
would turn a bounded six-call characterization into an unbounded background job.

## Supporting contracts

```text
docs/PHASE9A_I_CANDIDATE_SELECTION.md    candidate, hashes, atom map
docs/PHASE9A_I_MODEL_WEIGHT_CLOSURE.md   weight identity, offline enforcement
docs/PHASE9A_I_CACHE_ISOLATION_PLAN.md   cache redirection and proof
docs/PHASE9A_I_DETERMINISM_CONTRACT.md   preregistered tolerances
docs/PHASE9A_I_RESULT_SCHEMA.md          per-call and aggregate records
docs/PHASE9A_I_AUTHORIZATION_REQUEST.md  what is being asked for
```

## Execution staging

This round delivers documents, a mock implementation, and no-model tests, then
**stops**.

The real six energy-and-force calls require separate explicit user
authorization. Phase 9B is not executed under the same authorization, and no
part of this phase advances into it automatically.

## What a pass cannot prove

A pass proves only that the local weight loads offline, the selected elements
run, charge passes through, the energy and force interface works, and
single-point inference reproduces within the measured tolerance.

It does not prove AIMNet2 is accurate for NHC geometry, that the C2 carbene
centre is inside its training domain, that preoptimization beats direct PySCF,
that AIMNet2 reaches the same local minimum as PySCF, that the model is ready
for batch production, that a single member carries ensemble uncertainty, or that
any new high-fidelity label exists.
