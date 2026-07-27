# Phase 9B Attempt and Process-Owned State Machines

No shared mutable `state.json` exists. Every process writes only its own
immutable events or terminal receipt. `AttemptLifecycleV1` is a derived audit
projection over those receipts, not a state file owned by one process.

## `AttemptLifecycleV1`

```text
PLANNED
PERMIT_VALIDATED
PERMIT_CONSUMED
GUARDIAN_SPAWN_ATTEMPTED
CAMPAIGN_SUPERVISOR_SPAWNED
CAMPAIGN_ACKNOWLEDGED
A1_RUNNING
A1_TERMINAL
HANDOFF_TERMINAL
A2_RUNNING
A2_TERMINAL
ROUTE_TERMINAL
```

An auditor derives the furthest provable state from immutable permit,
consumption, guardian, registration, acknowledgement, stage, handoff, admission,
process-tree, and route-terminal receipts. Missing or contradictory events yield
an indeterminate projection; no process edits the projection.

## `GuardianLaunchStateV1`

The guardian alone may emit:

```text
not_started
permit_validated
permit_consumed
supervisor_spawned
supervisor_spawn_failed
acknowledged
ack_failed
indeterminate
```

Guardian events prove its own validation, irreversible consumption, spawn and
short acknowledgement transaction. It never claims that the supervisor
validated its campaign capability, ran A1/A2, verified handoff, or reached a
scientific terminal.

## `CampaignRuntimeStateV1`

The supervisor state machine begins only after it receives and validates a
campaign capability:

```text
campaign_capability_validated
campaign_acknowledged
a1_registration_waiting
a1_running
a1_terminal_accepted | a1_terminal_rejected
handoff_verifying
handoff_accepted | handoff_rejected
a2_registration_waiting
a2_running
a2_terminal_accepted | a2_terminal_rejected
route_accepted | route_rejected | indeterminate
```

The supervisor never claims permit validation, permit consumption, or its own
spawn. Those are guardian-owned events consumed by the lifecycle aggregator.
The supervisor may issue A2 capability only from `handoff_accepted` and only
after A1 process absence is durable.

## Stage terminals

A1 terminal outcomes are `accepted`, `rejected_cation`, `rejected_neutral`,
`timeout`, `process_failed`, `evidence_failed`, and `indeterminate`. Cation
failure skips neutral. Any non-accepted A1 terminal prevents handoff admission,
A2, and label.

A2 terminal outcomes are `accepted`, `rejected_cation`, `rejected_neutral`,
`d3_failed`, `timeout`, `process_failed`, `evidence_failed`, and
`indeterminate`. Cation failure skips neutral. A label requires A2 acceptance of
both endpoints and a route acceptance receipt.

## Process supervision

```text
guardian
`-- campaign supervisor session/process group
    |-- A1 stage session/process group
    |   `-- registered descendants
    `-- A2 stage session/process group
        `-- registered descendants
```

The supervisor and stages have separate process groups. Deadline or failure
sends TERM to the exact registered active-stage group, waits the inherited
10-second production grace, sends KILL if necessary, performs bounded reap, and
checks for orphans. It never signals an unregistered PID. PID, process start
time, parent, session and process-group identities protect against PID reuse.

A2 cannot start until A1's direct child is reaped, its registered descendants
and process group are absent, and the non-overlap proof is durable. Supervisor
termination kills and reaps the active stage, never starts the next stage, and
writes best-effort immutable terminal evidence.

## Runtime clock and deadline

The permit binds only `campaign_wall_limit_seconds=7200`,
`a1_local_limit_seconds=900`, and `termination_grace_seconds=10`. After campaign
capability validation, the supervisor observes `CLOCK_MONOTONIC` and creates:

```text
campaign_absolute_deadline_ns =
    campaign_monotonic_start_ns + 7200 * 1_000_000_000
```

The runtime clock receipt binds Linux boot ID digest, host execution identity
digest, supervisor process start identity, monotonic resolution, and a digest of
that derivation. Internal capabilities bind the resulting absolute deadline and
clock-domain/boot digest. A1 additionally binds the smaller local deadline; A2
binds only the campaign deadline and remaining budget. Cross-boot, cross-host or
cross-clock-domain capability replay is rejected, and A2 never receives a fresh
7200 seconds.

Observed windows must satisfy:

```text
A1_end <= handoff_start <= handoff_end <= A2_start
A2_end <= campaign_absolute_deadline
A1_window intersects A2_window = false
```
