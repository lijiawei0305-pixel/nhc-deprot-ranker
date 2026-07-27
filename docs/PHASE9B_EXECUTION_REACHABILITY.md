# Phase 9B Execution Reachability Audit

> Item 10/12 update: the historical audit below remains evidence for v8. The
> current v9 split-process reachability implementation is documented in
> `PHASE9B_SPLIT_PROCESS_REACHABILITY_AUDIT.md` and frozen at composite SHA256
> `13ba49fe33f8a85cceae76b043619df832d15633aa08a91d0eadfab7c6f580f5`.
> It remains unreachable from public execution because all gates are false and
> no real permit exists.

Line-by-line audit of the execution path on `main` at merge commit `96abc52`,
performed before any item 8/10 code was written. Read rather than inferred from
the previous round's summary.

## The chain as it actually exists

```text
phase9b_launch.launch_both_routes
  -> ssh -> python3 -B -s -m nhc_deprot_ranker.quantum.phase9b_guardian
     phase9b_guardian.main
       -> parse_supervisor_argv                        (closed 13-flag parser)
       -> verify_launch_arguments                      (every digest recomputed)
       -> consume_phase9b_permit                       (irreversible)
       -> build_worker_handshake_binding               (a RECORD, not a handshake)
       -> spawn_detached_supervisor
          -> python3 -B -s -m ...phase9b_supervisor
             phase9b_supervisor.main
               -> worker_launch_factory(...)           <-- BREAK 1
               -> run_phase9b_supervisor
                  -> run_phase9b_supervised_execution
                     -> _execute_supervised_request
                        -> spawns worker.main
                           -> _validate_worker_compute_claim   <-- BREAK 2
                           -> _issue_guarded_compute_capability
                           -> PySCFBackend(capability)         <-- BREAK 3 for Route A
                           -> _execute_validated_request
```

## Reachability matrix

| Question | Answer | Where it stops |
|---|---|---|
| Route D: guardian → PySCFBackend? | **No** | breaks 1 and 2 |
| Route A: guardian → AIMNet2? | **No** | no AIMNet2 exists in the path at all |
| Phase 9B permit/authority pass worker compute-claim validation? | **No** | `worker.py:403` |
| Phase 9B obtains a compute capability? | **No** | blocked before it, at the same line |
| What backend does *direct* construct? | `PySCFBackend` | `worker.py:574`, unconditional |
| What backend does *assisted* construct? | `PySCFBackend` | identical — the routes differ in **nothing** at execution |
| Does assisted call `pyscf_may_start`? | **No** | zero callers outside the module that defines it |
| Can PySCF bypass the handoff gate? | **Yes, trivially** | nothing consults the gate, so there is nothing to bypass |

## The three breaks

### Break 1 — the guardian builds no worker handshake

`phase9b_guardian` produces a `WorkerHandshakeBinding`, which is a validated
*record* of what the handshake must bind. It is not a `Phase8BWorkerLaunch`, and
the guardian never constructs one: no pipe, no release token, no compute-claim
path, no `on_process_started` callback, no registration, no acknowledgement.

It then spawns `phase9b_supervisor` with the thirteen frozen flags. That process
reaches `main`, finds `worker_launch_factory is None`, and refuses with *"no
guarded worker handshake is wired"*. **Every real Phase 9B launch stops here**,
on both routes, before any worker starts.

Phase 8B's equivalent is `phase8b_runtime._run_supervisor`, which builds
`ComputeClaimAuthority`, the pipe, `supervisor_register_and_release`, and the
`Phase8BWorkerLaunch`. Phase 9B has no analogue.

### Break 2 — compute-claim validation requires the Phase 8B object shape

`worker._validate_worker_compute_claim` carries a profile-driven type gate and
then, immediately after it, an unconditional concrete gate:

```python
if not isinstance(consumed, ConsumedPhase8BPermit) or not isinstance(
    authority, ExactPhase8BAuthority
):
    raise runner.ExecutionNotAuthorizedError(
        "compute claim validation still requires the Phase 8B object shape"
    )
```

The comment above it is honest about being a placeholder. The consequence is
that a Phase 9B consumed permit and authority cannot reach
`_issue_guarded_compute_capability`, so Phase 9B can never obtain a capability
and therefore can never construct a backend.

**The two authority records are already structurally compatible.** Every field
the validator body reads exists on both:

```text
ExactPhase8BAuthority     15 fields
Phase9BExactAuthority     the same 15, plus route, cation_xyz_sha256,
                          neutral_xyz_sha256
```

So the body would work today; it is the concrete gate, not the logic, that
blocks. What is missing is the profile plumbing that lets the one validator read
each chain's shape through an adapter rather than through `isinstance`.

### Break 3 — Route A has no runtime, and its gate has no caller

```text
preparation/phase9b_preopt.py     zero importers anywhere in src/
quantum/phase9b_handoff.py        pyscf_may_start: zero callers
                                  close_pyscf_handoff: zero callers
                                  build_preoptimization_receipt: zero callers
```

`worker.main` constructs `PySCFBackend(compute_capability)` unconditionally, so
`attempt-phase9b-lbnp-assisted-v001` and `attempt-phase9b-lbnp-direct-v001` would
execute **identically**. The assisted route is currently a second copy of the
direct route wearing a different attempt id.

The handoff contract, its two receipts, and the gate are built and tested — but
tested in isolation. Nothing invokes them, so PySCF does not bypass the gate; the
gate is simply not in any path.

## Tests that verify construction rather than execution

Recorded because the previous round's confidence rested partly on them.

| Test | What it actually proves |
|---|---|
| `test_phase9b_worker_profile.py::test_phase9b_now_reaches_capability_issue` | Monkeypatches `_validate_worker_compute_claim` to a no-op, then asserts capability issue is reached. With the real validator, break 2 stops it. The name overstates the result. |
| `test_phase9b_worker_profile.py::test_phase9b_loader_is_selected` | Proves profile selection, not execution. |
| `test_phase9b_handoff.py` (34 tests) | Proves the contract is correct in isolation. None proves it is consulted. |
| `test_phase9b_guardian.py::test_a_clean_transaction_...` | Drives an injected spawn seam. The real chain past the spawn is untested end to end, which is how break 1 survived. |
| `test_phase9b_supervisor_cli.py::test_the_adapter_refuses_...` | Proves the adapter's attempt registry, not that a capability is obtainable. |

## Scope conclusion

The audit found exactly the two blockers named in the item 8/10 authorization,
with one clarification: **break 1 is part of blocker 1, not a third item.**
Wiring the compute-claim closure necessarily means the guardian must construct
the registration, acknowledgement, compute claim, and worker handshake that the
worker validates — they are two ends of the same missing link.

No blocker outside that scope was found. Nothing in the audit required widening
the authorization.
