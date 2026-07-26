# Phase 9B Identity Re-baseline

## Why

The Phase 9B pre-launch integration closure edited three files inside the runner
source closure:

```text
quantum/phase9b_supervisor.py   gained the formal thirteen-flag CLI
quantum/two_endpoint.py         capability expectation became a multi-attempt
                                registry; handshake attempt gate became a
                                registry; guarded Phase 9B executor adapter added
```

Editing any file in `_RUNNER_SOURCE_RELATIVE_PATHS` changes
`runner_source_sha256`. Every Phase 9B request, payload manifest, and one-shot
permit is bound to that digest, so all of them are **superseded**.

## Status of the previous identities

```text
runner source schema   nhc-two-endpoint-runner-source-v4
runner_source_sha256   2059b35d0e62bc844e7fc602929e9e53b79cd3e9fcc6644fb4e67580e1a5a52c
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
runner source schema   nhc-two-endpoint-runner-source-v5
runner_source_sha256   c914afe3f166ea1ef47dd2e27901aac660c918d110f51299c806ee605164fea8
closure files          18 (unchanged membership; three contents changed)
resources_sha256       0fec2c1914f413a2762e1fafc7daa9900551981b5af72897746864edffac7df8
```

The resource budget is byte-identical, so `resources_sha256` did not move. The
candidate profile, its two geometry digests, the atom map, the locked protocol,
the request ID, and both attempt IDs are also unchanged. Only the source digest
moved, and everything downstream of it was rebuilt.

## Regenerated identities

### Route D — direct

Fully determined by the final closure and the frozen Phase 7 geometry:

```text
request_id             phase9b-lbnp-paired-smoke-v001
attempt_id             attempt-phase9b-lbnp-direct-v001
runner_source_sha256   c914afe3f166ea1ef47dd2e27901aac660c918d110f51299c806ee605164fea8
request_sha256         8f8d892b8f161f4aafb6fb03c712f531c0acdb590850ccf7ffcc8c772387546a
payload_manifest_sha256 1c0ef215b234033dc545ac5f5e613bc9757c34bf2a8e7e77d5a8df387a2d1c0f
```

### Route A — assisted

**Not yet determinable, and deliberately not fabricated.**

The assisted request declares the SHA256 of the *preoptimized* cation and neutral
geometries. Those files do not exist: producing them requires running AIMNet2,
which this authorization prohibits. The manifest binds the request digest and the
permit binds the manifest digest, so the whole assisted chain is blocked on that
one output.

What is fixed now:

```text
request_id             phase9b-lbnp-paired-smoke-v001   (shared)
attempt_id             attempt-phase9b-lbnp-assisted-v001
runner_source_sha256   c914afe3f166ea1ef47dd2e27901aac660c918d110f51299c806ee605164fea8
protocol_sha256        identical to Route D
resources_sha256       identical to Route D
cation/neutral xyz     pending AIMNet2 preoptimization
request_sha256         pending
payload_manifest_sha256 pending
```

Writing placeholder digests here would produce a permit that could never validate
against the real files, which is worse than recording the gap. The assisted chain
is generated in the same step that produces its geometry, against this same source
digest — `tests/test_phase9b_identity_rebaseline.py` asserts that binding.

### Both permits

Permit digests are **not recorded in this repository**, and that is deliberate
rather than an omission. A permit's canonical bytes include `paths`, which is
built from the private absolute project root on the server. Recording the digest
would not leak the path, but the digest is only meaningful alongside it, and the
permit is rendered at placement time in any case. It is recorded in the private
`PermitPlacementReceipt`, which never enters Git.

## Ordering

This is the order the authority chain requires, and the reason it cannot be
reordered:

```text
1  edit and test every closure file with the gate closed
2  freeze runner_source_sha256                            <- this document
3  build the request against the frozen digest
4  build the payload manifest against the request
5  render the permit against the manifest
6  deploy the payload            (permit excluded)
7  place the permit             (after promotion, before launch)
8  launch both routes
```

Building a permit before step 2 and editing source afterwards would leave a
permit bound to a digest the code no longer has, which is precisely the situation
this document closes out.

## What is still not wired

Recorded here rather than left implicit:

**The Phase 9B guardian transaction does not exist.** In Phase 8B the thing that
runs on the server is `phase8b_runtime` in `guardian` mode: it consumes the permit
irreversibly, then re-executes itself in `supervisor` mode, and only that mode
constructs the `Phase8BWorkerLaunch` handshake and calls the supervised runner.
Phase 9B has the supervisor CLI and the executor adapter, but no guardian, so
`main` takes the handshake through an injected factory and refuses when none is
wired. A real Phase 9B run needs that module before anything can start.

**The launch transport is not reconciled with a 7200 s run.** The supervisor CLI
prints its identity and then blocks in supervised execution for up to the frozen
wall-time, while `phase9b_launch` reads stdout under a bounded timeout. A real
launch therefore needs either a transport that returns after the identity line or
a detached guardian. Neither is built, and the launch control plane would report
`indeterminate` rather than claim success — which is the correct failure, but it
is not a working configuration.
