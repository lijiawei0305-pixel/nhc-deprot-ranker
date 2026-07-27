# Phase 9B Split-Process Evidence Tree

## Frozen layout

```text
<assisted_root>/
  input/
    cation.initial.xyz
    neutral.initial.xyz
    request.json
    payload_manifest.json
  private/
    permit.ready.json
    permit.consumed.json
  runtime/
    campaign/
      guardian_launch.json
      campaign_identity.json
      campaign_ack.json
      campaign_schedule.json
      campaign_terminal.json
      logs/
    stage_a1/
      identity.json
      capability_digest.json
      process_registration.json
      acknowledgement.json
      logs/
      cache/
      cation/
        input.xyz
        output.xyz
        trajectory.jsonl
        preoptimization_receipt.json
        handoff_receipt.json
      neutral/
        input.xyz
        output.xyz
        trajectory.jsonl
        preoptimization_receipt.json
        handoff_receipt.json
      terminal.json
    handoff/
      verification.json
      a2_admission.json
    stage_a2/
      identity.json
      capability_digest.json
      process_registration.json
      acknowledgement.json
      logs/
      cation/
        input.xyz
        optimization/
          optimized.xyz
          optimization_receipt.json
        final/
          scf_receipt.json
          d3_receipt.json
        endpoint_result.json
      neutral/
        input.xyz
        optimization/
          optimized.xyz
          optimization_receipt.json
        final/
          scf_receipt.json
          d3_receipt.json
        endpoint_result.json
      terminal.json
    evidence/
      permit_consumption.json
      process_tree.json
      route_terminal.json
      evidence_manifest.json
```

## File policy

The tree above is the complete allowed structural set. Log filenames are the
fixed `guardian.stdout`, `guardian.stderr`, `supervisor.stdout`,
`supervisor.stderr`, `stage.stdout`, and `stage.stderr` appropriate to their
named directory. A1 cache is the only variable-content subtree; every cache file
must be a regular file below its root and appears in the cache inventory. The
frozen policy is:

| Class | Mode | Maximum | Owner / link policy |
| --- | --- | --- | --- |
| directories | `0700` | exact registered tree | campaign UID/GID; never symlink |
| ready/consumed permit | `0400` | 64 KiB | campaign UID/GID; regular, link count 1 |
| canonical JSON receipt/request/manifest | `0400` | 64 KiB each | campaign UID/GID; regular, link count 1 |
| XYZ | `0400` after commit | 1 MiB each | campaign UID/GID; regular, link count 1 |
| trajectory JSONL | `0400` after commit | 8 MiB each | campaign UID/GID; regular, link count 1 |
| stdout/stderr log | `0600` | 64 KiB captured each | campaign UID/GID; regular, acceptance-ineligible |
| A1 cache files | `0600` | 1 GiB aggregate | campaign UID/GID; contained below registered cache root |

All names not shown above or frozen for logs are forbidden. Directories are
private, non-symlink roots. Receipts and inputs use exclusive create, no-follow
opens, bounded writes, file and parent-directory fsync,
re-read, SHA256, and evidence-manifest inclusion. No file may be overwritten,
deleted, restored, or silently omitted. Large logs and trajectories have frozen
caps and digests; logs never serve as acceptance evidence.

The raw internal release token is never written. Only the capability and token
digests and registration/acknowledgement receipts are durable. A failure tree
contains all evidence that landed before the failure plus a terminal missing-set
description; it is not backfilled.

## Exact set and route separation

The supervisor validates the exact allowed set after each stage and before the
campaign terminal. An extra regular file, directory, symlink, device, FIFO, or
socket under a registered evidence subtree is failure. Attempt-local A1 cache
growth is allowed only below the registered A1 cache root and is inventoried.

The direct route has its existing direct input/runtime/evidence tree and must not
contain `stage_a1`, `handoff`, ML cache, or AIMNet2 receipt paths. The paired
Postflight validates that absence as part of direct/assisted parity.
