# Phase 9B Item 11 — Postflight Evidence Gap Report

## Terminal decision

```text
item                         11/12 split-process-aware Postflight
status                       blocked_by_v9_evidence_gap
runner source                nhc-two-endpoint-runner-source-v9
runner composite SHA256      13ba49fe33f8a85cceae76b043619df832d15633aa08a91d0eadfab7c6f580f5
runner modified              false
v10 generated                false
SSH/server access            false
real Postflight executed     false
real permit                  none
real chemistry               none
new labels                   0
production labels            71
public execution gates       11/11 false
```

The Evidence Sufficiency Audit found acceptance-blocking gaps before any
Postflight implementation. Per the frozen Item 11 stop rule, no reader,
inspector, fixture system or Linux process suite was implemented. No gap was
converted to `pass`, inferred from logs or mtime, or repaired in v9.

## Acceptance-blocking gaps

### GAP-01 — production stage capability consumption is not durable

The campaign supervisor requires
`runtime/stage_a1/capability_consumption.json` after a successful A1 child and
the equivalent A2 receipt after a successful A2 child. The production A1 and A2
entrypoints call `run_registered_stage_bootstrap()`, receive the in-memory
capability, and proceed without writing either receipt.

The only writer of `StageCapabilityConsumptionReceiptV1` is
`preparation/phase9b_item10_fake_stage.py`. Thus the Linux fake campaign can be
accepted while the production campaign cannot pass the same supervisor read.

Affected routes/terminals: every production assisted terminal that would pass
A1; A2 is unreachable. This is acceptance-blocking and also a runtime
reachability defect.

### GAP-02 — the paired direct v003 route has no production authority chain

The paired generation binds `attempt-phase9b-lbnp-direct-v003`, and a direct v3
execution adapter exists. However, the externally exposed direct guardian,
launch planner, permit/guardian/supervisor constants and worker authority
registry remain bound to the v001 direct attempt. In particular, the worker
registry contains no v003 direct profile.

Affected routes/terminals: all direct v003 not-started/running/accepted/rejected
authority and process states. A synthetic adapter call cannot prove the missing
permit, guardian, registration, compute-claim or cleanup chain. This is
acceptance-blocking.

### GAP-03 — A2 disk-to-parser proof is process-local only

`A2DiskInputEvidence` contains the required disk byte count/SHA, parser-input
SHA and element-order SHA, but `run_stage_a2()` only returns this object to its
caller. The production `main()` discards it. No A2 input-evidence receipt is
written.

The A2 terminal digest includes only the two disk SHA strings and admission
SHA. It does not include parser-input SHA, byte counts, element order or an A2
input receipt SHA.

Affected route/terminal: accepted assisted. A future Postflight cannot
independently prove
`A2 disk bytes == A2 parser input bytes`. This is acceptance-blocking.

### GAP-04 — the assisted campaign does not bind its shared-core result tree

The shared PySCF core writes an internally verifiable ordinary output tree.
`runtime/stage_a2/route_result.json` copies only the final label and does not
store the shared-core result SHA, endpoint-result SHAs, A2 input provenance or
output-root identity. The A2 terminal likewise does not bind those objects, and
the campaign final manifest covers only the campaign evidence store.

Affected route/terminal: accepted assisted. D3, SCF, endpoint energies,
optimized XYZ and the label can be validated inside the shared-core tree, but
the required cryptographic join from that tree to the A2/campaign evidence is
missing. This is acceptance-blocking.

### GAP-05 — required A1 execution metrology is not durable

Production A1 checks `model_load_count == 1` in memory. Its durable
preoptimization receipts record optimizer steps and calculator invocations but
not:

- base-model load count;
- endpoint-wrapper count;
- the frozen loader options (`compile_model=false`,
  `validate_species=true`);
- the full optimizer contract (`fmax`, max steps and restart policy);
- initial/final energy and force-finiteness evidence;
- `base_model_forward_calls=unmeasured`.

The fake Linux A1 receipt happens to write a model-load count, but that fixture
field is absent from the production writer and cannot qualify production
evidence.

Affected route/terminal: accepted assisted. Source control flow is not runtime
evidence, so model-load-once and the requested A1 capability contract cannot be
independently established. This is acceptance-blocking.

### GAP-06 — exact private profile and guardian process identity are not durable

The internal stage capability contains a private interpreter-binding digest and
full process binding but is intentionally not persisted. Registration preserves
the executable hash and stage/supervisor process fields, while the intended
`stage_a1/identity.json` and `stage_a2/identity.json` paths have no production
writer. The stable profile appears in proposal/admission, but the private
binding cannot be recovered.

The assisted guardian launch receipt preserves only a digest of supervisor
PID/PGID/SID/argv data and no raw guardian PID/start-time identity. Postflight
therefore cannot prove exact guardian absence or safe PID reuse as required.

Affected route/terminal: accepted assisted authority and process cleanup. This
is acceptance-blocking.

### GAP-07 — many registered terminal classifications have no durable terminal

Guardian spawn/ack exceptions and several supervisor, registration, handoff and
admission exceptions escape before a campaign terminal/final manifest is
written. A2 collapses all shared-core nonzero exits to `rejected_cation`.
Consequently the requested terminal-specific exact trees for spawn, timeout,
neutral, D3, evidence and indeterminate outcomes cannot all be derived from v9
writers.

Affected routes/terminals: multiple assisted partial/rejected/indeterminate
states. A read-only observer could call them incomplete or indeterminate, but
could not recover the frozen detailed classification. This prevents the full
Item 11 terminal contract and is acceptance-blocking for Item 11 completion.

### GAP-08 — guardian evidence is outside the supervisor's manifest registry

The guardian and campaign supervisor each construct a separate
`CampaignEvidenceStore`. Its registered file set is process-local. The guardian
writes the permit-consumption and guardian-launch receipts, but the supervisor
never reads/adopts either file before building the preterminal/final manifests
and calling `assert_no_extra_files()`.

If the guardian files already exist, the supervisor treats them as unregistered
extras. If the supervisor finishes first, the guardian can add
`guardian_launch.json` after the final manifest, leaving it unbound. No ordering
makes a full accepted guardian+supervisor tree both exact and manifest-closed.

Affected route/terminal: every full assisted launch, including an otherwise
accepted campaign. This is acceptance-blocking.

## Performance-only gaps

These gaps would not by themselves convert a scientifically rejected route into
an invalid Postflight, but their fields must be `unavailable`:

- guardian and supervisor startup durations;
- model-load duration;
- per-endpoint A1 wall time;
- handoff and terminal-publication costs on rejected paths;
- actual CPU time and GPU utilization;
- complete historical process windows for rejected campaigns;
- PySCF SCF-cycle, energy-call, gradient-call and geometry-step counters, which
  are not present in the shared-core endpoint schema.

The accepted-only `process_tree.json` provides coarse A1/handoff/A2 monotonic
windows. It does not supply the missing detailed performance accounting.
Nothing may be estimated from mtime, logs or wall-time multiplied by a resource
envelope.

## Evidence that remains useful

The audit did not discard v9. Existing bytes still prove important design and
implementation facts:

- the three handoff receipt schemas are immutable and hash-linked;
- A1 output XYZ, trajectory and preoptimization receipts are durable;
- supervisor verification rereads A1 files;
- shared-core endpoint records contain convergence, D3 arithmetic and final
  energies;
- the accepted-only process tree can encode A1/A2 non-overlap;
- the preterminal manifest can be reconstructed from a valid final manifest by
  removing both terminal copies and the final manifest path;
- direct and A2 call the same source-frozen shared PySCF core.

These facts are insufficient for an accepted Postflight under the present
contract, but they remain retained provenance.

## Why a reader cannot close the gaps

Adding a Postflight reader would not create bytes that the writer never wrote.
The missing facts cannot be recovered safely from:

- source control flow, because Postflight must prove actual execution;
- logs, because logs are not structured acceptance evidence;
- file mtime, because it does not prove process order or scientific identity;
- the fake Linux stage, because it is outside v9 production leaves;
- the remote inspector's own booleans, because local validation must recompute
  from durable payloads;
- a synthetic accepted tree, because synthetic fixtures cannot authorize or
  characterize a future production run.

## Frozen identities remain unchanged

Item 11 did not edit any v9 leaf, dependency edge, deployment inventory,
paired-generation request, manifest or resources. The retained identities are:

```text
shared schema       3dabcfb2df9dd12ebdc3bab920ec486c5ee3ce8305a5390ca33190d8b7951b5b
shared PySCF core   40ebf95cc709bb18720e9da19bc022d51d285b11cbfcac54620aac1024c57f9e
campaign control    e24c5b7d6a9a4b299d60753239f6088bddbbc341625bc1152e7b0d9ab2fca38e
A1                  8aab997e67fcadab4f98dc2cb7aaaedece7a83a7c4d58e65b117d9b1ebc9279c
A2                  fb1a3f62486d6cb354483f8458d8a70ffc63ea35386e5f3fc25f28887b04687c
full composite      13ba49fe33f8a85cceae76b043619df832d15633aa08a91d0eadfab7c6f580f5
deployment inventory
                    6b51e853dfdad8a0c8e8648dd7bc45007a611b6340496ad370cbc08121d6b6f4
```

The v8 source remains retained as `superseded_before_execution`. No v10 or
other successor identity was calculated.

## Required next authorization

Item 12 cannot start. The next work requires a new, explicit runner-remediation
design authorization that permits changing and superseding v9 before any
execution. That design must at minimum specify:

1. a production writer for both stage capability-consumption receipts;
2. a real direct-v003-or-successor guardian/permit/worker authority chain;
3. durable A1 metrology and A2 disk/parser evidence;
4. a hash-closed campaign-to-shared-core result binding;
5. durable private-profile and guardian/process identities;
6. structured terminal/finally evidence for all partial states;
7. one new source and paired-generation freeze after implementation and tests;
8. a renewed Postflight Evidence Sufficiency Audit before Postflight code.

This report does not authorize those runner changes, a new source version,
Postflight implementation, rehearsal or execution.
