# Phase 9B Identity Re-baseline

## Why

Two rounds of closure work have now moved the source identity. The first, the
pre-launch integration closure, took it from v4 to v5. The second, the guardian
and handoff round, takes it from v5 to v6:

```text
quantum/one_shot_permit.py      new: the shared consumption transaction, so the
                                race-critical code exists once for both chains
quantum/phase9b_guardian.py     new: the guardian transaction
quantum/phase9b_handoff.py      new: the AIMNet2-to-PySCF handoff contract
quantum/phase8b_permit.py       consumption now delegates to the shared primitive
quantum/phase9b_permit.py       permit schema v2, single-transaction Route A
quantum/two_endpoint.py         request schema v2, closure membership 18 -> 21
```

Editing any file in `_RUNNER_SOURCE_RELATIVE_PATHS` changes
`runner_source_sha256`. Every Phase 9B request, payload manifest, and one-shot
permit is bound to that digest, so all of them are **superseded**.

## Status of the previous identities

```text
runner source schema   nhc-two-endpoint-runner-source-v4
runner_source_sha256   2059b35d0e62bc844e7fc602929e9e53b79cd3e9fcc6644fb4e67580e1a5a52c
state                  superseded_before_execution

runner source schema   nhc-two-endpoint-runner-source-v5
runner_source_sha256   c914afe3f166ea1ef47dd2e27901aac660c918d110f51299c806ee605164fea8
direct request         8f8d892b8f161f4aafb6fb03c712f531c0acdb590850ccf7ffcc8c772387546a
direct manifest        1c0ef215b234033dc545ac5f5e613bc9757c34bf2a8e7e77d5a8df387a2d1c0f
assisted chain         never generated
state                  superseded_before_execution
```

**They were never deployed, never launched, and never consumed.** No permit
crossed its irreversible point, no remote root was created, and no attempt was
opened in the guarded runner. They are not `consumed`, not `failed`, and not
`rejected` — those words describe Phase 8B's QXH attempt, which is a different
thing entirely and remains permanently unusable.

`superseded_before_execution` means exactly: the source identity they referenced
no longer exists, so they can no longer authorize anything. Nothing was
overwritten and nothing was deleted; this record preserves them.

## The final closure

```text
runner source schema   nhc-two-endpoint-runner-source-v6
runner_source_sha256   72125b67abc9e52d41a41bc6d3f4dc5ce9a999d1f577717b30c011076de10de3
direct request         a53c26201fd1f2989fd242681c3c382fd17cc1c88c1433cd5dcc7c0a58ec04d2
direct manifest        f73cdb9a3a34fe49738994800a1d7d79bc0b854ae197a385c3151cce2c8305b5
assisted request       feaecb7b6de9e7ab0f8710b4fd9e094d019b3cc6c1f68d349dc901137ebe7659
assisted manifest      bc0534f72fe16eb69338af1eb897c3a705b71b7973825f7a4fe9e9732e236d7b
state                  superseded_before_execution

runner source schema   nhc-two-endpoint-runner-source-v7
runner_source_sha256   d7060a314993225595c616f4329b08689c6974de621ef663c18f891d6a7d9c22
direct request         acc22c67ba07e245ae001211cfb34038eeb486c3a4fbccdefdf6991b35d66635
direct manifest        906b1f39982107218fec079150851b9d14a4d9a3e4d43bf401c2dec00ed3afa9
assisted request       b74cd3b7e433059ea5d5a9ae213917766a236f4a2c72ef97e3edc9fe6298bef1
assisted manifest      d23b12f9d7b31c6e6bd19665cf847e1f45ab6ec8825ff86a84e560fcf1f56081
state                  superseded_before_execution

runner source schema   nhc-two-endpoint-runner-source-v8
runner_source_sha256   5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2
closure files          23 (two added: execution adapters, AIMNet2 runtime)
resources_sha256       0fec2c1914f413a2762e1fafc7daa9900551981b5af72897746864edffac7df8
request schema         nhc-two-endpoint-request-v2
permit schema          nhc-phase9b-private-permit-v2
```

The resource budget is byte-identical, so `resources_sha256` did not move. The
candidate profile, its two geometry digests, the atom map, the locked protocol,
the request ID, and both attempt IDs are also unchanged. Only the source digest
moved, and everything downstream of it was rebuilt.

The AIMNet2 stage identity the assisted permit binds:

```text
optimizer protocol     1b4e4f136ae74d56a70444386ec3a5d92d9329790fd9dc7e34a9f6cb571dc8bc
structural gates       92cf1219ee7fe25129bc26a69243428390ff763d6df4842f01fe33ac49ee85ae
handoff contract       8a2acad53db472ae0c70b8c944cf1820ee022cf376974bd830eb7922db2d3e85
stage digest           e1a3bab60805fac242b870692cb18a750442d7576cee34447749b7b53a923cb1
weight                 aimnet2_wb97m_d3_0.pt, 8836941 bytes
                       f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28
```

## Regenerated identities

Both routes are now fully determined. The assisted chain is no longer pending:
under the single-transaction design it starts from the same frozen Phase 7
initial geometry as the direct route, and binds the AIMNet2 *stage* rather than a
preoptimized geometry that cannot exist before the route runs.

### Route D — direct

```text
request_id              phase9b-lbnp-paired-smoke-v001
attempt_id              attempt-phase9b-lbnp-direct-v001
runner_source_sha256    5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2
request_sha256          acc22c67ba07e245ae001211cfb34038eeb486c3a4fbccdefdf6991b35d66635
payload_manifest_sha256 906b1f39982107218fec079150851b9d14a4d9a3e4d43bf401c2dec00ed3afa9
preoptimization         stage: none
```

### Route A — assisted

```text
request_id              phase9b-lbnp-paired-smoke-v001   (shared)
attempt_id              attempt-phase9b-lbnp-assisted-v001
runner_source_sha256    5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2
request_sha256          b74cd3b7e433059ea5d5a9ae213917766a236f4a2c72ef97e3edc9fe6298bef1
payload_manifest_sha256 d23b12f9d7b31c6e6bd19665cf847e1f45ab6ec8825ff86a84e560fcf1f56081
preoptimization         stage: aimnet2, runs_inside_route: true
cation/neutral xyz      identical to Route D
```

### What the two share and what differs

```text
initial cation xyz      identical
initial neutral xyz     identical
atom order              identical
charge and multiplicity identical per endpoint
PySCF protocol          identical
resources               identical
runner source           identical
request id              identical
attempt id              distinct
request digest          distinct
manifest digest         distinct
permit                  distinct
remote root             distinct, frozen per route
preoptimization stage   THE experimental variable
```

`validate_route_parity` now enforces exactly that: shared geometry, one differing
field. It also refuses a pair where both declare the same stage, or where the
direct route declares AIMNet2.

### Both permits

Permit digests are **not recorded in this repository**, and that is deliberate
rather than an omission. A permit's canonical bytes include `paths`, which is
built from the private absolute project root on the server. The permit is
rendered at placement time and recorded in the private `PermitPlacementReceipt`,
which never enters Git.

## Ordering

This is the order the authority chain requires, and the reason it cannot be
reordered:

```text
1  edit and test every closure file with the gate closed
2  freeze runner_source_sha256                            <- this document
3  build both requests against the frozen digest
4  build both payload manifests against their requests
5  render both permits against their manifests
6  deploy both payloads          (permits excluded)
7  place both permits            (after promotion, before launch)
8  launch: start the guardian on each route
9  guardian consumes the permit, spawns the supervisor, returns an ack
10 Route A runs AIMNet2 inside the route, closes the handoff, then PySCF
```

Building a permit before step 2 and editing source afterwards would leave a
permit bound to a digest the code no longer has. Requiring the assisted permit to
name a preoptimized geometry would have made step 5 depend on step 10, which is
the circularity this round removed.

## What is still not wired

**Postflight does not exist.** That is item 9/10 and remains deliberately not
started in Phase 9B-U1.

**The production AIMNet2 runtime is implemented, but no validated unified
environment identity exists.** U1 created and populated a new v001 prefix, then
failed its capability harness on four observed calculator invocations versus
two expected. The prefix is retained as `failed_incomplete_environment` and is
unusable; it does not move the runner source schema or authorize a route.

**The current control-plane identities do not bind an interpreter.** The v8
preflight invokes unbound `python3`, and resources/request/permit contain no
unified-environment identity. Those are explicit schema/integration gaps for a
future gate-closed round, not fields to add silently during installation.

No Phase 9B payload has been deployed, no permit placed or consumed, and no
guardian, supervisor or worker launched. Every public execution gate is closed.
The v8 source digest remains
`5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2`.

## U2 did not create a new execution identity

Phase 9B-U2 left the v8 closure byte-identical and matched its frozen capability
call semantics, but ended `rejected_environment`: its protected before/after
snapshot payloads used different top-level key sets (`state` absent versus
`state=present`). The target-tree digest and all physical protected evidence
remain retained, but no `UnifiedExecutionEnvironmentIdentity v2` or
`environment_canonical_sha256` was issued. Consequently no resources, request,
permit, or preflight identity was regenerated, and every v8 identity remains
blocked rather than superseded.

## U3 pre-creation terminal outcome

Phase 9B-U3 did not reach environment identity construction. Its document-first
metrology code stayed outside the runner closure, so schema v8 and the SHA256
above remain unchanged. The read-only six-object measurement qualification
returned stable `state=invalid` captures and terminated as
`failed_before_environment_creation`; the v003 prefix, wheelhouse, and cache
were never created. No `UnifiedExecutionEnvironmentIdentity v3` or environment
canonical SHA256 exists, and there is nothing eligible to integrate or
supersede before execution.
