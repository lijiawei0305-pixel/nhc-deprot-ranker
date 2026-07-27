# Phase 9B Cross-Process Handoff Contract

## Authority carrier

The only authoritative carrier from A1 to A2 is each endpoint's durable
`output.xyz` byte sequence. Coordinates never cross as Python objects, pickle,
JSON coordinate arrays, command-line floats, environment variables, parent
memory, or re-serialized geometry.

Handoff evidence is three independently created, immutable receipts. No process
may initialize and later “close” or enrich one shared receipt:

```text
A1HandoffProposalReceiptV1
SupervisorHandoffVerificationReceiptV1
StageA2AdmissionReceiptV1
```

Each is exclusive-create, no-follow, immutable after creation, fsynced with its
parent directory, re-read, SHA256-closed, and independently included in the
evidence manifest. None may overwrite, rename over, append to, or replace
another.

## `A1HandoffProposalReceiptV1`

A1 creates this receipt exactly once after both endpoints and cross-endpoint
validation succeed. It contains candidate, route, attempt, A1 source digest,
MLFF stable interpreter-profile digest, weight and optimizer-protocol digests,
`no_pyscf_assertion=true`, and an endpoint map. Each endpoint contains:

```text
endpoint, charge, multiplicity, atom_count, ordered_elements
element_order_sha256
a1_input_xyz_sha256
a1_output_xyz_sha256
a1_output_xyz_byte_count
trajectory_sha256
preoptimization_receipt_sha256
structural_gates_passed
final_max_force_ev_per_angstrom
optimizer_step_count
calculator_invocation_count
```

The canonical proposal digest covers every field. A1 writes no verification or
admission outcome and has no authority to name A2 as started.

## `SupervisorHandoffVerificationReceiptV1`

Only the campaign supervisor creates this receipt, and only after A1's direct
child, process group, and registered descendants are proved absent. It binds the
proposal digest, supervisor verifier source digest, A1 process-tree absence
proof, exact file-set result, and an independent observation for every proposal
file: byte count, SHA256, mode, regular-file/link-count identity, no-follow
verdict, and size-cap verdict.

It also records proposal-versus-disk equality, candidate/route/attempt,
endpoint/charge/multiplicity/atom-order equality, structural-gate revalidation,
the overall `accepted` or `rejected` outcome, failure classification when
rejected, and its own canonical digest. It never modifies the proposal.

## `StageA2AdmissionReceiptV1`

Only an accepted supervisor verification permits this third immutable receipt.
It binds proposal and verification digests; the admitted cation and neutral XYZ
SHA256 and byte counts; A2 source digest; GPU-PySCF stable interpreter-profile
digest; shared PySCF core digest; shared schema digest; campaign absolute
deadline; remaining budget at admission; clock-domain/boot digest; admission
outcome; and its canonical digest.

The admission is one-shot and does not copy or reserialize the XYZ. A rejected
verification produces no admission receipt.

## Exact-byte closure

Both endpoints must satisfy:

```text
A1 output disk bytes
== bytes hashed by the A1 preoptimization receipt
== bytes named by A1HandoffProposalReceiptV1
== bytes independently re-read by the supervisor
== bytes admitted by StageA2AdmissionReceiptV1
== bytes independently re-read by A2
== bytes passed unchanged to the shared PySCF XYZ parser
```

Byte count and SHA256 are checked at every arrow. A semantically equivalent or
reformatted XYZ is a mismatch. File stat identity, endpoint, atom order,
charge/multiplicity, candidate, attempt, source, profile, and schema identities
must also agree.

## Supervisor verification

An A1 exit code of zero is never admission. The supervisor safely reads the A1
terminal, both endpoint inputs/outputs/trajectories/preoptimization receipts,
and the proposal; recomputes every identity; verifies the exact allowed file
set; rejects extra files; and confirms A1 claims no PySCF result. Only the
resulting accepted immutable verification can authorize admission.

## A2 independent check

Before importing PySCF, A2 validates its internal capability, parent/process,
source/profile/schema/core, admission and clock-domain identities. It opens both
A1 output files itself with bounded no-follow reads, compares the actual bytes
to admission, and hands those same bytes objects to the shared parser. It records
`disk_bytes_sha256 == parser_input_sha256` per endpoint.

A2 cannot accept a parent-supplied hash or coordinate object as a substitute,
edit an A1 file, select another geometry, fall back to Phase 7 input, rerun
AIMNet2, or issue new handoff evidence.

## Failure boundary

Missing evidence, mismatched bytes, endpoint/charge/multiplicity/candidate/source
drift, atom reorder, failed structure gates, unsafe file identity, extra files,
residual A1 processes, or unreadable evidence closes the campaign before A2.
There is no retry, repair, reformatting, receipt mutation, or label.
