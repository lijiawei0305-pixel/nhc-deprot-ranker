# Phase 9B Cross-Process Handoff Contract

## Authority carrier

The only authoritative carrier from A1 to A2 is the durable `output.xyz` byte
sequence for each endpoint. Coordinates never cross as Python objects, pickle,
JSON arrays, command-line floats, environment variables, parent memory, or a
re-serialized geometry.

`CrossProcessPySCFHandoffReceiptV1` is initialized by A1 and independently
verified and closed by the campaign supervisor. Each endpoint record includes:

```text
schema, candidate, route, attempt, endpoint
charge, multiplicity, atom_count, element_order, element_order_sha256
input_xyz_sha256, output_xyz_sha256, output_xyz_bytes
preoptimization_receipt_sha256, trajectory_sha256
stage_a1_source_sha256, mlff_interpreter_identity_sha256
weight_sha256, optimizer_protocol_sha256
structural_gate_result, final_max_force, step_count
calculator_invocation_count, no_pyscf_assertion
canonical_receipt_sha256
```

Timestamps and process observations live outside the stable receipt projection.

## Byte closure

Both endpoints must satisfy one transitive equality:

```text
A1 output bytes read from disk
== bytes hashed by the A1 preoptimization receipt
== bytes hashed by CrossProcessPySCFHandoffReceiptV1
== bytes independently read from disk by the campaign supervisor
== bytes independently read from disk by A2
== bytes passed by A2's shared PySCF core into the XYZ parser
```

The byte count and SHA256 are checked at every arrow. A semantically equivalent
or re-formatted XYZ is a mismatch. Atom order, endpoint, candidate, attempt,
charge, multiplicity, source identities, and schema identities must also agree.

## Supervisor verification

After A1 exits, the supervisor first proves the A1 process tree is fully absent.
It then opens the A1 terminal, per-endpoint `input.xyz`, `output.xyz`, trajectory,
preoptimization receipt, and handoff receipt with no-follow bounded reads;
recomputes every digest; verifies exclusive-file identity, endpoint fields,
structural gates, and the frozen allowed path set; rejects extra files; and
confirms A1 claims no PySCF computation.

An A1 exit code of zero is never admission. Only successful independent
verification produces one durable `StageA2AdmissionReceiptV1`, containing both
endpoint identities, the exact admitted byte hashes, verifier source identity,
deadline, A1 terminal digest, process-tree absence proof, file-set verdict, and
receipt digest.

## A2 independent check

Before importing PySCF, A2 validates its capability, supervisor/process/source
and exact interpreter identities, admission receipt, handoff receipts, deadline,
resources, and both XYZ files. It reads the files itself through safe bounded
file descriptors, compares their bytes and identities to admission, parses those
same bytes, and records `disk_bytes_sha256 == parser_input_sha256`.

A2 cannot accept a hash or coordinate object supplied by the supervisor as a
substitute for its own read. It cannot edit the A1 file, select an alternative
geometry, fall back to the Phase 7 input, rerun AIMNet2, or reissue admission.

## Failure boundary

Missing files, hash mismatch, endpoint/charge/multiplicity/candidate/source
drift, atom reorder, failed structure gates, extra files, residual A1 processes,
or unreadable evidence closes the campaign before A2. No retry, repair,
reformatting, or label is permitted.
