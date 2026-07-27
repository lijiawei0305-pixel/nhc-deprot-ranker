# Phase 9B Split-Process Implementation Plan

> Completion note (2026-07-27): all Item 10 implementation units below are
> complete, the Linux fake-process gate ran three fresh campaigns, and the one
> permitted v9 rebaseline is final. No Postflight source was added. The next and
> only allowed work is Item 11/12 split-process-aware Postflight.

## Item 10/12 scope

Item 10/12 is a separate, local/mock-only authorization. It may implement source
and tests but may not SSH, load a real model, use a GPU, run PySCF, deploy, place
or consume a permit, launch a real process chain, open a public gate, implement
Postflight, or run the full-chain rehearsal.

One implementation unit, in order:

1. Define strict campaign, stage-capability, handoff, admission, process, evidence,
   terminal, request v3, manifest v3, resources v2, and permit v3 schemas.
2. Define source-frozen campaign and exact interpreter profiles; request fields
   can reference but cannot choose them.
3. Extend the audited registration/release/compute-claim chain for one-shot
   internal stage capabilities.
4. Bind an assisted campaign guardian to the one user permit and composite
   source identity.
5. Implement the standard-library campaign supervisor, runtime-derived absolute
   deadline, process-owned state receipts, process groups, reaping and terminal logic.
6. Refactor the existing AIMNet2 runtime behind an A1-only entrypoint while
   preserving one model load and both endpoint algorithms.
7. Implement exclusive durable XYZ, one immutable A1 proposal, one immutable
   supervisor verification, exact file-set checks, and no receipt mutation.
8. Implement `StageA2AdmissionReceiptV1` and an A2-only entrypoint that re-reads
   disk bytes before PySCF import.
9. Extract one typed PySCF core used by direct and A2; preserve protocol and
   standard-to-SOSCF semantics exactly.
10. Update bundle, resources, preflight, deploy, permit placement, and launch
    adapters for the composite campaign while exposing no public stage launch.
11. Implement the fixed evidence tree and partial-terminal writers.
12. Complete unit, integration, property, failure-injection, and mutation tests
    with every execution gate false.
13. Freeze file lists and compute v9 and subclosure identities once.
14. Mark v8 `superseded_before_execution` without editing its retained records.
15. Generate one new paired request/manifest generation; permit rendering remains
    a later authorized transaction.

No v9 identity is generated until step 12 is fully green. Steps 13–15 happen
once, never iteratively. Any discovered source defect before freeze is fixed and
retested without creating an identity; a defect after freeze requires stopping
and explicit reauthorization rather than silently making v10.

## Component change summary

Preflight gains two exact interpreter and GPU/A2 resource checks. Deployment
gains the composite inventory and remains all-source-before-run. Permit staging
gains the assisted campaign permit, not stage permits. Guardian gains campaign
binding but not computation. Launch can invoke only the campaign guardian.
Postflight is explicitly deferred to Item 11/12.

## Frozen Item 11/12 Postflight interface

The future Postflight must verify the campaign permit and consumption, guardian,
campaign supervisor, A1 identity/process/descendants/terminal, both endpoint
preoptimization receipts, immutable A1 proposal, supervisor verification, A2 admission, A2
identity/process/descendants/terminal, A1/A2 non-overlap, absence of residual
processes, both exact interpreter identities, every source subclosure and the
composite, exact evidence tree, final PySCF/D3 evidence, label formula, and full
end-to-end wall/CPU/GPU accounting.

It must represent rather than reject structurally valid intermediate terminals:
A1 accepted with A2 not started; A1 accepted with handoff rejected; A1 accepted
with A2 spawn failed or indeterminate; and A2 cation accepted with neutral
rejected. One worker or A2 receipt can never stand for the campaign. This is an
interface freeze only; no Postflight source is implemented in Item 9/12.
