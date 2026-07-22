# Phase 8B Frozen Smoke Execution Runbook

Status: the only authorized attempt was consumed and rejected. The source
execution gate is closed. This runbook does not authorize a second attempt,
another candidate, or a protocol/resource change.

## Frozen identity

- InChIKey: `QXHIEGFUWOLQIJ-UHFFFAOYSA-N`
- request: `phase8b-qxh-smoke-v001`
- attempt: `attempt-phase8b-qxh-v001`
- endpoint order: cation `(+1, singlet)` then neutral `(0, singlet)`
- cation XYZ SHA256:
  `097f08ab7c3f265efa8ee36c3fd45d72776c9bdcbd3de503baf8fe91561c12aa`
- neutral XYZ SHA256:
  `e41e87daca3c7a74383364a427d277df5cf8a0aa70bff015c4cf432455f26bd0`
- protocol: gas-phase RKS B3LYP-D3(BJ)/def2-SVP, geomeTRIC grid 3,
  `conv_tol=1e-9`, `maxsteps=100`
- remote relative root:
  `data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001`

## Fixed resource and compute boundary

The request uses one worker and serial endpoints, four computational threads,
whole-tree Linux CPU affinity `0-3`, PySCF `max_memory=12000 MB` as a soft
limit, a 7,200-second absolute wall deadline, a 10-second TERM grace, and
65,536 captured bytes per stream. Only an explicit standard-SCF
non-convergence may consume the single endpoint-wide SOSCF retry budget.

Each endpoint performs one D3(BJ)-active optimization and one final
same-method SCF. One D3-only, zero-SCF energy/gradient audit is allowed per
endpoint. Its value is compared with the final SCF D3 component and is never
added to the label again. Hessian, frequency, ZPE, thermal corrections,
radicals, no-D3 controls, extra electronic single points, Molden output, and a
second attempt are forbidden.

## Ordered gates

1. Keep every execution gate false while implementing and running fake-backend
   and standard-library process tests.
2. Pass the complete test suite, Ruff formatting/lint, strict mypy,
   pre-commit, package build, static no-compute scan, and independent safety,
   science, and consistency reviews.
3. Make the final candidate-specific source change, repeat the no-chemistry
   gates, and freeze the complete executable source hash.
4. Build the request, permit-excluding payload manifest, private one-shot
   permit, and outer transport inventory in that acyclic order. Independently
   re-read and hash the local bundle.
5. Run one fresh combined read-only server preflight. Stop before creating the
   target root on any version, source, Phase 7, resource, process, symlink, or
   target-existence mismatch.
6. Create only the frozen run root, transfer only inventory-listed files
   without deletion or overwrite, and rehash every file at its final path.
7. Before opening the launch SSH connection, validate the unchanged local
   bundle, private route, source gate, transport inventory, permit route, and
   exact remote command. Atomically create one ignored local invocation record
   with `O_EXCL | O_NOFOLLOW`, mode `0600`, file and parent-directory `fsync`,
   binding the config hash, bundle identities, SSH command hash, and frozen
   candidate/request/attempt. An existing record rejects before SSH. The
   record is never deleted, replaced, restored, or reused, including when SSH
   fails or times out; a separate exclusive outcome record may describe the
   one call but cannot authorize another call.
8. Atomically consume the path-bound permit before spawning any worker. Start
   one detached `setsid` guardian under `taskset -c 0-3`; its worker remains
   behind a pre-import parent-death/identity/watchdog handshake. Detach the
   initial guardian invocation with stdin and both output streams connected to
   `/dev/null`; no launcher-side log may be created outside the frozen run
   root. Inside the post-consumption, exact-authority-validated spawn callback,
   the entry point creates and redirects `private/guardian.log`, then creates
   `private/supervisor.stdout.log` and `private/supervisor.stderr.log`. A
   partial log-open, redirection, or spawn failure is therefore closed safely
   and represented by the durable guardian receipt.
   The tested launcher must use one SSH argv, enter the exact project root,
   source only `env/envs/molenv.sh`, replace every frozen thread variable, and
   invoke only the deployed hash-closed runtime. The remote guardian command
   is exactly `setsid -f taskset -c 0-3 python -I -B ... guardian`; its stdin,
   stdout, and stderr are `/dev/null`, and it has no scheduler or shell-side
   background fallback.
   After the guardian has durably ACKed the exact live registration, the
   production supervisor must re-read and validate the registration and ACK,
   all three live PID/starttime/boot/session/parent/affinity identities, and the
   still-absent receipt. It then publishes exactly one permanent
   `private/compute_claim.json` with `O_EXCL | O_NOFOLLOW`, mode `0600`, and file
   plus directory `fsync`, binding the registration/ACK hashes, release token,
   deadline, candidate/request/attempt, consumed permit, transport/payload/
   source/protocol/resource/input hashes, exact roots, request/output paths,
   worker scratch, and process identities. Only after re-reading that complete
   hash chain may it release the pipe. Release failure burns and retains the
   claim. The bootstrap revalidates the chain and current live identities before
   importing the worker, and the worker repeats the authority/claim cross-check
   before issuing its process-local compute capability. Any existing, missing,
   replaced, reused-PID, expired, or mismatched claim permanently rejects
   compute; no code path deletes or restores it.
9. Monitor read-only. Never retry, replace the candidate, extend the deadline,
   enlarge resources, or modify deployed bytes.
10. After termination, first prove the exact process groups are absent, the
   permit remains consumed, the success/failure inventory is exact, and Phase
   7/source hashes remain unchanged. Then perform a private readback and create
   portable evidence.
11. Close the local source execution gate, rerun no-chemistry checks, and stop.

## Acceptance and failure rule

Success is accepted only when both endpoints explicitly converge, all finite
energy/geometry/resource/D3 conditions pass, the final label independently
recomputes from the two D3-inclusive final energies and the frozen gas-proton
constant, both supervisor and guardian prove cleanup/reap, neither stream is
truncated, and the exact success tree is hash-closed. Any ambiguity is a
failure. A safe failure may publish only the fixed attempt's bounded failure
envelope after cleanup proof; the consumed permit is never restored.

Concrete SSH coordinates, absolute server paths, raw logs, and result geometry
remain in ignored private configuration/evidence and must not enter tracked
files.

## Rejected terminal incident handling

If the frozen postflight rejects an immutable terminal receipt, that rejection
must not be weakened or reinterpreted after the run. The permit remains burned,
the attempt remains failed, and no second launch, candidate, resource change,
or repaired remote artifact is allowed.

A separate read-only incident collector may produce only a canonical
`phase8b.portable-incident.v1` envelope with `status=rejected` and
`acceptance_eligible=false`. It must independently bind the transport inventory,
consumed permit, registration, acknowledgement, compute claim, guardian receipt,
failure envelope, absent final marker, terminated process groups, unchanged
Phase 7 tree, and the frozen inspector hash. It may identify a receipt/claim
null mismatch and a code-level root-cause class, but it must not replace the
receipt's fields, publish final acceptance, or reuse the passed-postflight
schema. Portable incident evidence excludes absolute paths, SSH coordinates,
PIDs, release tokens, raw logs, tracebacks, coordinates, and scratch contents.

Missing endpoint artifacts establish only that zero complete endpoint workflows
and zero accepted final SCF energies were produced. They do not prove that a
PySCF or SCF kernel was never invoked. Such invocation status remains
`indeterminate`; D3 runtime evidence is unavailable and no deprotonation label
may be produced.
