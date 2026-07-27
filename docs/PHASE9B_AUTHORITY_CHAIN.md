# Phase 9B Authority Chain and Implementation Gap

> Item 10/12 supersession note: the retained v8 single-process chain is
> `superseded_before_execution`. The current prepared chain is runner v9,
> composite SHA256
> `13ba49fe33f8a85cceae76b043619df832d15633aa08a91d0eadfab7c6f580f5`,
> with one assisted campaign permit and two supervisor-issued internal stage
> capabilities. No real permit exists and all public gates remain false.

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
the new chain.

**Correction, recorded after implementation began:** this understated the work.
The guarded worker is bound to Phase 8B far more deeply than closure wiring
implies, including a hard-coded 120-electron pin that would reject the Phase 9B
candidate's 160 electrons before any other check ran. The full binding inventory
and the resulting architecture decision are in
`docs/PHASE9B_WORKER_BINDING_GAP.md`. That is real implementation work with its own tests, and it is
inside the runner source closure — so it changes `runner_source_sha256` and must
be completed and frozen **before** the request, manifest, and permit are
generated.

The correct order is: implement and test with the gate closed, freeze the source
hash, then build the request and permit against that frozen hash. Building the
permit first and editing source afterward would invalidate the chain.

**Second correction, recorded after the launch control plane was built.** The
inventory above was still incomplete. Two further Phase 8B bindings would have
stopped Phase 9B after everything else was in place:

- `CapabilityIdentityExpectation` carried one `attempt_id`, set to the direct
  route. The assisted route could therefore never pass
  `_validate_compute_capability_fields`, so the paired comparison — the entire
  point of Phase 9B — could not have run. A test had recorded that as intended
  behaviour.
- the pre-import handshake gate in `_execute_supervised_request` compared
  `attempt_id` against Phase 8B's `FROZEN_ATTEMPT_ID`, so neither Phase 9B route
  could reach the handshake at all.

Both are now registries rather than pinned constants, and both fixes are inside
the closure. Together with the Phase 9B supervisor CLI they moved the source hash
a second time; the re-baseline is recorded in
`docs/PHASE9B_IDENTITY_REBASELINE.md`.

**Still missing: the guardian.** What actually runs on the server in Phase 8B is
`phase8b_runtime` in `guardian` mode. It consumes the permit irreversibly, then
re-executes itself in `supervisor` mode, and only that mode constructs the
`Phase8BWorkerLaunch` handshake. Phase 9B has a supervisor CLI and a guarded
executor adapter but no guardian, so the handshake arrives through an injected
factory and the CLI refuses when none is wired. That historical work became
Item 8/12 under the D1 rebaseline and no
Phase 9B run can start without it.

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


**Third correction, recorded after the execution-runtime closure.** The binding
inventory was still incomplete. A line-by-line audit of the shipped chain found
that *neither* route could reach a backend:

- `worker._validate_worker_compute_claim` checked the profile's declared types
  and then, unconditionally, `isinstance(consumed, ConsumedPhase8BPermit)`. The
  comparison body already worked for both chains, so a single concrete gate was
  what blocked Phase 9B from ever obtaining a compute capability.
- Two shared validators in `phase8b_execution` pinned Phase 8B's attempt and
  candidate identity, so a Phase 9B compute claim could not be structurally
  valid.
- The worker ended with one unconditional `PySCFBackend(...)`, so the direct and
  assisted attempts executed **identically**. The assisted route was a second copy
  of the direct route with a different attempt id.
- Route A had no AIMNet2 runtime at all, so the handoff contract had zero callers.

All four were closed in the historical item 8/10 (now Item 8/12), as one
source-freeze unit because each one moves the closure hash. The chain is now:

```text
exact attempt -> WorkerAuthorityProfile -> ClaimIdentityView -> one comparison
              -> compute capability -> ExecutionAdapter -> backend / runtime
```

Three profiles exist, each binding exactly one attempt. Phase 8B's behaviour,
durable bytes, schemas, and refusal semantics are unchanged, and its own
regressions prove it.

## Item 8/12 closure — v8 (historically 8/10)

The production AIMNet2 loader and ASE/LBFGS optimizer are implemented, so the
runner source closure moved again and both chains were regenerated:

```text
runner source schema   nhc-two-endpoint-runner-source-v8
runner_source_sha256   5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2
direct request         acc22c67ba07e245ae001211cfb34038eeb486c3a4fbccdefdf6991b35d66635
direct manifest        906b1f39982107218fec079150851b9d14a4d9a3e4d43bf401c2dec00ed3afa9
assisted request       b74cd3b7e433059ea5d5a9ae213917766a236f4a2c72ef97e3edc9fe6298bef1
assisted manifest      d23b12f9d7b31c6e6bd19665cf847e1f45ab6ec8825ff86a84e560fcf1f56081
state                  prepared_not_authorized
```

The permit now binds how the model is *obtained*, not only what is run: loader
decision A with grade `source_proven`, the absolute-path requirement, no
registry alias, no Hugging Face, no revision or token, no manual `load_model`,
no extra `.eval()`, `compile_model=False`, `validate_species=True`, one base
model load per route with two endpoint wrappers, ASE's own LBFGS defaults, and
the three points at which the deadline is checked.

Every v7 identity is recorded as `superseded_before_execution` in
`docs/PHASE9B_IDENTITY_REBASELINE.md`. None was deployed, launched, or consumed.

## D1 campaign authority correction

One `AssistedCampaignPermitV3` authorizes the whole assisted attempt and binds
both exact interpreter profiles, all source subclosures, initial scientific
inputs, the A1 procedure and validation contract, the only A2 consumer, the
sequential schedule, and one 7200-second absolute deadline. It does not bind the
future A1 output digest; it binds the hash-producing procedure and verifier,
avoiding self-reference.

After consumption, only the campaign supervisor may mint one-shot
`InternalStageCapabilityV1` values via the audited anonymous-pipe,
release-token, registration, acknowledgement, and compute-claim chain. These are
not user permits and are not stored in replayable form. A2 capability cannot
exist before both A1 endpoints are accepted, A1 descendants are reaped, and an
independent durable admission receipt is written.

The campaign guardian consumes and launches; the supervisor controls, verifies,
supervises and terminates; A1 performs only AIMNet2; A2 performs only PySCF after
its own disk read. D1 adds no implementation and opens no gate.
