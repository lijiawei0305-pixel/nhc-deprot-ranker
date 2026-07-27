# Phase 9B-U5 Conda Prefix Inventory Schema

`CondaPrefixInventoryV1` reads only a non-symlink `<ENV>/conda-meta` directory,
its stable regular `history`, and a sorted, non-recursive set of stable regular
`*.json` package records. The record count must be positive. Every file is read
once between identity checks.

`history` records raw SHA256, bytes, mtime, and line count. Semantic parsing is
not required to preserve its raw identity.

Package JSON uses strict UTF-8, rejects duplicate keys and non-finite numbers,
and requires an object. Required identity fields are non-empty string `name`,
`version`, `build`, and integer `build_number`. The reviewed optional fields
are `channel`, `subdir`, `fn`, `url`, `md5`, `sha256`, `depends`, `constrains`,
`noarch`, `package_type`, `requested_spec`, and `requested_specs`.

Each record retains filename, raw bytes/count SHA256, a canonical package name,
the required fields, sanitized portable channel/URL, sorted dependency and
constraint/spec collections, artifact hashes, package/noarch semantics, and
source-record raw SHA256. Prefix/cache-local fields are represented by a sorted
name list plus a digest of their values; their private absolute values do not
enter the portable projection. Unknown fields are not silently discarded:
their sorted names and set digest are retained, while the raw record SHA binds
their values pending review.

The inventory publishes:

```text
history_sha256
record_count
raw_record_set_sha256
normalized_record_set_sha256
record_filename_set_sha256
unknown_field_name_set_sha256
```

Same-object before/after requires equality of history, count, filename set,
raw record set, and normalized record set. Normalized records are the separate
portable layer for cross-environment package semantics; raw equality is not
asserted between independently created prefixes.

Registered failures distinguish missing/invalid/unreadable metadata directory,
history, record set, record bytes/JSON, required fields, and field types.
