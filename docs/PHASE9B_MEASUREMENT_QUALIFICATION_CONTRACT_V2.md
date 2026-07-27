# Phase 9B-U4 Measurement Qualification Contract V2

After the document-first PR merges, Phase 9B-U4-Q permits exactly one
controlled, read-only SSH qualification. It runs the exact merged U4 helper in
one process, imports no computational package, uses no GPU, downloads nothing,
and creates no v004 prefix, wheelhouse, cache, or receipt directory.

The six frozen objects are project MLFF, project AIMNet2, project GPU-PySCF,
shared molecular, unified v001, and unified v002. Each is captured A then B by
the same function/serializer/projection builder.

Every pair must prove:

```text
A.state == B.state == present
A.failure == B.failure == null
snapshot and projection keysets equal
projection bytes and SHA256 equal
resolved target inside exact environment root
launcher identity equal
resolved executable identity equal
```

The public qualification receipt includes only object IDs, launcher kind,
environment-relative chain/target paths, symlink depth, containment, capture
states, diagnostic status/codes, projection hashes, and equality decisions.
Absolute paths, host/account, raw device/inode, and credentials remain private.

Any failed object terminates U4 as `failed_before_environment_creation` with
its exact diagnostic. No helper edit, retry, object omission, v004 resource, U5,
or later gate is then allowed.
