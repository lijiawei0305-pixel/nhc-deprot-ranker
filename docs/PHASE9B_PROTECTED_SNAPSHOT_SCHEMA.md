# Phase 9B Protected Snapshot Schema

## Purpose

Phase 9B-U3 qualifies the measurement system before it creates any environment
resource. U1 failed its calculator-call metrology contract. U2 matched that
corrected call contract but failed a different metrology contract: its before
snapshot omitted `state` and its after snapshot added `state=present`. Neither
failure was a dependency, native-library, or AIMNet2 incompatibility.

U1 and U2 are immutable retained outcomes. This schema applies only to the new
U3 attempt and cannot validate or repair either predecessor.

## `ProtectedObjectSnapshotV2`

Every capture has exactly these top-level fields:

```json
{
  "schema_version": "nhc-phase9b-protected-object-snapshot-v2",
  "object_id": "project_mlff",
  "state": "present",
  "object_kind": "conda_environment",
  "python_identity": {},
  "conda_history_sha256": "...",
  "conda_explicit_sha256": "...",
  "pip_freeze_sha256": "...",
  "critical_distribution_identities": [],
  "filesystem_entry_count": 0,
  "regular_file_count": 0,
  "regular_file_bytes": 0,
  "tree_digest": "...",
  "mtime_summary_digest": "..."
}
```

`state` is mandatory and is exactly one of `present`, `absent`, `unreadable`,
or `invalid`. All six U3 protected objects must be `present`.

`python_identity` always has exactly `executable_sha256`, `executable_bytes`,
`version`, and `implementation`. Each critical distribution identity always has
exactly `distribution`, `state`, `version`, `metadata_sha256`, and
`record_sha256`. Missing values use an explicit state and string sentinel; null
is forbidden everywhere.

Unknown keys, missing keys, conditional keys, phase-dependent keys, or nested
key drift are schema failures. JSON member order is not identity.

## Stable identity projection

`ProtectedObjectIdentityProjectionV1` contains only the stable identity fields
from the validated snapshot. It excludes phase, timestamp, attempt, observer,
host, path, PID, warning order, transport metadata, receipt name, and receipt
digest. Its schema version is
`nhc-phase9b-protected-object-identity-projection-v1`.

Canonical bytes are UTF-8 JSON with sorted keys, compact separators, and one
terminal newline. Only those bytes are hashed for protected equality.

## Observation receipt

`ProtectedObjectObservationReceiptV1` wraps, but never enriches, the stable
snapshot and projection. It may add observation phase, timestamp, attempt ID,
observer PID, and warnings. Before and after observation receipts may differ.
The equality gate compares only their validated projection bytes and SHA256.

The receipt writer may add a receipt digest outside the projection. It may not
add, remove, or overwrite any snapshot or projection field.

## Comparison order and failure codes

Structure is checked before content. Every object reports:

```text
schema_keyset_equal
projection_keyset_equal
projection_bytes_equal
projection_sha256_equal
```

Failure codes are:

```text
PROTECTED_SNAPSHOT_SCHEMA_ASYMMETRY
PROTECTED_SNAPSHOT_CONTENT_DRIFT
PROTECTED_SNAPSHOT_CAPTURE_FAILURE
PROTECTED_SNAPSHOT_EVIDENCE_INCOMPLETE
```

Comparing a full observation receipt, a receipt SHA, or an enriched payload in
place of a stable projection is a contract error, never equality evidence.

## One production capture path

Both qualification captures, protected before, and protected after call only:

```text
capture_protected_object_snapshot()
→ validate schema
→ build stable projection
→ canonical serialize
→ SHA256
→ wrap observation receipt
```

There is no before helper, after helper, Stage 0 helper, Stage 4 helper, or
finally-side enrichment path.
