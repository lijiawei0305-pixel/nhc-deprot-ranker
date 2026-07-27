# Phase 9B Internal Stage Capability Contract

## `InternalStageCapabilityV1`

An internal capability is not a permit. It can be constructed only by the
authorized campaign supervisor after the user permit is irreversibly consumed
and after the intended pre-import stage bootstrap has registered and that
registration has been verified. Exactly two stage values exist:

```text
aimnet2_preoptimization
pyscf_residual_optimization
```

The capability binds campaign/attempt/candidate/route; stage source leaf and
dependency digests; exact stable and private interpreter bindings; exact argv;
input identities; output root; campaign absolute deadline; A1 derived deadline
or A2 remaining budget; `CLOCK_MONOTONIC` domain and Linux boot digest; evidence
schemas; release-token digest; and one unique capability ID.

Process identity fields are explicit and never overloaded:

```text
supervisor_pid
supervisor_start_time
supervisor_session_id
supervisor_process_group_id

stage_pid
stage_start_time
stage_session_id
stage_process_group_id
expected_parent_pid
```

There is no ambiguous `expected_process_group_id` field.

## Registration, construction and release timeline

The implementation must preserve the strongest audited Phase 8B/9B handshake
semantics. Pipe count may follow the actual shared core, but the authority order
is fixed:

```text
supervisor creates registration and release channels
-> supervisor spawns pre-import stage bootstrap
-> stage creates its own session/process group
-> stage sends registration to supervisor
-> supervisor verifies child PID and start time
-> supervisor verifies parent PID, child SID and child PGID
-> supervisor verifies exact executable, argv and source digest
-> supervisor constructs InternalStageCapabilityV1 from that registration
-> supervisor writes immutable acknowledgement
-> supervisor sends capability + one-shot release token over release channel
-> stage validates parent/process/profile/source/deadline/token
-> stage permanently consumes the release
-> only then may the stage import compute packages
```

Creating a capability before registration verification is impossible by type
and control flow. A capability for a different registered process cannot be
rebound by editing a PID field because all process, source, profile, argv,
deadline and token identities are digest-bound.

## Durable evidence and replay resistance

The raw release token and complete replayable capability never become durable
files. Durable evidence contains only schema, capability SHA256, release-token
digest, stage registration, acknowledgement, process identity and consumption
receipt. Token and capability frames are bounded and inherited only by the
registered bootstrap; they are consumed once and the file descriptors close.

Capabilities are invalid across attempt, stage, parent, process, source,
interpreter profile, host, boot, clock domain, argv, input, output root, or
deadline. A replayed token or capability is rejected. Request, CLI, environment,
filename, or caller-selected adapter cannot construct one.

A1 capability may be issued once after campaign acknowledgement. A2 capability
is unconstructable until A1 is accepted, its entire process tree is absent,
`SupervisorHandoffVerificationReceiptV1` is accepted, and
`StageA2AdmissionReceiptV1` is durable. There is no external `launch-a1` or
`launch-a2` and no second ordinary assisted permit.

## Stage import boundaries

A1 may import torch/ASE/aimnet only after capability consumption. A2 may import
PySCF/geomeTRIC/dispersion only after capability consumption and its own safe
disk re-read of admitted XYZ. A1 importing PySCF or A2 importing the ML stack is
an authority failure, not a scientific rejection.
