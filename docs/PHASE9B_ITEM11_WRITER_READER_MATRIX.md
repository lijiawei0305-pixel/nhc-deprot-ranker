# Phase 9B Item 11 — v9 Writer / Future Reader Matrix

## Audit outcome

This matrix is derived from the frozen v9 writer control flow at composite
SHA256
`13ba49fe33f8a85cceae76b043619df832d15633aa08a91d0eadfab7c6f580f5`.
It does not treat `CAMPAIGN_ALLOWED_PATHS` as a terminal required-path set.
That constant is only a write/read allowlist. A path below is required only
when the named writer actually reaches its write.

The audit found acceptance-blocking gaps. Item 11 therefore stops before a
Postflight implementation. The disposition and required next authorization are
in `PHASE9B_ITEM11_EVIDENCE_GAP_REPORT.md`.

The Phase A document named
`PHASE9B_CAMPAIGN_SUPERVISOR_STATE_MACHINE.md` no longer exists under that
name. Its merged replacement,
`PHASE9B_ATTEMPT_AND_PROCESS_STATE_MACHINES.md`, was audited instead.

## Static and authority objects

| Evidence path or object | Writer | Write condition | Owner / immutable | Accepted route | Rejected, partial or indeterminate route | Future reader obligation | Cross-file binding | Independently reconstructable? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `input/request.json` | v3 bundle/deploy preparation | Before any launch | deploy-owned static bytes | Required | Required if deployed | Exact bytes, SHA, v3 schema, generation, candidate, route, attempt, profiles, sources, resources and endpoint inputs | v3 manifest and permit | Yes, if deployed |
| `payload_manifest.json` or deployed manifest location | v3 bundle/deploy preparation | Before any launch | deploy-owned static bytes | Required | Required if deployed | Exact bytes/SHA, static file inventory and no mixed generation | request, source DAG, resources | Yes, if deployed |
| `xyz/cation.xyz`, `xyz/neutral.xyz` | deploy preparation | Before any launch | static payload | Required | Required if deployed | Exact bytes/SHA, atom counts/order and frozen initial identity | request and manifest | Yes |
| ready permit | later permit placement, not Item 10 | Before launch only | one-shot private authority | Forbidden after launch | May exist only for `not_started` | ready-only means not started; ready plus consumed is invalid | request/manifest/resources/source/profile/attempt | No real permit exists in the current generation |
| consumed permit | one-shot permit primitive | Successful permit consumption | immutable private authority | Required after launch | Required after any irreversible consumption | Exact bytes and absence of restored ready permit | consumption receipt and route identity | Yes if a real permit had existed |
| `runtime/evidence/permit_consumption.json` | assisted campaign guardian | Immediately after permit consumption | guardian; exclusive write | Required | Present after consumption even if later spawn/ack fails | Exact schema and permit/consumed hashes | consumed permit | Bytes are readable, but supervisor never adopts this file into its final manifest |
| `runtime/campaign/guardian_launch.json` | assisted campaign guardian | Only after supervisor acknowledgement | guardian; exclusive write | Required | Absent on spawn or acknowledgement exception | Validate exact bytes and hashes; do not infer failure class from absence alone | permit consumption and acknowledgement hash | Guardian process identity is missing, and supervisor never adopts this file into its final manifest |

## Assisted campaign evidence tree

| Evidence path | Writer | Write condition | Owner / immutable | Accepted | Rejected / partial | Future reader validation | Cross-file bindings | Independently reconstructable? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `runtime/campaign/campaign_identity.json` | campaign supervisor | Start of `run_assisted_campaign` | supervisor; exclusive write | Required | Present only after supervisor enters runtime | Strict `AssistedCampaignIdentityV1` | request, manifest, resources, composite source, stable profiles | Yes |
| `runtime/campaign/campaign_schedule.json` | campaign supervisor | After current supervisor process identity is read | supervisor; exclusive write | Required | Present after schedule derivation | Start/deadline arithmetic, boot and clock digests | internal capabilities and terminal | Yes |
| `runtime/campaign/campaign_ack.json` | campaign supervisor | Runtime initialization | supervisor; exclusive write | Required | May be present without a terminal | Capability and campaign identity hashes | guardian acknowledgement | Partly; raw supervisor identity is only a digest here |
| `runtime/stage_a1/process_registration.json` | A1 sends; supervisor persists | A1 registers and exact PID/PGID/argv/source checks pass | A1 content, supervisor write | Required | Optional before A1 launch failure | Strict registration and live/terminal process identity | acknowledgement and capability | Yes |
| `runtime/stage_a1/capability_digest.json` | supervisor | After verified A1 registration and capability issue | supervisor; digest only | Required by intended chain | Optional | Digest/token non-persistence assertions | acknowledgement and consumption receipt | Raw capability is intentionally not reconstructable |
| `runtime/stage_a1/acknowledgement.json` | supervisor | After A1 capability construction | supervisor; exclusive write | Required | Optional | Registration/capability/token digest equality | registration and consumption | Yes |
| `runtime/stage_a1/capability_consumption.json` | **only Item 10 fake stage** | Fake stage consumes release frame | fake fixture; exclusive write | Supervisor requires it | Missing from production A1 | Exact one-shot consumption and consumer identity | registration, capability and token digests | **No production writer** |
| `runtime/stage_a1/{endpoint}/input.xyz` | production A1 | Endpoint runtime succeeds | A1; immutable data mode | Both required | Cation may exist before neutral rejection | Exact bytes/SHA/order and initial endpoint identity | request, preoptimization receipt and proposal | Yes |
| `runtime/stage_a1/{endpoint}/output.xyz` | production A1 | Endpoint runtime succeeds | A1; immutable data mode | Both required | Cation may exist before neutral rejection | Exact bytes/SHA/count/order/finite coordinates | preoptimization receipt, proposal, verification and admission | Yes |
| `runtime/stage_a1/{endpoint}/trajectory.jsonl` | production A1 | Endpoint runtime succeeds | A1; immutable data mode | Both required | Cation may exist before neutral rejection | Strict trajectory frames and digest | preoptimization receipt and proposal | Bytes exist, but required production metadata is incomplete |
| `runtime/stage_a1/{endpoint}/preoptimization_receipt.json` | production A1 | Endpoint runtime succeeds | A1; exclusive write | Both required | Cation may exist before neutral rejection | Endpoint, charge/mult, hashes, gates, force/counts | proposal and verification | Yes for fields actually written |
| `runtime/stage_a1/handoff_proposal.json` | production A1 | Both endpoints accepted | A1; immutable receipt | Required | Forbidden after A1 rejection | Strict canonical proposal and self-digest | endpoint files/receipts and A1 source/profile/weight/protocol | Yes |
| `runtime/stage_a1/terminal.json` | production A1 | A1 returns accepted or catches endpoint exception | A1; immutable receipt | Required | Required for caught cation/neutral rejection; absent on uncaught/bootstrap failure | State, evidence hash and failure shape | proposal when accepted | Yes when present |
| `runtime/handoff/verification.json` | supervisor | A1 accepted and verification returns | supervisor; immutable receipt | Required | May be absent if verification raises | Recompute every observed file; never trust booleans alone | proposal, A1 files and process-absence digest | Yes for recorded files; exact-file-set boolean was hard-coded true |
| `runtime/handoff/a2_admission.json` | supervisor | Verification accepted and remaining budget positive | supervisor; immutable receipt | Required | Forbidden before accepted handoff | Proposal/verification hashes, XYZ hashes/counts, A2 source/profile/core/schema/deadline | proposal, verification and schedule | Yes |
| `runtime/stage_a2/process_registration.json` | A2 sends; supervisor persists | A2 registers and exact checks pass | A2 content, supervisor write | Required | Optional on A2 launch failure | Same process checks as A1 | acknowledgement and capability | Yes |
| `runtime/stage_a2/capability_digest.json` | supervisor | After verified A2 registration | supervisor; digest only | Required by intended chain | Optional | Capability/token digest identity | registration, acknowledgement and consumption | Raw capability is not reconstructable |
| `runtime/stage_a2/acknowledgement.json` | supervisor | After A2 capability construction | supervisor; exclusive write | Required | Optional | Registration/capability/token digest equality | registration and consumption | Yes |
| `runtime/stage_a2/capability_consumption.json` | **only Item 10 fake stage** | Fake A2 consumes release frame | fake fixture; exclusive write | Supervisor requires it | Missing from production A2 | Exact one-shot consumption and consumer identity | registration, capability and token digests | **No production writer** |
| `runtime/stage_a2/cation/input.xyz`, `neutral/input.xyz` | none in v9 production | Never | allowlist entries only | Absent | Absent | Must not be treated as required | none | No |
| `runtime/stage_a2/cation/endpoint_result.json`, `neutral/endpoint_result.json` | none in v9 production | Never | allowlist entries only | Absent | Absent | Must not be treated as campaign evidence | shared-core result tree is separate | No |
| `runtime/stage_a2/route_result.json` | production A2 | Shared core exits zero and its `result.json` is found | A2; exclusive write | Intended required | Absent on core failure | Status/source/label only | No stored shared-core result SHA | Partly; label source binding is insufficient |
| `runtime/stage_a2/terminal.json` | production A2 | Shared core returns | A2; immutable receipt | Intended required | Core nonzero is always called `rejected_cation` | State and evidence digest | Digest covers only two disk hashes plus admission hash | Yes, but insufficient for parser/result proof |
| `runtime/evidence/process_tree.json` | supervisor | **Only after A1, handoff and A2 all accepted** | supervisor; exclusive write | Required | Absent for every rejected path | A1/handoff/A2 windows, no overlap and cleanup booleans | registrations, schedule and live `/proc` observation | Yes on accepted path |
| `runtime/campaign/campaign_terminal.json` | supervisor | Accepted path or selected handled rejection branch | supervisor; immutable | Required | Missing on uncaught supervisor, handoff or stage exceptions | Strict terminal and preterminal-manifest binding | schedule, stage terminals, verification and admission | Yes when present |
| `runtime/evidence/route_terminal.json` | supervisor | Same call as campaign terminal | supervisor; byte-for-byte copy | Required | Same availability as campaign terminal | Exact raw-byte equality, not parsed-object equality | campaign terminal | Yes |
| `runtime/evidence/evidence_manifest.json` | supervisor | After terminal and route-terminal writes | supervisor; immutable final manifest | Required | Present only if `_write_campaign_terminal` completes | Verify every entry; reconstruct preterminal manifest by removing the two terminals and final manifest | campaign terminal preterminal SHA | Yes when present |

`runtime/stage_a1/identity.json` and `runtime/stage_a2/identity.json` are also
allowlist-only entries. No production writer creates either file. A
terminal-specific reader must not require them, and their absence means the
private interpreter binding carried only inside the non-persisted capability
cannot be recovered from those paths.

## Shared PySCF result tree

The shared core writes an ordinary result tree at the separately supplied
`output_root`; it is not part of `CampaignEvidenceStore` or the campaign final
manifest.

| Result path | Writer / condition | Accepted | Failure | Reader validation | Campaign binding | Independently reconstructable? |
| --- | --- | --- | --- | --- | --- | --- |
| `attempts/<attempt>/cation.optimized.xyz` | shared core after accepted cation optimization/SCF | Required | May exist before later failure | Exact XYZ, hash and atom order | cation record only | Yes |
| `attempts/<attempt>/cation.json` | shared core after accepted cation | Required | May exist before neutral failure | PySCF protocol, convergence, D3 and energy | request/attempt/input hash | Yes |
| `attempts/<attempt>/neutral.optimized.xyz` | shared core after accepted neutral | Required | Absent on cation failure | Exact XYZ, hash and atom order | neutral record | Yes |
| `attempts/<attempt>/neutral.json` | shared core after accepted neutral | Required | Absent on cation failure | Same validator as cation | request/attempt/input hash | Yes |
| `attempts/<attempt>/result.json` | shared core after both endpoints and label | Required | Forbidden on endpoint failure | Endpoint records, protocol, energies and label formula | `_ATTEMPT_SUCCESS` and top-level success | Yes within this result tree |
| `attempts/<attempt>/_ATTEMPT_SUCCESS` | shared core after `result.json` | Required | Forbidden | Result SHA and identity | result | Yes |
| `attempts/<attempt>/failure.json` | shared core caught failure | Forbidden | Expected when durable failure publication succeeds | Stage/error/attempt/request/candidate | partial endpoint files | Yes |
| `success.json`, `_SUCCESS` | shared core after publishing successful attempt | Required | Forbidden | Exact output inventory and marker hash | result tree | Yes |

The v9 assisted campaign does not persist the A2 input-evidence object, the
shared-core `result.json` SHA, or the output-root identity carried inside the
internal capability. Consequently the ordinary result tree can be internally
validated but cannot be independently joined back to the campaign with all
required A2 disk/parser and output bindings.

The guardian and supervisor also instantiate separate process-local
`CampaignEvidenceStore` registries. The supervisor does not read/adopt the
guardian-owned permit-consumption or guardian-launch receipt. Its final
manifest therefore cannot bind those files. If they exist before
`assert_no_extra_files()`, they are extras; if the guardian writes after the
supervisor's final check, they appear after the final manifest and are still
unbound.

## Direct v003 reachability

The paired generation defines `attempt-phase9b-lbnp-direct-v003`, and
`phase9b_execution.py` contains a direct v003 execution adapter. The production
authority chain does not reach it:

- the external v3 direct entry aliases the retained `phase9b_guardian`;
- `phase9b_launch.py` still builds plans from the v001 request and attempt
  registry;
- `phase9b_guardian.py`, `phase9b_supervisor.py` and `phase9b_permit.py` still
  require the v001 direct attempt;
- `worker.py` has no worker authority profile for the v003 direct attempt.

Therefore no real accepted direct-v003 authority/evidence tree has a production
writer in frozen v9. Synthetic invocation of the adapter does not replace the
missing guardian, permit, registration, compute-claim and process evidence.

## Terminal-specific conclusions

- An accepted production assisted terminal is unreachable because both
  production stage entrypoints omit the capability-consumption receipt that the
  supervisor requires after a successful child exit.
- Several partial branches raise before `_write_campaign_terminal`, so they have
  no route terminal or final manifest. They can be observed only as incomplete
  or indeterminate trees; a reader may not invent a rejection classification.
- A2 maps every shared-core nonzero exit to `rejected_cation`, so neutral, D3 and
  other shared-core failures cannot be recovered from the A2 terminal alone.
- `process_tree.json` is an accepted-only file. Rejected campaigns have no
  durable historical A1/A2 windows.
- The direct v003 accepted, rejected and partial terminal sets are not derivable
  because the v003 production authority/writer chain is absent.

These conclusions make an accepted direct-and-assisted Postflight impossible
without changing the runner writers. Such changes are outside Item 11.
