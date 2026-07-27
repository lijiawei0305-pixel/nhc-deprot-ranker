# Phase 9B Campaign Supervisor State Machine

## States

```text
PLANNED
-> PERMIT_VALIDATED
-> PERMIT_CONSUMED
-> CAMPAIGN_SUPERVISOR_SPAWNED
-> CAMPAIGN_ACKNOWLEDGED
-> A1_CAPABILITY_ISSUED
-> A1_RUNNING
-> A1_TERMINAL_ACCEPTED | A1_TERMINAL_REJECTED
-> HANDOFF_VERIFYING
-> HANDOFF_ACCEPTED | HANDOFF_REJECTED
-> A2_CAPABILITY_ISSUED
-> A2_RUNNING
-> A2_TERMINAL_ACCEPTED | A2_TERMINAL_REJECTED
-> ROUTE_ACCEPTED | ROUTE_REJECTED | INDETERMINATE
```

Only the left-to-right accepted path reaches A2 or a label. A terminal rejected
or indeterminate state cannot transition back, restore authority, issue another
capability, or resume.

## Stage A1

A1 validates its pre-import authority, loads the base model exactly once, and
runs cation then neutral. For each endpoint it performs frozen LBFGS,
preregistered structural validation, durable trajectory/XYZ/receipt writes, and
receipt re-read. It then performs cross-endpoint validation and writes one A1
terminal receipt.

Terminal A1 states are `accepted`, `rejected_cation`, `rejected_neutral`,
`timeout`, `process_failed`, `evidence_failed`, and `indeterminate`. A cation
failure prevents neutral A1. Any non-accepted state prevents handoff admission,
A2, and label.

## Stage A2

A2 exists only after `HANDOFF_ACCEPTED`. It independently validates authority and
disk bytes before importing PySCF, then runs cation residual optimization and
final SCF/evidence. Only accepted cation permits neutral. Neutral acceptance is
required for the route terminal and label. A2 never reruns A1 or chooses another
input.

## Process supervision

```text
guardian
`-- campaign supervisor session/process group
    |-- A1 stage session/process group
    |   `-- registered descendants
    `-- A2 stage session/process group
        `-- registered descendants
```

The supervisor and each stage have separate groups. For a deadline or failure,
the supervisor sends TERM to the exact registered active-stage group, waits the
frozen inherited 10-second grace, sends KILL to that exact group if needed,
performs bounded reap,
and checks for orphans. It never signals an unregistered PID. PID plus start
time, session, process group and parent identity protect against PID reuse.

A2 cannot start until A1's direct child is reaped, its registered descendants
and process group are absent, and the no-overlap assertion is durable. If the
campaign supervisor is terminated, it terminates the current stage, never starts
the next stage, writes best-effort terminal evidence, and leaves no orphan.

## Deadline observations

The same campaign absolute deadline is present in both capabilities, both stage
terminals, the admission receipt, and the campaign terminal. Observed windows
must satisfy:

```text
A1_end <= handoff_start <= handoff_end <= A2_start
A2_end <= campaign_absolute_deadline
A1_window overlaps A2_window = false
```

Clock observations are receipt metadata; authority binds the absolute monotonic
deadline and derived remaining time. A2 admission after expiry is rejected.
