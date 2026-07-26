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
runner_source_sha256   22610234a42735541c5cbd12bacbdfbe48ad43e10fdab671dd70b9ccf11526dc
closure files          21 (three added)
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
runner_source_sha256    22610234a42735541c5cbd12bacbdfbe48ad43e10fdab671dd70b9ccf11526dc
request_sha256          05e266cb47528e81ee2e48ac5748989c8bb23896ba5adf7ca64d6f58fb317bdb
payload_manifest_sha256 78aace2a77d792e6a5960d994a18a45469bb2d48b1bbc4efd02bccf4e7f6404b
preoptimization         stage: none
```

### Route A — assisted

```text
request_id              phase9b-lbnp-paired-smoke-v001   (shared)
attempt_id              attempt-phase9b-lbnp-assisted-v001
runner_source_sha256    22610234a42735541c5cbd12bacbdfbe48ad43e10fdab671dd70b9ccf11526dc
request_sha256          30ad9e2618efb2698bd0f2e328546b521a70e305dcfc2eca9e6361c2fce748f5
payload_manifest_sha256 cfb7125c4782f0f1618108a760d50f29c244ac431207c6dd01d75506efa50d68
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

**Postflight does not exist.** That is item 8/8 and is deliberately not started
until every interface above is frozen.

**The AIMNet2 stage has no runtime implementation inside the route.** The handoff
contract, its receipts, and the gate that stops PySCF are built and tested; what
produces the preoptimized geometry under the permit is not. Route A cannot run
until it exists, and Route D is unaffected.

**Nothing here has been executed.** No server was contacted, no permit was placed
or consumed, no guardian ran, and no supervisor was spawned. Every gate is closed.
