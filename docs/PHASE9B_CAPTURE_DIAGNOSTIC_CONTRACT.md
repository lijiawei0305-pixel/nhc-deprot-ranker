# Phase 9B-U4 Capture Diagnostic Contract

`ProtectedObjectCaptureDiagnosticV1` is observation evidence outside the
stable projection. It always records object/state, launcher classification,
logical relative launcher, symlink depth, root-containment result, individual
command evidence, exception class/message digest, and details digest.

Each command evidence row binds the exact argv digest, executable identity,
return code, stdout/stderr SHA256 and byte counts, and timeout state.

For `state=present`, `failure=null`. Every non-present capture has a non-empty,
registered code, stage, and assertion. Frozen codes include:

```text
ROOT_ABSENT
ROOT_UNREADABLE
ROOT_NOT_DIRECTORY
ROOT_SYMLINK_FORBIDDEN
PYTHON_LAUNCHER_MISSING
PYTHON_SYMLINK_DANGLING
PYTHON_SYMLINK_LOOP
PYTHON_SYMLINK_ESCAPES_ENV
PYTHON_TARGET_NOT_REGULAR
PYTHON_TARGET_NOT_EXECUTABLE
PYTHON_IDENTITY_DRIFT
CONDA_HISTORY_MISSING
CONDA_HISTORY_INVALID
PYTHON_PROBE_FAILED
CONDA_EXPLICIT_FAILED
PIP_FREEZE_FAILED
TREE_CAPTURE_FAILED
DISTRIBUTION_CAPTURE_FAILED
SNAPSHOT_SCHEMA_FAILED
UNEXPECTED_CAPTURE_EXCEPTION
PROTECTED_SNAPSHOT_EVIDENCE_INCOMPLETE
```

Exceptions are caught at their stage. Expected failures retain their specific
code. An unregistered exception becomes `UNEXPECTED_CAPTURE_EXCEPTION`; it is
never represented as an unexplained ordinary invalid sentinel.
