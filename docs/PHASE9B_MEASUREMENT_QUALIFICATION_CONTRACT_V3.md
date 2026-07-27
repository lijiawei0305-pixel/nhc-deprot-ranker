# Phase 9B-U5 Measurement Qualification Contract V3

After the document-first PR merges, Phase 9B-U5-Q permits exactly one
controlled read-only SSH. It runs the exact merged U5 helper in one process and
captures A then B for exactly these six objects:

```text
project_mlff
project_aimnet2
project_gpupyscf
shared_molecular
phase9b_unified_v001_env
phase9b_unified_v002_env
```

Q5 invokes no package-manager CLI, imports no computational package, uses no
GPU, downloads nothing, and creates no v005 prefix, wheelhouse, cache, or
receipt directory. Between A and B there is no server write. The sole child
process is each environment's already authenticated resolved Python with
`-I -B -c` and a standard-library probe.

Every object must prove:

```text
A.state == B.state == present
A.failure == B.failure == null
launcher and resolved executable stable and root-contained
Python version/implementation stable
history SHA256 equal
raw and normalized Conda inventories equal
record count and filename set equal
all-distribution inventory equal
tree structure/content/mtime identity equal
schema and projection keysets equal
canonical projection bytes and SHA256 equal
```

The public qualification receipt contains relative launcher chain/target,
Python identity, Conda record count and inventory hashes, distribution count and
hash, tree digests, projection SHA256, per-field comparisons, and complete
failure or `null`. It contains no private absolute path, host/account,
credential, raw process map, or private device/inode value.

Any failed object terminates U5 as `failed_before_environment_creation`. The
failed object, stage, code, assertion, partial evidence, and whether evidence
indicates content drift or a capture defect must be reported. There is no
helper edit, retry, object omission, relaxed present gate, v005 resource, or
automatic U6. If the failure is a helper design defect, future work must stop
creating unified attempts and move to a separately authorized dual-environment
/ split-process assisted route.
