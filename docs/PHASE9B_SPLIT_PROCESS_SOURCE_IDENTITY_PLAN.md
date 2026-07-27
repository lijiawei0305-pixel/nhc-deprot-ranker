# Phase 9B Split-Process Source Identity Plan

## Selected strategy

The project selects option B: independently verifiable subclosure identities
plus one composite campaign identity. A single flat source hash was rejected
because it obscures which exact bytes execute under each interpreter and makes
Postflight unable to prove partial replacement at a stage boundary.

The future v9 generation contains:

```text
campaign_control_source
stage_a1_source
stage_a2_source
shared_pyscf_core_source
shared_schema_source
full_assisted_campaign_source
```

Each subclosure has a canonical ordered file list and per-file SHA256. The full
composite hashes the schema versions, ordered subclosure names, subclosure
digests, exact interpreter identity assigned to each executable closure, and
deployment inventory. A permit binds all subclosure hashes and the composite,
so replacing a single source file or mixing otherwise valid generations fails
both the affected subclosure and composite check.

This provides independent stage verification, avoids source/interpreter cycles,
keeps request and permit fields readable, lets deployment promote one complete
inventory atomically, preserves direct/A2 shared-core parity, and lets
Postflight attribute a source mismatch precisely.

## Schema migration

Both direct and assisted requests migrate from v2 to v3 so one paired manifest
generation has explicit topology and interpreter-profile bindings. Direct uses
`single_stage_pyscf`; assisted uses `split_process_campaign`. Requests may name
only frozen profile IDs and hashes; they cannot supply paths or select an
interpreter.

The migration set is:

```text
request                         v2 -> v3, both routes
payload manifest                v2 -> v3, one paired generation
direct permit                   v2 -> v3, route authority
assisted permit                 v2 -> AssistedCampaignPermitV3
handoff                         existing -> cross-process v1
resources                       current -> campaign-aware v2
launch                          current -> campaign-aware v3
terminal                        current -> campaign-aware v1
```

The future source schema name is `nhc-two-endpoint-runner-source-v9`, represented
by the composite identity above. This document deliberately records no v9 hash.

## Freeze ordering

Item 10/12 implements every source and schema, completes all local/mock tests and
mutations, freezes closure membership, and only then computes one v9 rebaseline.
No provisional v9 request, manifest, resource, permit, or source hash is created.
After the single rebaseline, v8 is marked `superseded_before_execution`, never
overwritten. The new direct/assisted requests and manifests are generated as one
paired generation, and private permits only later under separate authority.

Deploy must deliver campaign control, A1, A2, shared schemas/core, initial
geometry, requests, manifests, and resources as one verified inventory before
anything can run. External launch exposes only direct guardian and assisted
campaign guardian; no A1/A2 launcher is public.

## Current identity

Throughout Item 9/12, runner schema v8 and SHA256
`5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2`
remain current, prepared but unauthorized and blocked. No current request,
manifest, resource, or permit identity is regenerated.
