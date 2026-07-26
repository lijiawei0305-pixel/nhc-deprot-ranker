# Phase 9B Authority Chain and Implementation Gap

## Status

Plan only. Phase 9B is **not authorized** by this document. It records what must
be built and what must be freshly created before execution can be requested.

## A wholly new chain

Nothing from Phase 8B is reused. Phase 9B requires:

```text
new candidate selection record
new request ID
new attempt ID
new remote root
new source closure
new model-weight closure
new one-shot permit
new local invocation record
new preflight
new acceptance / rejection contract
new privacy contract
new explicit execution authorization
```

Two attempts run under this chain — Route D and Route A — each with its own
attempt identity and its own result tree.

## Candidate

`LBNPGYISTSLAHY-UHFFFAOYSA-N`, the same candidate characterized in Phase 9A-I.

Reusing it is legitimate, and the distinction from QXH matters. QXH is retired
because its **DFT permit, attempt, and remote root were consumed and rejected**.
Phase 9A-I consumed nothing of that kind: it was an inference characterization
that created no DFT permit, no remote run root, and no attempt in the guarded
runner. The candidate itself was never spent.

Positive reasons to keep it:

- its elements `C F H N` are the **only** set empirically confirmed to run under
  `validate_species=True`; every other candidate needs `O`, whose support is
  still unverified;
- it is the smallest remaining candidate at 26 and 25 atoms;
- AIMNet2 energies, forces, and timings for exactly these two endpoints are
  already measured, so Route A's preoptimization stage starts from a known
  working configuration rather than an untested one.

Phase 9B still creates a **new** request, attempt, root, and permit for it.
Reusing the candidate is not reusing an authority chain.

## Frozen identities

```text
inchikey   LBNPGYISTSLAHY-UHFFFAOYSA-N
cation     26 atoms, C9 F9 H5 N3, charge +1, multiplicity 1, 160 electrons
neutral    25 atoms, C9 F9 H4 N3, charge  0, multiplicity 1, 160 electrons
atom map   {C2_carbene: 14, N1: 8, N3: 15}

cation  xyz sha256  543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286
neutral xyz sha256  af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8

weight   aimnet2_wb97m_d3_0.pt, 8836941 bytes
         f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28
```

Both endpoints carry 160 electrons, the count is even, and the two are equal —
consistent with a one-proton difference compensated by charge.

## The implementation gap

This is the part most likely to be underestimated, so it is stated plainly:
**the existing guarded runner cannot execute Phase 9B as it stands.**

Three concrete blockers, each verified in source:

**The electron count is pinned to Phase 8B.** The authority module hard-codes
`FROZEN_ELECTRON_COUNT = 120`. This candidate has **160**. The pin is a
candidate-specific constant, not a general validator.

**The ring position is pinned to Phase 8B.** The authority module requires
`(elements[3], elements[4], elements[5]) == ("N", "C", "N")`. This candidate's
ring atoms are at indices **8, 14, 15**. A correct structure would be rejected,
and "fixing" it by reordering atoms would destroy the atom-order invariant the
entire pipeline depends on.

**The generic entry point is permanently closed.** `run_two_endpoint` raises
unconditionally even with the gate open; the only live path is
`run_phase8b_supervisor`, which is bound to the frozen Phase 8B request,
attempt, permit, root, and hashes.

### What this implies

Phase 9B needs a **new authority module** parameterized by candidate identity
rather than carrying Phase 8B's constants, plus a new supervisor entry bound to
the new chain. That is real implementation work with its own tests, and it is
inside the runner source closure — so it changes `runner_source_sha256` and must
be completed and frozen **before** the request, manifest, and permit are
generated.

The correct order is: implement and test with the gate closed, freeze the source
hash, then build the request and permit against that frozen hash. Building the
permit first and editing source afterward would invalidate the chain.

Historical Phase 8B artifacts must not be edited to accommodate this. They are
immutable records of a rejected attempt.

## Where the preoptimizer lives

Outside the runner source closure, under `preparation/`, as established in
`docs/AIMNET2_PYSCF_HANDOFF_CONTRACT.md`. The ML stack never becomes a
dependency of the guarded quantum worker.

The Phase 9A-I module `preparation/phase9a_i_inference.py` already provides the
validated endpoint model, weight closure, and structural checks. Phase 9B
extends that line rather than starting over, and keeps its own
`EXECUTION_AUTHORIZED` gate closed until authorized.

## Environment separation

AIMNet2 and PySCF run in different conda environments and cannot share a
process. Phase 9A-I confirmed the AIMNet2 side works from the project's explicit
`mlff` script without touching `~/.bashrc`.

Phase 9B therefore runs as two stages in two environments with a hash-closed
file handoff:

```text
stage 1  mlff env       AIMNet2 preoptimization  -> optimized XYZ + hash
stage 2  molecular env  PySCF residual optimization from that XYZ
```

Whether the project may use the `mlff` prefix for production work, as opposed to
the characterization already performed, remains a user decision.

## Cache isolation is mandatory, not optional

Phase 9A-I established this empirically. Despite `compile_model=False`, AIMNet2
exercised `torch.compile` and wrote **66 files totalling 9,966,538 bytes** of
TorchInductor artifacts. On a shared account, an unredirected run would have
written that into global cache.

Phase 9B's AIMNet2 stage must redirect `TORCHINDUCTOR_CACHE_DIR`,
`TRITON_CACHE_DIR`, `CUDA_CACHE_PATH`, `TORCH_HOME`, `XDG_CACHE_HOME`, `HF_HOME`,
and `TMPDIR` into an attempt-specific isolated root before any import, snapshot
global caches before and after, and enumerate what it wrote.

A preoptimization of many steps will write more than a six-call characterization
did. The isolated root must be sized and inventoried accordingly.

## GPU discipline

Re-read GPU state immediately before the run. Take exactly one free device with
sufficient memory, or fail closed. Never preempt, never retry on another card,
never wait in the background. Phase 9A-I found two of eight devices occupied by
other users; that occupancy changes without notice.

## Two-stage authorization

```text
1. plan review            this document and its siblings
2. implementation         new authority module, tests, gate closed
3. execution authorization  a separate, explicit decision naming the frozen run
```

Reaching step 3 requires stopping and restating, in full, the candidate, both
protocols, the resource budget, the remote root, the number of invocations, the
failure semantics, and the non-retryability, then obtaining explicit consent.
