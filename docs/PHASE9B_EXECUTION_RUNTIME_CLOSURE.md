# Phase 9B Execution Runtime Closure

Item 8/10. What the execution-reachability audit found unreachable, and what was
built to close it, as one source-freeze unit.

> **Status: incomplete.** Everything below is delivered and tested, but two
> production adapters are still refusal paths: `_load_base_model` raises even
> when the gate is open, and no ASE/LBFGS optimizer exists. Route A therefore
> still cannot run a real preoptimization. The blocker is one unrecovered API
> fact, recorded in `docs/PHASE9A_I_API_RECOVERY.md`.

## What was unreachable

```text
Route D: guardian -> PySCFBackend       No
Route A: guardian -> AIMNet2            No -- no AIMNet2 existed in the path
Phase 9B passes compute-claim           No -- worker.py hard-required Phase 8B types
Phase 9B obtains a capability           No
assisted backend                        PySCFBackend, identical to direct
pyscf_may_start callers                 zero
```

## 1. One compute-claim core, three exact-attempt profiles

`_validate_worker_compute_claim` used to check the profile's declared types and
then, immediately after, an unconditional `isinstance(ConsumedPhase8BPermit)`.
The comparison body already worked for both chains — `Phase9BExactAuthority` has
every field `ExactPhase8BAuthority` has, plus three — so the concrete gate was the
only obstacle.

Each profile now supplies a `read_claim_identity` adapter producing a
`ClaimIdentityView`, and the comparison sees only that view:

```text
consumed permit + exact authority
  -> profile.read_claim_identity   (typed against Protocols, not getattr)
  -> ClaimIdentityView             (17 fields, chain-agnostic)
  -> one comparison                (no if phase, no match route, no laxer path)
```

Three profiles, each binding exactly one attempt:

```text
PHASE8B_WORKER_PROFILE            attempt-phase8b-qxh-v001        PySCF only
PHASE9B_DIRECT_WORKER_PROFILE     attempt-phase9b-lbnp-direct-v001    PySCF only
PHASE9B_ASSISTED_WORKER_PROFILE   attempt-phase9b-lbnp-assisted-v001  AIMNet2 + PySCF
```

Two exact-attempt Phase 9B profiles rather than one branching on route: the
assisted route has a different runtime, and a runtime must never be chosen by a
condition evaluated inside a security check. `__post_init__` refuses a profile
that binds more than one attempt or an adapter belonging to another attempt.

Two shared validators in `phase8b_execution` also pinned Phase 8B's attempt and
candidate. They now read `registered_transaction_identities()` and
`registered_candidate_identities()` — one registry, sourced from the modules that
own route and candidate identity.

**Phase 8B is unchanged.** Its permit bytes, schemas, frozen artifacts, and
refusal semantics are untouched, and its own regressions prove it. No Phase 8B
consumed permit, receipt, request, bundle, root, or evidence was modified or
regenerated.

## 2. The closed worker CLI

`argparse` honours unambiguous abbreviations, so `--attempt` was accepted for
`--attempt-id`. The supervisor already refused that; a worker only ever started by
the supervisor must hold the same contract, because a weaker inner interface is a
weaker system.

Thirteen required flags, hand-parsed. Rejected: unknown, repeated, missing,
`--flag=value`, abbreviated, positional, empty, malformed integer, non-canonical
path, traversal, control character, NUL. The rejection now happens **before the
request is loaded**, which is stronger than the previous ordering.

## 3. Route-aware execution adapters

```text
exact attempt -> source-frozen WorkerAuthorityProfile -> exact ExecutionAdapter
```

`resolve_execution_adapter` takes one argument, and it is the attempt identity.
Nothing in the request, the CLI, the payload, an environment variable, a file
name, or a remote root can select one; no attempt matches two adapters; an
unregistered attempt has none. Each adapter also refuses an attempt that is not
its own.

**DirectExecutionAdapter** keeps the frozen baseline exactly: frozen initial XYZ →
`PySCFBackend` → the existing two-endpoint runner. It never imports torch, ASE, or
aimnet, never reads the weight, never creates a cache, never preoptimizes, never
produces a preoptimization or handoff receipt, never consults `pyscf_may_start`,
and never touches a GPU. A test watches `sys.modules` across a real direct
execution and asserts the ML stack never appears.

**AssistedExecutionAdapter** runs the AIMNet2 stage inside the route, then the
same PySCF baseline on the bytes the handoff closed over. It cannot fall back to
direct, cannot construct a backend before the gate, and requires its frozen run
root.

## 4. The AIMNet2 production runtime

`quantum/phase9b_aimnet2_runtime.py`, inside the closure.

**Lazy import.** `torch`, `ase`, and `aimnet` are imported only inside
`_load_base_model`, reachable only after the permit is consumed, the handshake is
verified, the claim is validated, the capability is issued, the exact assisted
attempt is selected, and the assisted adapter is resolved. No module in the
guardian, supervisor, worker, or adapter path imports them at module scope.

**The model interface is reused, not guessed.** It reproduces what Phase 9A-I ran
and recorded: `aimnet 0.2.0`, `AIMNet2ASE` from an explicit local weight path,
`charge` and `mult` per endpoint, `validate_species=True`, energies in eV, forces
in eV/A, elements C/F/H/N. One file — `aimnet2_wb97m_d3_0.pt`, 8836941 bytes,
`f0f7c054…4e28` — verified by name, symlink, type, size, and full digest. No
registry alias, no Hugging Face repo, no revision, no token, no download, no
fallback. `ensemble_members = 1`, uncertainty `unavailable_single_member`.

**Offline and cache isolation** are established and *verified* before any import:
`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `HF_DATASETS_OFFLINE`,
`PYTHONDONTWRITEBYTECODE`, plus every cache root Phase 9A-I redirected —
`TORCHINDUCTOR_CACHE_DIR`, `TRITON_CACHE_DIR`, `CUDA_CACHE_PATH`, `TORCH_HOME`,
`XDG_CACHE_HOME`, `HF_HOME`, `TMPDIR` — all pointed inside
`<run-root>/runtime/cache`. A token or model-alias variable is a hard stop. Phase
9A-I proved `compile_model=False` does not prevent a `torch.compile` cache, so the
runtime *measures* what appeared rather than asserting nothing did.

**The frozen optimizer contract** is used unchanged: LBFGS, fmax 0.05 eV/A, 200
steps, 900 s local wall-time, RMSD ≤ 1.0 Å, displacement ≤ 2.5 Å, C2–N1 and C2–N3
≤ 0.15 Å, ring angle ≤ 10°, member `_0`, no restart, no fallback. The local
deadline is `min(route absolute deadline, start + 900 s)`, so adding AIMNet2 can
never extend the route's 7200 s.

**The model is loaded once** for the whole route. Two endpoint calculators are
made from that one model with their own charge and multiplicity; coordinates, ASE
objects, optimizer, history, trajectory, and receipts are never shared.

## 5. The per-endpoint state machine

```text
INITIAL -> INPUT_VERIFIED -> AIMNET2_RUNNING -> AIMNET2_CONVERGED
        -> STRUCTURE_VALIDATED -> PREOPT_EVIDENCE_DURABLE -> HANDOFF_CLOSED
        -> PYSCF_ALLOWED -> PYSCF_RUNNING -> PYSCF_TERMINAL
```

Order fixed; no stage may be skipped, repeated, or follow a failure. **Cation runs
first.** If any cation stage fails, the neutral never starts, PySCF never starts,
no label is produced, and nothing is retried. No failure re-runs AIMNet2, changes
GPU, changes optimizer, relaxes fmax, relaxes a structural gate, restores a
permit, switches to direct, or extends a deadline.

Preoptimization runs **exactly once per endpoint**. A PySCF standard→SOSCF retry
reuses the same closed output and handoff; a second request for the same endpoint
is refused.

## 6. Structural and chemical identity gates

Uses the candidate's real atom map — `C2_carbene=14`, `N1=8`, `N3=15` — never
Phase 8B's `3/4/5`.

Atom count, element sequence, atom-order digest, finite coordinates, per-endpoint
charge and multiplicity, index-preserving connectivity, proton host **by index**,
C2–N1, C2–N3, N1–C2–N3, unaligned total RMSD, and maximum single-atom
displacement. Connectivity is compared as index pairs, never as a canonical graph:
graph isomorphism would call a swap of two same-element atoms "the same
structure", and it is not.

## 7. The handoff into PySCF

```text
AIMNet2 output XYZ bytes
  -> written exclusively, fsynced, re-read
  -> Aimnet2PreoptimizationReceipt (durable, 0400)
  -> every gate must pass
  -> PySCFHandoffReceipt over the bytes read back off disk
  -> pyscf_may_start(receipt)          <- the only door
  -> the request is rebound to that same file and digest
```

The receipt is closed over the bytes read back from disk, and the request PySCF
reads is rebound to that same path and digest — so `handoff_source_sha256` and the
real PySCF geometry's source digest are the same value by construction, not by
coincidence. A test asserts it end to end.

## 8. Evidence tree

```text
runtime/aimnet2/<endpoint>/input.xyz
runtime/aimnet2/<endpoint>/output.xyz
runtime/aimnet2/<endpoint>/trajectory.jsonl
runtime/logs/<endpoint>.aimnet2.log
runtime/evidence/<endpoint>.aimnet2_preoptimization.json   0400
runtime/evidence/<endpoint>.pyscf_handoff.json            0400
runtime/cache/...                                          attempt-local
```

Writes are exclusive-create, no-follow, temp-file plus atomic link, fsynced,
re-read, and compared on type, size, and bytes. Nothing is overwritten, deleted,
or restored, and no caller can declare a write successful.

## 9. AIMNet2 energies never enter a scientific result

They are used for the optimizer, finiteness checks, the trajectory, and
diagnostics. They are never an endpoint energy, never a PySCF substitute or
correction, never mixed with PySCF, and never part of the label, which stays

```text
(E_neutral_PySCF - E_cation_PySCF) * 627.509474 - 6.28      lower_is_better = true
```

Without Hessians or frequencies, nothing claims a frequency-confirmed minimum.

## 10. What is still missing

```text
_load_base_model()      raises unconditionally; no production construction
AseLBFGSOptimizer       does not exist
run_assisted_stage()    refuses without an injected optimizer
```

The security contract, the gates, the evidence writer, and the handoff are real
and tested. What is absent is the code that actually builds an AIMNet2 model and
runs an optimizer, which is blocked on recovering how Phase 9A-I passed its
explicit local weight to `AIMNet2Calculator`.

## 11. What this round did not do

No SSH, no server, no deploy, no permit placed, no launch, no guardian or
supervisor or worker started, no weight loaded, no torch/ASE/aimnet imported for
inference, no GPU, no PySCF or geomeTRIC, and no geometry, energy, force, or label
produced. Eleven `EXECUTION_AUTHORIZED` gates, all false.

`phase9b_postflight.py` was not created. It may begin only once every interface
listed in the item-9 authorization is frozen.
