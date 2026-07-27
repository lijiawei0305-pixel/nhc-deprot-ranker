# Phase 9B Split-Process Runtime Plan

## Scope and status

This document completes Item 9/12: architecture only. It authorizes no SSH,
runtime implementation, source freeze, request or permit generation, deployment,
launch, Postflight, model load, GPU use, PySCF call, or label.

The Phase 9B plan is re-baselined as follows:

| Item | Deliverable | State |
| --- | --- | --- |
| 1/12 | AIMNet2 preoptimization contract | complete |
| 2/12 | request and payload manifest | complete |
| 3/12 | read-only server preflight | complete |
| 4/12 | directed two-route deployment | complete |
| 5/12 | guardian launch | complete |
| 6/12 | pre-launch integration | complete |
| 7/12 | guardian / transport / handoff contract | complete |
| 8/12 | single-process production runtime v8 | complete, host-incompatible |
| 9/12 | dual-environment split-process design | complete in this document set |
| 10/12 | split-process implementation and v9 freeze | not started |
| 11/12 | split-process-aware Postflight | not started |
| 12/12 | closed-gate full-chain rehearsal | not started |

Item 8/12 is retained code, not discarded code. The AIMNet2 loader, ASE LBFGS
optimizer, trajectory and structure gates, PySCF backend, authority primitives,
and process supervision remain reuse candidates. The route orchestration and
authority boundary are what must change. Until Item 10/12 is complete, v8 stays
`prepared_not_authorized` and `blocked_by_no_validated_single_interpreter`; only
the final v9 freeze may mark it `superseded_before_execution`.

## Unique topology

Route D remains one direct process under its own guardian and supervisor:

```text
Direct Guardian
-> Direct Supervisor
-> exact gpupyscf interpreter
-> PySCF cation
-> PySCF neutral
-> direct terminal
```

Route A becomes one campaign with two sequential stage processes:

```text
Assisted Campaign Guardian
-> Assisted Campaign Supervisor
   +-> Stage A1, exact MLFF interpreter
   |   -> load one AIMNet2 base model
   |   -> cation preoptimization and structural validation
   |   -> neutral preoptimization and structural validation
   |   -> durable geometry and receipts
   +-> supervisor-side independent handoff verification
   +-> Stage A2, exact GPU-PySCF interpreter
       -> cation residual PySCF optimization and final evidence
       -> neutral residual PySCF optimization and final evidence
       -> assisted terminal
```

The frozen cardinality is one candidate, one assisted route, one overall
assisted attempt, one user-authorized one-shot permit, one campaign guardian,
one long-lived campaign supervisor, two sequential stage processes, one overall
hard deadline, and one terminal route outcome. It is not two attempts because
A1 and A2 share one attempt ID, one consumed authority, one deadline, one
evidence root, and one immutable-receipt-derived attempt lifecycle; neither stage is independently
launchable or retryable.

There are no scheduler jobs, background shell launches, `nohup`, shell `&`,
free-text commands, `PYTHONPATH` composition, manual file copying, caller-chosen
A2 inputs, or second authorization between stages.

## Frozen stage order

A1 handles cation then neutral in one MLFF process. A2 starts only after both A1
endpoints and the cross-endpoint gates pass, then runs PySCF cation and, only on
acceptance, neutral. Alternating A1 cation / A2 cation / A1 neutral / A2 neutral
is forbidden because it would require additional processes, model loads,
capabilities, and failure states.

This makes the assisted route more conservative: neutral AIMNet2 rejection
prevents all PySCF consumption. It changes neither the final label formula nor
the direct route, does not inspect a future neutral PySCF result, and may cause
earlier assisted failure. Such early termination is never reported as a
speedup.

## Scientific invariants

Direct and assisted share candidate, initial endpoint bytes, atom order,
charge/multiplicity, electron count, PySCF execution core, PySCF protocol,
resource envelope, cation-before-neutral order, D3 evidence, and label formula.
The only scientific variable remains the insertion of AIMNet2 preoptimization
before the same PySCF residual optimizer. Process separation is an execution
implementation detail.

AIMNet2 energies are diagnostic only. A label may be emitted only after both A2
endpoints are accepted and only from the frozen PySCF electronic-energy formula.

## Deadline and resource accounting

The permit binds duration authority only: campaign wall limit 7200 seconds, A1
local limit 900 seconds, and termination grace 10 seconds. It does not contain a
future absolute monotonic timestamp. After validating the campaign capability,
the supervisor binds `CLOCK_MONOTONIC`, Linux boot ID, host execution identity,
its process-start identity and clock resolution, then derives:

```text
campaign_absolute_deadline_ns =
    campaign_monotonic_start_ns + 7200 * 1_000_000_000
A1_deadline_ns = min(campaign_absolute_deadline_ns,
                     A1_start_ns + 900 * 1_000_000_000)
A2_deadline_ns = campaign_absolute_deadline_ns
```

A2 receives the remaining campaign time in the same boot/clock domain, never a fresh 7200 seconds. A1 and A2
process windows must not overlap. The supervisor records campaign, A1, handoff,
and A2 start/end observations, total wall time, overlap verdict, and remaining
time at A2 admission.

A1 uses the preflight-selected exact V100 with `sm_70` and attempt-local ML caches. The
selected device is permit-bound and rechecked immediately before A1; it is never
switched automatically. A2 uses four computational threads, CPU affinity `0-3`,
and 12000 MB PySCF memory and need not retain the GPU. GPU-seconds cover only the
A1 process window. CPU core-seconds are reported separately for A1, handoff, and
A2. Assisted total wall includes all guardian, supervisor, import/model,
preoptimization, handoff, A2, PySCF, and terminal-evidence overhead.

## Exactly once

The permit, supervisor spawn, A1 spawn, model load, endpoint preoptimizations,
handoff admission, A2 spawn, endpoint PySCF executions, route terminal, and
label are each bounded to one. A2 may be spawned at most once. The frozen
standard-to-SOSCF internal PySCF progression is not a route retry; it must reuse
the same A1 bytes and cannot restart A1 or A2.

## Prohibitions and next boundary

Direct-only output remains insufficient for a paired experiment. No scientific
execution is reachable in Item 9/12. The only next work is Item 10/12, a new
local/mock-only authorization that implements this frozen design and performs
one v9 rebaseline after all source and tests are final.

## Item 9/12 completion assessment

- unified strategy is closed without an incompatibility claim;
- one unique campaign topology and one user permit protect both stages;
- internal capabilities are supervisor-only, one-shot and non-replayable;
- both exact interpreter identities and the A1-then-A2 order are bound;
- one A1 process preserves one base-model load for both endpoints;
- durable XYZ bytes, independent supervisor verification, and A2 disk re-read
  close the handoff;
- one absolute deadline, non-overlapping process groups, termination/reap and
  orphan rules close supervision;
- terminal failure states and the fixed evidence tree cover partial outcomes;
- direct/A2 use one shared PySCF core and differ only in admitted input bytes;
- option B subclosures plus a composite make the one-time v9 migration unique;
- the reachability audit classifies every current execution component;
- Item 10 implementation/tests, Item 11 Postflight, and Item 12 rehearsal have
  explicit, non-overlapping scopes;
- v8, all eleven false gates, and 71 production labels are unchanged;
- no server connection or scientific calculation occurred.

No unresolved design choice can make A2 independently launchable, require a
second user permit, replay a capability, cross handoff in memory, overlap A1/A2,
reset A2's deadline, fork the PySCF algorithm, or hide A1 from Postflight.
