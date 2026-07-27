# Phase 9B Item 10/12 — Split-Process Runtime Report

## Terminal status

Item 10/12 is complete and `prepared_not_authorized`. One user-level assisted
authority is represented by one campaign guardian and one long-lived campaign
supervisor. The supervisor creates two post-registration, one-shot internal
capabilities and runs A1 then A2 without overlap. No server was contacted and no
scientific package was loaded in validation.

The public execution boundary remains closed:

```text
public execution gates       11 / 11 false
real permit generated        false
permit placed/consumed       false / false
deploy or production launch  false
real AIMNet2/PySCF/D3        false / false / false
new labels                   0
production label count       71
```

## Implemented authority and runtime

- The guardian validates request/manifest/resources/source/profile identity,
  consumes exactly one campaign permit only after public gates open, launches
  one supervisor session/process group, waits for a bounded acknowledgement,
  and never waits for science.
- The supervisor validates one pipe-delivered campaign capability, derives the
  `CLOCK_MONOTONIC` deadline in the current boot domain, and owns A1, handoff,
  A2 and route-terminal control.
- Each stage first registers its PID, start time, parent, SID, PGID, exact
  executable, argv and source. Only then does the supervisor construct and
  release `InternalStageCapabilityV1`. Raw release tokens and replayable
  capability bytes are not persisted.
- A1 loads its base model exactly once, handles cation then neutral, and emits
  durable XYZ/trajectory/preoptimization evidence. It cannot import PySCF.
- The handoff is three immutable objects: A1 proposal, supervisor verification,
  and A2 admission. The supervisor never mutates an A1 receipt.
- A2 rereads admitted XYZ through no-follow evidence reads, recomputes byte
  count/hash/order, passes those same bytes to the parser, and invokes the same
  `SharedTwoEndpointPySCFCore` used by direct.
- The campaign limit is 7200 seconds. A1 additionally has a 900-second local
  limit; A2 receives only the remaining absolute deadline. Stage process groups
  are distinct and real process-window evidence proves no overlap.

## Validation

Portable tests cover schemas, authority, immutable receipts, gate-closed
guardian behavior, A1 model-load-once/early-stop, exact-byte handoff, A2 disk
reread, shared-core parity, closure DAG and evidence immutability. The 32
pre-registered mutation cases each name an executable guard.

GitHub Actions Linux run `30270727079`, source-freeze commit
`1e108f9b8ec827dfd5d7109b64b8b7ebd2afdc2f`, ran three fresh campaign supervisor
processes. Each supervisor spawned real fake A1/A2 process groups, completed the
registration/capability/release protocol, accepted the hash-closed handoff, and
proved timeout TERM/KILL/reap cleanup. Every result reported
`synthetic_test_only=true` and `no_chemistry=true`.

## One-time v9 freeze

```text
schema                     nhc-two-endpoint-runner-source-v9
shared schema leaf         3dabcfb2df9dd12ebdc3bab920ec486c5ee3ce8305a5390ca33190d8b7951b5b
shared PySCF core leaf     40ebf95cc709bb18720e9da19bc022d51d285b11cbfcac54620aac1024c57f9e
campaign control leaf      e24c5b7d6a9a4b299d60753239f6088bddbbc341625bc1152e7b0d9ab2fca38e
A1 leaf                    8aab997e67fcadab4f98dc2cb7aaaedece7a83a7c4d58e65b117d9b1ebc9279c
A2 leaf                    fb1a3f62486d6cb354483f8458d8a70ffc63ea35386e5f3fc25f28887b04687c
full composite             13ba49fe33f8a85cceae76b043619df832d15633aa08a91d0eadfab7c6f580f5
```

The full per-file inventory, dependency edges, profile assignments and
independent recomputation result are in `PHASE9B_RUNNER_SOURCE_V9_MANIFEST.json`.
The v8 generation is retained as `superseded_before_execution` and was never
deployed, placed, consumed or launched.

## New paired generation

```text
request id                 phase9b-lbnp-paired-split-process-v003
direct request             84046351c5ba6e1a8087acc6e3070f46ff3429f4781a1bf689a1fa473218c4d3
direct manifest            f6e193706006fc1f6bc937ba636145e1c1617fe9245ea60db9703605f7707d9a
assisted request           24a1caf75b9cdbd061e366eab3202e7d1511d46ed2ca70245b4390fc04681933
assisted manifest          ed91373bf0ced4a1d100f51966a8010812b41c9e55dbdf0ce56f68f5d06b1904
campaign resources         39d1be30f30c85a21452a30548b5ba97414cb106461e8d0104beb6c34618c0ab
state                      prepared_not_authorized
real permit generated      false
```

## Only next work

Item 11/12 split-process-aware Postflight is the only allowed next stage. It
must validate guardian, supervisor, A1, handoff, A2, two interpreters, source
leaves, non-overlap, process absence, final PySCF evidence and partial terminal
trees. This report does not authorize Postflight implementation, rehearsal or
execution.
