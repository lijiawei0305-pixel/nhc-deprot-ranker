# Post-Phase-8B Local Safety Closeout Plan

## Decision and authorization boundary

The rejected Phase 8B incident, its future-code corrections, and its
closed-gate verification were merged to `main` by merge commit
`7d65f724baf1a7827d727b1db08578935895b276`. That publication step is complete
and is no longer a pending action.

This closeout is local only. It does not connect to the server, does not
construct a molecule, does not import a chemistry stack, does not run the
worker, and does not open any execution gate. Throughout this work:

```text
EXECUTION_AUTHORIZED = false
phase8b_bundle._PRODUCTION_AUTHORIZATION_CONSUMED = true
phase8b_launch._PRODUCTION_AUTHORIZATION_CONSUMED = true
phase8b_deploy._PRODUCTION_AUTHORIZATION_CONSUMED = true (added by this closeout)
private quantum_execution_authorized = false
private scheduler_submission_authorized = false
private second_attempt_authorized = false
private server_write_authorized = false (closed by this closeout)
```

No part of this closeout is authorization for SSH, a server write, a quantum
calculation, a second attempt, or a replacement candidate. Any future
calculation requires a new phase, a new document-first plan, a new
candidate/request/attempt/root/permit authority chain, and separate explicit
user authorization.

## Problem statement

The read-only handover audit found two residual safety gaps and several
current-state documentation drifts. None of them changes the scientific
outcome, and none of them makes the rejected attempt acceptable.

### Gap 1 — the deployment route carried no authorization gate

`phase8b_bundle.py` and `phase8b_launch.py` each check the source execution
gate and then an unconditional consumed latch. The directed deployment route
did not:

```text
src/nhc_deprot_ranker/preparation/phase8b_deploy.py
  source execution gate check : absent
  consumed authorization latch: absent
```

`deploy_phase8b_bundle` is a real server-write route. It opens an SSH channel,
creates the frozen remote root, and streams the registered bundle. Its only
protections were the private remote configuration and the directed-write
assertion inside that configuration. That is the weakest link in the retired
authority chain: the private configuration is a local, mutable, gitignored
file, so a stale or re-enabled `server_write_authorized` bit was sufficient to
reach a live upload attempt for a permanently retired bundle.

### Gap 2 — a stale private write bit survived the incident

The gitignored `configs/phase8b.local.yaml` still carried
`server_write_authorized: true` after the attempt was consumed and rejected.
The quantum, scheduler, and second-attempt bits were already false. The stale
write bit is not current user authorization and never was; it is residue from
the consumed attempt, and it must be closed so that no route can read it as
permission.

### Documentation drift

Current-state entry points disagreed with the merged repository state:

- `PHASE_STATUS.md` still listed publishing the rejected incident to `main` as
  the next action, although `7d65f72` already completed it;
- `AGENT.md` recorded the consumed and rejected attempt, but its phase line
  named only the PR #9 planning merge, not the incident-closure merge;
- `AGENT.md` could be read as saying the frozen postflight rejected the attempt
  after reading the receipt. It exited earlier, at a legitimate zero-byte Phase
  7 helper log, before receipt validation.

## Scope

In scope, local only:

1. this plan;
2. `AGENT.md` current phase, boundary, and postflight-ordering correction;
3. `PHASE_STATUS.md` current boundary and next action;
4. closing the stale private `server_write_authorized` bit;
5. adding the source gate and consumed latch to the deployment route;
6. no-chemistry regressions proving the retired routes cannot be revived;
7. a scope-matched quality gate on a recorded interpreter;
8. privacy, diff, and tracked/ignored boundary checks.

Out of scope:

- refactoring or refreshing Phase 0 through 8A;
- regenerating any immutable artifact or evidence hash;
- rewriting historical reports to be naming-symmetric;
- the `pyproject.toml` setuptools `project.license` deprecation warning;
- any server, quantum, scheduler, or second-attempt action.

## Correctness rules for the deployment latch

The latch must behave exactly like the bundle and launch latches:

- it is a module-level `Final` constant, not a parameter, environment variable,
  configuration key, or request field;
- it is checked unconditionally, including on the injectable command-runner
  seam, so a synthetic caller inherits it;
- it is checked before any local file read, before the deployment plan is
  built, before the permit is validated, and before any command runner is
  invoked, so a rejected call performs no input-dependent work;
- the source execution gate is checked first, so a closed gate is reported as a
  closed gate rather than as a consumed authorization;
- it raises the module's own error type.

Ordering matters for evidence, not only for speed. A latch that ran after the
plan build would read the retired bundle and the consumed permit from disk
before refusing, which would make a refusal indistinguishable from a partial
deployment attempt in any future audit.

## Regression contract

The new regressions are no-chemistry and must prove fail-closed behavior, not
happy paths. They must show:

1. the deployment route refuses while the consumed latch is set, even when the
   source execution gate is patched open in the test-style manner;
2. the refusal happens before the injected command runner is called, proving no
   SSH command was constructed or issued;
3. the refusal happens even when the private configuration carries
   `server_write_authorized: true`, proving the stale bit cannot revive the
   route;
4. all three retired routes — deploy, bundle, and launch — hold the consumed
   latch simultaneously, so no single-module patch reopens the chain;
5. the source execution gate remains false in checked-in source.

Item 3 is the direct regression for the stale bit that this closeout also
turns off in the local file. Turning the bit off is a local hygiene action that
leaves no public evidence; the regression is the durable, checked-in guarantee,
because it keeps holding even if the private file is later edited back.

## Verification

The gate runs on a recorded interpreter. The repository virtual environment is
macOS CPython 3.11.15, which does not expose `os.waitid(..., WNOWAIT)`, so the
process-supervisor suite fails closed there by design. That is a platform
capability limit and must not be reported as a code regression. The gate
therefore runs on local CPython 3.14.3, which provides the primitive.

```text
pytest             : full suite
Ruff lint          : full repository
Ruff format        : full repository
mypy strict        : source and scripts
private-path scan  : tracked files only
git diff --check   : full diff
```

The suite must remain no-chemistry: no PySCF, RDKit, geomeTRIC, xTB, Hessian,
optimizer, SSH, or scheduler execution.

## Evidence that must not change

This closeout must leave the following byte-identical:

```text
docs/PHASE8B_DFT_SMOKE_V001.json
  SHA256 0767f20f5a5b9d0a6d87769b7de5e26010c5af9ecdd1a097fbfe4839319b6aa8
```

and must not alter any Phase 0 through 8A manifest, result hash, or immutable
local product under `data/` or `results/`.

The incident interpretation is unchanged by any result in this closeout:

- the immutable guardian receipt remains `cleanup_failed`;
- its `compute_claim_sha256` remains null;
- no cation or neutral endpoint result exists;
- no accepted final SCF energy and no dynamic D3 endpoint evidence exist;
- no deprotonation electronic-energy label exists;
- kernel invocation remains `indeterminate`;
- the consumed candidate, request, attempt, bundle, permit, and remote root
  remain permanently unusable.

A passing software gate is not a scientific result. These two statements are
reported separately and must never be merged into a single claim of success.

## Stopping condition

The closeout is complete when the plan, the two current-state documents, the
deployment latch, and the regressions are in place; the quality gate passes on
the recorded interpreter; the privacy and boundary checks pass; and no
immutable evidence has changed.

At that point the project has exactly three legitimate forward options, and the
next decision belongs to the user:

1. archive at the rejected Phase 8B and perform no further calculation;
2. plan a new, strictly read-only server incident forensics pass;
3. plan a wholly new calculation phase.

None of the three is started by this closeout.
