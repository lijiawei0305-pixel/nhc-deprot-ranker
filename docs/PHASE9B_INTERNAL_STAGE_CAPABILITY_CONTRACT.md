# Phase 9B Internal Stage Capability Contract

## `InternalStageCapabilityV1`

An internal capability is not a permit. It can be created only by the already
authorized campaign supervisor after the user permit has been irreversibly
consumed. Exactly two stage values exist:

```text
aimnet2_preoptimization
pyscf_residual_optimization
```

The canonical capability binds campaign/attempt/candidate/route identity, stage
source closure, exact absolute interpreter and executable identity, exact
structured argv, input identities, output root, campaign absolute deadline,
stage-local deadline where applicable, supervisor PID/start-time/session/group
identity, expected parent PID and stage process group, evidence schema set,
release-token digest, and a unique one-shot capability ID.

## Creation and transport

The implementation must reuse the audited Phase 8B/9B registration,
acknowledgement, release-token, and compute-claim primitives rather than create a
weaker parallel handshake:

```text
supervisor creates anonymous inherited pipe
-> supervisor creates unpredictable one-shot release token
-> stage starts pre-import and registers PID/start/session/group
-> supervisor validates registration and writes acknowledgement
-> supervisor releases token and bound capability through the pipe
-> stage validates parent, token, capability and its own process identity
-> stage permanently consumes the in-memory release
```

The raw release token and complete replayable capability are never placed as
long-lived files in the remote root. Durable evidence contains only schema,
capability SHA256, release-token digest, registration receipt, acknowledgement
receipt, compute-claim linkage, and consumption result.

## Non-forgeability and one-shot rules

The capability cannot be supplied by CLI, request fields, environment variables,
filenames, or caller-selected adapters. It is valid only for the current attempt,
supervisor identity, process group, exact interpreter, exact stage argv, input
hash set, output root, and deadline. A capability from another attempt, stage,
parent, process, interpreter, or already-released token is rejected.

A1 capability is issued once after campaign acknowledgement. A2 capability is
unconstructable until A1 is accepted, its entire process group is absent, the
handoff has been independently verified, and `StageA2AdmissionReceiptV1` is
durable. There is no external `launch-a1` or `launch-a2` interface and no second
ordinary route permit.

## Stage import boundaries

Both stage programs validate capability, process and interpreter identity before
their first compute-package import. A1 then may import only torch/ASE/aimnet; A2
may import PySCF/geomeTRIC/dispersion only after independently re-reading and
validating the admitted XYZ bytes. Any import-boundary violation is an authority
failure, not a scientific rejection.
