# Phase 9B Protected Snapshot Schema V3

## Version boundary

`ProtectedObjectSnapshotV3` and `ProtectedObjectIdentityProjectionV2` belong
only to Phase 9B-U4. They do not modify V2, repair U3, or change any retained
U1–U3 result.

U3 classified `<ENV>/bin/python` as invalid whenever the logical launcher was
a symlink. That branch ran before the Python probe, `conda list --explicit`,
`pip freeze --all`, distribution scan, and tree capture. U3 also combined all
three nonzero command results and later `KeyError`, `OSError`, `ValueError`, and
schema failures into the same `state=invalid` sentinel. Its public receipt did
not preserve a capture reason. U3 remains valid as
`failed_before_environment_creation`, but its public sentinel alone cannot
prove which internal branch fired.

The retained U3 source control flow is exactly:

```python
python = target.root / "bin/python"

if python.is_symlink() or not python.is_file():
    return invalid

if any(result.returncode != 0 for result in (version, explicit, freeze)):
    return invalid

except (KeyError, OSError, ValueError, SnapshotSchemaError):
    return invalid
```

The first branch precedes every command and capture operation. These lines are
quoted as retained root-cause evidence; V3 does not edit them or use them to
reclassify U3.

## Snapshot V3

Every V3 snapshot always contains object identity/state, Python launcher
identity, three separately named command evidence rows when executed, conda
history/specification, pip freeze, critical distribution identities, file and
byte counts, tree digest, and mtime digest. Unknown, missing, conditional, or
null fields are forbidden.

`python_identity` records:

```text
logical_launcher_relative_path
launcher_kind
launcher_lstat_digest
symlink_chain_relative_targets
symlink_chain_digest
resolved_executable_relative_path
resolved_executable_sha256
resolved_executable_bytes
resolved_executable_mode
resolved_device
resolved_inode
version
implementation
```

Private evidence keeps full device/inode identity. Public evidence omits those
numbers and uses environment-relative paths only.

## Symlink-aware launcher policy

`resolve_environment_python_launcher()` accepts a regular executable launcher
or a bounded symlink chain whose final regular executable remains inside the
exact environment root. The algorithm performs logical-launcher `lstat`,
bounded link traversal, lexical and canonical containment, regular/executable
checks, full node/target identity capture, exact resolved-absolute execution,
and identity recapture after every command and before final snapshot assembly.

A symlink is not itself a failure. Dangling links, loops, root escape, another
environment, system Python, non-regular targets, non-executable targets, or any
launcher/target identity drift fail closed.

## Stable projection V2

The projection includes launcher kind, launcher lstat digest, symlink-chain
relative targets and digest, resolved relative target, executable hash/bytes/
mode, version and implementation, plus stable environment/package/tree and
command evidence. Raw device/inode, private absolute paths, diagnostic,
timestamp, phase, PID, and attempt metadata are excluded.

Only canonical projection bytes and SHA256 are equality identity. An
observation receipt may never be compared directly as stable identity.
