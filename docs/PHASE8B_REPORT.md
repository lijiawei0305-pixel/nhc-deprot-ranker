# Phase 8B Report

## Outcome

Phase 8B is rejected. The only authorized smoke attempt was consumed and did
not produce an acceptable terminal result. It must not be retried, resumed,
reconstructed, or treated as a partially successful calculation.

This report records an execution incident, not a passed DFT gate. No accepted
Phase 8B portable postflight exists for the attempt.

The checked-in machine record is `docs/PHASE8B_DFT_SMOKE_V001.json`, SHA256
`0767f20f5a5b9d0a6d87769b7de5e26010c5af9ecdd1a097fbfe4839319b6aa8`.
It is explicitly `rejected`, `eligible=false`, and
`terminal_evidence_complete=false`; it is not a portable postflight result.

## Frozen scope

The authorization covered exactly one preregistered candidate, request, and
attempt:

| Field | Frozen value |
| --- | --- |
| Candidate | `QXHIEGFUWOLQIJ-UHFFFAOYSA-N` |
| Request | `phase8b-qxh-smoke-v001` |
| Attempt | `attempt-phase8b-qxh-v001` |
| Endpoint order | cation, then neutral |
| Method | gas-phase B3LYP-D3(BJ)/def2-SVP electronic-energy workflow |
| Execution count | one authorized attempt only |

The authorization did not include a second attempt, a replacement candidate,
resume, Hessian, frequency, ZPE, thermal correction, radical calculation,
Molden output, no-D3 control, extra single point, or scheduler submission.

## Terminal evidence and decision

The following facts are established without interpreting any private log:

| Evidence | Observed terminal fact | Acceptance consequence |
| --- | --- | --- |
| One-shot permit | consumed | cannot be restored or reused |
| Permanent compute claim | present; its registration and acknowledgement chain and byte hash are valid | proves that compute authority reached its linearization point, not that an endpoint succeeded |
| Immutable guardian receipt | `cleanup_failed` | terminal success is unavailable |
| Receipt claim binding | `compute_claim_sha256` is null | durable claim cannot be substituted for the receipt's missing terminal binding |
| Endpoint results | no cation or neutral endpoint result | no endpoint can be accepted |
| Final acceptance | not produced | no result marker or scientific result may be published |
| Kernel invocation | `indeterminate` | the evidence does not prove either invocation or non-invocation |

The durable claim and immutable receipt intentionally answer different
questions. The claim proves that the pre-import authority protocol progressed
far enough to authorize the worker. The receipt is the terminal authority for
cleanup and final publication. A valid claim on disk cannot repair, replace,
or override a receipt that records `cleanup_failed` and does not bind that
claim hash.

The acceptance decision therefore remains rejected even after the claim chain
is independently validated.

## Incident sequence

1. The one-shot permit was irreversibly consumed for the frozen attempt.
2. Registration and guardian acknowledgement completed, and the permanent
   compute claim was published.
3. The terminal producer compared process identities from different snapshots
   using full object equality. A normal transient process-state change from
   `S` to `R` was treated as identity drift even though the stable identity
   fields had not changed.
4. The producer failed closed, wrote an immutable `cleanup_failed` receipt, and
   set the receipt's compute-claim hash to null.
5. The historical frozen postflight did not complete terminal acceptance. Its
   Phase 7 tree helper rejected a registered, legitimate zero-byte helper log
   before receipt validation, so the inspector exited without a canonical
   postflight payload.
6. The helper defect does not alter the terminal decision. Once the Phase 7
   reader is corrected, the receipt/claim null mismatch remains a mandatory
   rejection.
7. A later one-call, read-only incident collector failed closed on an exact
   terminal relative-file-tree mismatch. It produced no portable incident
   envelope and was not retried. The mismatch prevents a completeness claim;
   it cannot make the rejected receipt acceptable.

The historical postflight failure must not be described as a completed passed
or rejected portable postflight. The rejection recorded here follows from the
immutable terminal records and the frozen acceptance contract.

## Corrective changes for future readback

The repository now separates stable identity from transient process state when
comparing receipt and registration snapshots. Stable process identity fields
must still agree. Guardian acknowledgement and compute claim identities remain
exactly equal to registration, so the repair does not weaken the compute
authority chain.

The stable file reader now permits zero-byte files only when the Phase 7 tree
reader explicitly requests that behavior. Coordination records, permits,
claims, receipts, failure envelopes, success records, and other safety evidence
remain non-empty and retain the existing regular-file, ownership, link-count,
mode, path, size-bound, and stable-file-descriptor checks.

The local postflight launcher also classifies a nonzero inspector exit and
empty standard output before attempting strict JSON parsing. This improves the
diagnostic without converting any failed inspection into acceptance.

The old QXH production bundle and real-launch paths now carry an unconditional
consumed-authorization latch in addition to the closed source gate. Even a
test-style gate patch cannot revive either effectful path. A future calculation
requires a new documented authority chain rather than reuse of these seams.

These are future-code corrections only. They do not mutate the receipt, restore
the permit, synthesize endpoint output, or reinterpret the consumed attempt.

## Scientific result boundary

There is no Phase 8B electronic-energy result. In particular:

- no cation optimized endpoint or final electronic energy is available;
- no neutral optimized endpoint or final electronic energy is available;
- no dynamic D3(BJ) endpoint evidence is available;
- no electronic energy difference or deprotonation label is available;
- no result may be added to a dataset, model, ranking, or candidate decision.

The absence of endpoint results does not prove that a quantum kernel was never
entered. The only honest kernel status is `indeterminate`. This report makes no
claim about a completed SCF cycle, optimization step, dispersion evaluation,
or other internal chemistry action.

## Privacy and evidence boundary

This tracked report and rejected machine record contain no private absolute
path, server address, account, process identifier, raw log, credential,
molecular coordinate, or private configuration value. No portable postflight
or portable incident envelope was produced. The machine record retains the
collector failure and incomplete-evidence flag rather than presenting a
successful Phase 8B postflight.

## Gate conclusion

Phase 8B does not pass. The execution gate remains closed, the consumed permit
and attempt remain unusable, and no second launch is authorized. Work stops at
incident documentation, future-code correction, and local no-chemistry
verification.
