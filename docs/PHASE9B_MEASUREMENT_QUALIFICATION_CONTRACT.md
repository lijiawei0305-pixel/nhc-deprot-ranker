# Phase 9B-U3 Measurement Qualification Contract

## Hard pre-write gate

Measurement qualification runs after the document-first PR is merged and
before creation of the v003 prefix, wheelhouse, cache, or any other v003 file.
It is read-only. Failure status is `failed_before_environment_creation` and no
v003 resource may then be created.

The six protected objects are:

```text
<PROJECT_MLFF_ENV>
<PROJECT_AIMNET2_ENV>
<PROJECT_GPUPYSCF_ENV>
<SHARED_MOLECULAR_ENV>
<PHASE9B_UNIFIED_V001_ENV>
<PHASE9B_UNIFIED_V002_ENV>
```

Each is captured twice, A then B, in one process using the same production
helper, serializer, projection builder, and command runner. No server write,
third-party computation import, bytecode, cache write, or mtime mutation is
allowed between captures.

Every object must prove:

```text
A.state == B.state == present
A and B snapshot schema keys exact
A and B projection keys exact
A.projection_bytes == B.projection_bytes
A.projection_sha256 == B.projection_sha256
```

The in-memory qualification result contains both observation receipts and a
per-object comparison. Only after all six pass may the v003 cache be created
and `measurement_qualification_receipt.json` written exclusively, fsynced, and
re-read. A qualification failure is returned through the existing read-only
control channel; it is not written into a newly created v003 path.

## Qualified helper reuse

The exact helper source SHA256 from qualification is bound into the attempt
header. Protected before and after observations must use those same source
bytes. Any helper, serializer, projection schema, or object-set change after
qualification is `PROTECTED_SNAPSHOT_EVIDENCE_INCOMPLETE` and stops U3.

## Terminal failure contract

Every non-success terminal receipt contains a structured failure with non-empty
`code`, `stage`, `assertion`, `object_ids`, and `details_digest`. A successful
terminal receipt has `failure=null`. A parent-finally failure cannot be encoded
only as an overall false Boolean.
