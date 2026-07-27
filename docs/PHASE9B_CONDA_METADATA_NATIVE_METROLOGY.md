# Phase 9B-U5 Conda-Metadata-Native Protected Metrology

## Authority decision

A protected environment's equality gate no longer depends on an external
package-manager process. Installed Conda records are persistent files under
`<ENV>/conda-meta/*.json`; transaction history is `<ENV>/conda-meta/history`.
Installed Python distributions are persistent `*.dist-info` directories.
Together with the authenticated Python launcher and frozen tree identity, these
are the environment's own on-disk facts.

An external CLI would additionally bind its executable and base environment,
plugins, user configuration, HOME, channels, CLI version, argument parsing,
offline behavior, and package cache. Those are observations about an external
tooling context, not intrinsic contents of the protected prefix. Explicit
exports are useful for reconstruction, but are not the only proof that the
same prefix did not drift.

`phase9b_u5_metrology.py` therefore does not call or import a package manager,
activate an environment, read user configuration, consult a registry, or use a
channel/cache. Its only child process is the already authenticated resolved
environment Python, called as an absolute executable with `-I -B -c` for a
standard-library-only version probe.

## Two comparisons that must not be confused

Same-object immutability compares raw record bytes and filenames, raw history,
all distribution metadata, launcher identity, and tree identity. A single-byte
or filename change is drift.

Cross-environment semantic package comparison uses normalized records that
retain package name, version, build, build number, artifact identities,
dependencies, and portable optional fields while excluding prefix-local and
cache-local values. Raw `conda-meta` records are not claimed to be byte-identical
across two independently cloned prefixes.

## Partial evidence and diagnostics

Capture proceeds through root, launcher, isolated Python probe, Conda metadata,
distribution metadata, tree identity, and final launcher recheck. Every
completed payload remains in `ProtectedObjectSnapshotV4` if a later stage
fails. A Python probe failure is also non-destructive to disk metrology: its
return/stdout/stderr evidence is retained and the metadata/tree stages are
still captured before the failed snapshot is returned.

Every non-present snapshot carries `ProtectedObjectCaptureDiagnosticV2` with a
registered code, exact stage and assertion, object ID, exception class/message
digest, and details digest. Unknown exceptions are explicitly
`UNEXPECTED_CAPTURE_EXCEPTION`. If the portable structure cannot express real
partial evidence, the only allowed classification is
`PROTECTED_SNAPSHOT_EVIDENCE_INCOMPLETE`; no reason-free sentinel is a normal
result.
