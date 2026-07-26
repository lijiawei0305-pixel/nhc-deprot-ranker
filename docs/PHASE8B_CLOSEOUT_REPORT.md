# Post-Phase-8B Local Safety Closeout Report

## Outcome

The local safety closeout planned in `docs/PHASE8B_CLOSEOUT_PLAN.md` is
complete. Two residual safety gaps were closed and three current-state
documentation drifts were corrected.

This report records a software and documentation result. It does not change any
scientific fact, and it does not make the rejected Phase 8B attempt acceptable.

## Authorization boundary for this round

Local only. No SSH connection, no server read, no server write, no molecule, no
chemistry import, no worker, no scheduler, and no execution-gate change
occurred. The gates were verified closed at the end of the round:

```text
EXECUTION_AUTHORIZED                              = False
phase8b_bundle._PRODUCTION_AUTHORIZATION_CONSUMED = True
phase8b_deploy._PRODUCTION_AUTHORIZATION_CONSUMED = True   (added this round)
phase8b_launch._PRODUCTION_AUTHORIZATION_CONSUMED = True
```

## Sources read

`prompt.md`-derived handover, `AGENT.md`, `PHASE_STATUS.md`,
`docs/PHASE8B_IMPLEMENTATION_PLAN.md`, `docs/PHASE8B_REPORT.md`,
`docs/PHASE8B_TEST_REPORT.md`, `docs/PHASE8B_DFT_SMOKE_V001.json`, the Phase 8B
bundle, deploy, launch, and runner sources, the Phase 8B deploy tests, and the
ignored private remote configuration. The read-only Git audit confirmed `main`
clean at `7d65f724baf1a7827d727b1db08578935895b276`, identical to `origin/main`.

## Gap 1 — the deployment route carried no authorization gate

`deploy_phase8b_bundle` is a real server-write route: it opens SSH, creates the
frozen remote root, and streams the registered bundle. It checked neither the
source execution gate nor a consumed latch, while `phase8b_bundle.py` and
`phase8b_launch.py` checked both. Its only protection was the directed-write
assertion inside the private, mutable, gitignored configuration.

That made the private configuration the weakest link in a retired authority
chain. A stale or re-enabled `server_write_authorized` bit was sufficient to
reach a live upload attempt for a permanently retired bundle.

The route now checks the source execution gate first, then an unconditional
consumed latch, before the timeout check, before the private configuration is
loaded, before the deployment plan is built, before the permit is validated,
and before any injected command runner is called. Ordering is part of the fix:
a latch placed after the plan build would read the retired bundle and consumed
permit from disk before refusing, which would leave a refusal and a partial
deployment attempt indistinguishable in a later audit.

## Gap 2 — a stale private write bit survived the incident

The gitignored `configs/phase8b.local.yaml` still carried
`server_write_authorized: true` after the attempt was consumed and rejected.
It was set to `false`. That file is local, is not tracked, and was not
committed.

Turning the bit off leaves no public evidence, so the durable guarantee is the
checked-in regression: the deployment route now refuses even when a private
configuration presents `server_write_authorized: true`. That protection keeps
holding if the private file is later edited back.

## Documentation drift corrected

- `PHASE_STATUS.md` listed publishing the rejected incident to `main` as the
  next action; `7d65f72` had already completed it. The current boundary and the
  next action now state the real position and the three legitimate forward
  options.
- `AGENT.md` named only the PR #9 planning merge in its phase line; it now also
  records the incident-closure merge at `7d65f72` and states that publication is
  done.
- `AGENT.md` could be read as saying the frozen postflight rejected the attempt
  after reading the receipt. It exited earlier, at a legitimate zero-byte Phase
  7 helper log, before receipt validation. The rejection still stands, but it
  rests on the immutable terminal records and the frozen acceptance contract.
- A new `AGENT.md` section 20 fixes the closeout boundary.

## Files changed

```text
AGENT.md                                              modified
PHASE_STATUS.md                                       modified
docs/PHASE8B_CLOSEOUT_PLAN.md                         added
docs/PHASE8B_CLOSEOUT_REPORT.md                       added
src/nhc_deprot_ranker/preparation/phase8b_deploy.py   modified
tests/test_phase8b_deploy.py                          modified
tests/test_phase8b_retired_routes.py                  added
configs/phase8b.local.yaml                            modified, local only, not tracked
```

The four existing deployment tests gained a fixture that reopens the retired
latches, matching how the launch tests already patch their own latch. Without
it those tests would assert against the refusal rather than the transport
machinery they are meant to cover.

## Evidence that did not change

```text
docs/PHASE8B_DFT_SMOKE_V001.json
  SHA256 0767f20f5a5b9d0a6d87769b7de5e26010c5af9ecdd1a097fbfe4839319b6aa8
```

Recomputed after the closeout and byte-identical. No Phase 0 through 8A
manifest, result hash, figure, or immutable local product under `data/` or
`results/` was read for modification, rewritten, or regenerated.

## Regression contract and its proof

Six no-chemistry regressions in `tests/test_phase8b_retired_routes.py`:

1. all three retired routes hold the consumed latch simultaneously;
2. the checked-in source execution gate is false in source text, not only at
   runtime;
3. a private configuration with `server_write_authorized: true` cannot revive
   the deployment route, and no SSH is opened;
4. the refusal does not depend on a readable configuration, bundle, or valid
   inventory digest;
5. a closed source gate is reported as a closed gate, not as a consumed
   authorization;
6. an out-of-range timeout argument does not preempt the retirement refusal.

These were mutation-tested rather than assumed. With
`phase8b_deploy._PRODUCTION_AUTHORIZATION_CONSUMED` flipped to `False`, four of
the six failed, including the stale-bit and no-input-read cases; the module was
then restored and verified byte-identical to its pre-mutation state. Regressions
2 and 5 are independent of that constant and correctly stayed green.

## Verification

Interpreter: local CPython 3.14.3, which provides `os.waitid(..., WNOWAIT)`.

```text
FULL_PYTEST_RESULT       : 562 passed
RUFF_LINT_RESULT         : passed; All checks passed
RUFF_FORMAT_RESULT       : passed; 129 files formatted
MYPY_STRICT_RESULT       : passed; 72 source files
MYPY_STRICT_NEW_TESTS    : passed
PRIVATE_PATH_SCAN_RESULT : passed; zero markers in tracked files
DIFF_CHECK_RESULT        : passed
EVIDENCE_HASH_RESULT     : passed; unchanged
```

The baseline before this round was `556 passed` on the same interpreter,
matching the previously recorded final gate. The six new regressions account
for the difference.

The repository virtual environment is macOS CPython 3.11.15, which does not
expose `os.waitid(..., WNOWAIT)`. The supervisor suite fails closed there by
design and reports `524 passed, 26 failed`. That is a platform capability limit,
not a code regression, and it is not used as the gate.

## Known issue found but deliberately not fixed

`pre-commit run --all-files` fails one hook:

```text
ruff-check: tests/test_phase8b_runtime.py:768: UP038
  Use `X | Y` in `isinstance` call instead of `(X, Y)`
```

This is pre-existing and unrelated to the closeout. That file is byte-identical
to `main` and was not touched this round. The cause is a stale pin: the
pre-commit configuration pins `ruff-pre-commit` at `v0.12.4`, which still
enforces `UP038`, while the project's own ruff is `0.15.16`, where that rule was
removed. Running ruff with the repository configuration passes.

No pre-commit git hook is installed, so this does not gate commits. Fixing it
means either editing an untouched Phase 8B test or bumping the pin, both of
which are outside this closeout's scope. It is recorded here rather than hidden
or silently repaired, and it belongs with the known low-priority maintenance
items alongside the setuptools `project.license` deprecation warning.

## Scientific position, stated separately

No software result in this round changes any of the following:

- the immutable guardian receipt remains `cleanup_failed`;
- its `compute_claim_sha256` remains null;
- no cation or neutral endpoint result exists;
- no accepted final SCF energy and no dynamic D3 endpoint evidence exist;
- no deprotonation electronic-energy label exists, so the high-fidelity label
  count remains 71;
- kernel invocation remains `indeterminate`;
- the consumed candidate, request, attempt, bundle, permit, and remote root
  remain permanently unusable;
- the frozen Phase 4 verdict remains `raw_xTB_wins`.

A passing software gate is not a scientific result. Phase 8B remains a rejected
execution incident.

## Remaining risk and the next gate

The residual risk is no longer a reachable retired route; it is human. Every
protection here is fail-closed in checked-in source, but nothing prevents a
future operator from writing a new authority chain. That is intended: a new
calculation is supposed to require a new phase, a new document-first plan, a new
candidate/request/attempt/root/permit chain, and separate explicit user
authorization.

The project now has exactly three legitimate forward options, and the choice
belongs to the user:

1. archive at the rejected Phase 8B and perform no further calculation;
2. plan a new, strictly read-only server incident forensics pass;
3. plan a wholly new calculation phase.

None is started by this closeout.
