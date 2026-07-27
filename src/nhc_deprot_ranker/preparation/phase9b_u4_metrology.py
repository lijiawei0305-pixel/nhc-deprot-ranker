"""Symlink-aware protected-object metrology for Phase 9B-U4.

This standard-library-only module is outside the frozen runner closure.  It
does not mutate an environment.  Qualification, protected-before, and
protected-after must all use :func:`capture_protected_object_snapshot` from
these exact source bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

SNAPSHOT_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-snapshot-v3"
PROJECTION_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-identity-projection-v2"
DIAGNOSTIC_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-capture-diagnostic-v1"
OBSERVATION_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-observation-receipt-v2"
COMPARISON_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-comparison-v2"
QUALIFICATION_SCHEMA_VERSION: Final = "nhc-phase9b-u4-measurement-qualification-receipt-v2"

NO_FAILURE: Final = "none"
ROOT_ABSENT: Final = "ROOT_ABSENT"
ROOT_UNREADABLE: Final = "ROOT_UNREADABLE"
ROOT_NOT_DIRECTORY: Final = "ROOT_NOT_DIRECTORY"
ROOT_SYMLINK_FORBIDDEN: Final = "ROOT_SYMLINK_FORBIDDEN"
PYTHON_LAUNCHER_MISSING: Final = "PYTHON_LAUNCHER_MISSING"
PYTHON_SYMLINK_DANGLING: Final = "PYTHON_SYMLINK_DANGLING"
PYTHON_SYMLINK_LOOP: Final = "PYTHON_SYMLINK_LOOP"
PYTHON_SYMLINK_ESCAPES_ENV: Final = "PYTHON_SYMLINK_ESCAPES_ENV"
PYTHON_TARGET_NOT_REGULAR: Final = "PYTHON_TARGET_NOT_REGULAR"
PYTHON_TARGET_NOT_EXECUTABLE: Final = "PYTHON_TARGET_NOT_EXECUTABLE"
PYTHON_IDENTITY_DRIFT: Final = "PYTHON_IDENTITY_DRIFT"
CONDA_HISTORY_MISSING: Final = "CONDA_HISTORY_MISSING"
CONDA_HISTORY_INVALID: Final = "CONDA_HISTORY_INVALID"
PYTHON_PROBE_FAILED: Final = "PYTHON_PROBE_FAILED"
CONDA_EXPLICIT_FAILED: Final = "CONDA_EXPLICIT_FAILED"
PIP_FREEZE_FAILED: Final = "PIP_FREEZE_FAILED"
TREE_CAPTURE_FAILED: Final = "TREE_CAPTURE_FAILED"
DISTRIBUTION_CAPTURE_FAILED: Final = "DISTRIBUTION_CAPTURE_FAILED"
SNAPSHOT_SCHEMA_FAILED: Final = "SNAPSHOT_SCHEMA_FAILED"
UNEXPECTED_CAPTURE_EXCEPTION: Final = "UNEXPECTED_CAPTURE_EXCEPTION"
EVIDENCE_INCOMPLETE: Final = "PROTECTED_SNAPSHOT_EVIDENCE_INCOMPLETE"

FAILURE_CODES: Final = frozenset(
    {
        ROOT_ABSENT,
        ROOT_UNREADABLE,
        ROOT_NOT_DIRECTORY,
        ROOT_SYMLINK_FORBIDDEN,
        PYTHON_LAUNCHER_MISSING,
        PYTHON_SYMLINK_DANGLING,
        PYTHON_SYMLINK_LOOP,
        PYTHON_SYMLINK_ESCAPES_ENV,
        PYTHON_TARGET_NOT_REGULAR,
        PYTHON_TARGET_NOT_EXECUTABLE,
        PYTHON_IDENTITY_DRIFT,
        CONDA_HISTORY_MISSING,
        CONDA_HISTORY_INVALID,
        PYTHON_PROBE_FAILED,
        CONDA_EXPLICIT_FAILED,
        PIP_FREEZE_FAILED,
        TREE_CAPTURE_FAILED,
        DISTRIBUTION_CAPTURE_FAILED,
        SNAPSHOT_SCHEMA_FAILED,
        UNEXPECTED_CAPTURE_EXCEPTION,
        EVIDENCE_INCOMPLETE,
    }
)
SNAPSHOT_STATES: Final = frozenset({"present", "absent", "unreadable", "invalid"})
OBSERVATION_PHASES: Final = frozenset(
    {"qualification_a", "qualification_b", "protected_before", "protected_after"}
)
U4_PROTECTED_OBJECT_IDS: Final = frozenset(
    {
        "project_mlff",
        "project_aimnet2",
        "project_gpupyscf",
        "shared_molecular",
        "phase9b_unified_v001_env",
        "phase9b_unified_v002_env",
    }
)
CRITICAL_DISTRIBUTIONS: Final = (
    "aimnet",
    "ase",
    "geometric",
    "h5py",
    "networkx",
    "numpy",
    "nvalchemi-toolkit",
    "nvalchemi-toolkit-ops",
    "pip",
    "pyscf",
    "pyscf-dispersion",
    "scipy",
    "setuptools",
    "six",
    "torch",
)
MAX_SYMLINK_DEPTH: Final = 16
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_EMPTY_SHA256: Final = hashlib.sha256(b"").hexdigest()


class U4MetrologyError(RuntimeError):
    """The U4 metrology contract could not be proved."""


class SnapshotSchemaError(U4MetrologyError):
    """A strongly typed U4 payload violated its exact schema."""


class LauncherResolutionError(U4MetrologyError):
    """The logical environment Python launcher could not be authenticated."""

    def __init__(
        self,
        code: str,
        assertion: str,
        *,
        launcher_kind: str,
        symlink_depth: int,
        inside_root: bool,
        exception: BaseException | None = None,
    ) -> None:
        super().__init__(assertion)
        self.code = code
        self.assertion = assertion
        self.launcher_kind = launcher_kind
        self.symlink_depth = symlink_depth
        self.inside_root = inside_root
        self.exception = exception


def canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: str, label: str) -> None:
    if not _SHA256_RE.fullmatch(value):
        raise SnapshotSchemaError(f"{label} must be a lowercase SHA256")


def _relative_inside(root: Path, candidate: Path) -> str:
    root_text = os.path.normpath(str(root))
    candidate_text = os.path.normpath(str(candidate))
    try:
        common = os.path.commonpath((root_text, candidate_text))
    except ValueError as exc:
        raise LauncherResolutionError(
            PYTHON_SYMLINK_ESCAPES_ENV,
            "resolved launcher target remains inside exact environment root",
            launcher_kind="symlink",
            symlink_depth=0,
            inside_root=False,
            exception=exc,
        ) from exc
    if common != root_text:
        raise LauncherResolutionError(
            PYTHON_SYMLINK_ESCAPES_ENV,
            "resolved launcher target remains inside exact environment root",
            launcher_kind="symlink",
            symlink_depth=0,
            inside_root=False,
        )
    return Path(candidate_text).relative_to(Path(root_text)).as_posix()


@dataclass(frozen=True, slots=True)
class CaptureTarget:
    object_id: str
    root: Path
    conda_executable: Path

    def __post_init__(self) -> None:
        if not self.object_id:
            raise ValueError("object_id is empty")
        if not self.root.is_absolute() or not self.conda_executable.is_absolute():
            raise ValueError("capture paths must be absolute")


@dataclass(frozen=True, slots=True)
class FileNodeIdentity:
    relative_path: str
    kind: str
    mode: int
    size: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int
    link_target: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "kind": self.kind,
            "mode": self.mode,
            "size": self.size,
            "device": self.device,
            "inode": self.inode,
            "mtime_ns": self.mtime_ns,
            "ctime_ns": self.ctime_ns,
            "link_target": self.link_target,
        }

    def digest(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_mapping()))


def _node_identity(root: Path, path: Path) -> FileNodeIdentity:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        kind = "symlink"
        target = os.readlink(path)
    elif stat.S_ISREG(info.st_mode):
        kind = "regular"
        target = ""
    elif stat.S_ISDIR(info.st_mode):
        kind = "directory"
        target = ""
    else:
        kind = "other"
        target = ""
    return FileNodeIdentity(
        relative_path=_relative_inside(root, path),
        kind=kind,
        mode=info.st_mode,
        size=info.st_size,
        device=info.st_dev,
        inode=info.st_ino,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
        link_target=target,
    )


@dataclass(frozen=True, slots=True)
class LauncherResolution:
    logical_launcher: Path
    launcher_kind: str
    nodes: tuple[FileNodeIdentity, ...]
    symlink_chain_relative_targets: tuple[str, ...]
    resolved_executable: Path
    resolved_executable_relative_path: str
    resolved_executable_sha256: str
    resolved_executable_bytes: int
    resolved_executable_mode: int
    resolved_device: int
    resolved_inode: int
    resolved_target_inside_root: bool

    @property
    def symlink_depth(self) -> int:
        return len(self.symlink_chain_relative_targets)

    @property
    def launcher_lstat_digest(self) -> str:
        return self.nodes[0].digest()

    @property
    def symlink_chain_digest(self) -> str:
        return sha256_bytes(
            canonical_json_bytes({"relative_targets": list(self.symlink_chain_relative_targets)})
        )

    @property
    def identity_digest(self) -> str:
        return sha256_bytes(
            canonical_json_bytes(
                {
                    "nodes": [row.to_mapping() for row in self.nodes],
                    "resolved_relative_path": self.resolved_executable_relative_path,
                    "resolved_sha256": self.resolved_executable_sha256,
                    "resolved_bytes": self.resolved_executable_bytes,
                    "resolved_mode": self.resolved_executable_mode,
                    "resolved_device": self.resolved_device,
                    "resolved_inode": self.resolved_inode,
                }
            )
        )


def resolve_environment_python_launcher(target: CaptureTarget) -> LauncherResolution:
    """Resolve and authenticate ``<ENV>/bin/python`` without escaping ``<ENV>``."""

    root = Path(os.path.normpath(str(target.root)))
    logical = root / "bin/python"
    current = logical
    nodes: list[FileNodeIdentity] = []
    relative_targets: list[str] = []
    visited: set[str] = set()
    launcher_kind = "missing"
    for depth in range(MAX_SYMLINK_DEPTH + 1):
        current_text = os.path.normpath(str(current))
        if current_text in visited:
            raise LauncherResolutionError(
                PYTHON_SYMLINK_LOOP,
                "Python launcher symlink chain is acyclic and bounded",
                launcher_kind="symlink",
                symlink_depth=len(relative_targets),
                inside_root=True,
            )
        visited.add(current_text)
        try:
            node = _node_identity(root, Path(current_text))
        except FileNotFoundError as exc:
            code = PYTHON_LAUNCHER_MISSING if depth == 0 else PYTHON_SYMLINK_DANGLING
            raise LauncherResolutionError(
                code,
                "Python launcher and every symlink target exist",
                launcher_kind=launcher_kind,
                symlink_depth=len(relative_targets),
                inside_root=True,
                exception=exc,
            ) from exc
        except OSError as exc:
            raise LauncherResolutionError(
                UNEXPECTED_CAPTURE_EXCEPTION,
                "Python launcher lstat and readlink complete without unexpected error",
                launcher_kind=launcher_kind,
                symlink_depth=len(relative_targets),
                inside_root=True,
                exception=exc,
            ) from exc
        nodes.append(node)
        if depth == 0:
            launcher_kind = node.kind
        if node.kind != "symlink":
            break
        if depth == MAX_SYMLINK_DEPTH:
            raise LauncherResolutionError(
                PYTHON_SYMLINK_LOOP,
                "Python launcher symlink chain is acyclic and bounded",
                launcher_kind="symlink",
                symlink_depth=len(relative_targets),
                inside_root=True,
            )
        raw_target = node.link_target
        candidate = (
            Path(raw_target)
            if os.path.isabs(raw_target)
            else Path(current_text).parent / raw_target
        )
        candidate = Path(os.path.normpath(str(candidate)))
        try:
            relative = _relative_inside(root, candidate)
        except LauncherResolutionError as exc:
            raise LauncherResolutionError(
                PYTHON_SYMLINK_ESCAPES_ENV,
                "resolved launcher target remains inside exact environment root",
                launcher_kind="symlink",
                symlink_depth=len(relative_targets) + 1,
                inside_root=False,
                exception=exc,
            ) from exc
        relative_targets.append(relative)
        current = candidate
    final = nodes[-1]
    if final.kind != "regular":
        raise LauncherResolutionError(
            PYTHON_TARGET_NOT_REGULAR,
            "resolved Python target is a regular file",
            launcher_kind=launcher_kind,
            symlink_depth=len(relative_targets),
            inside_root=True,
        )
    resolved = Path(os.path.normpath(str(current)))
    try:
        canonical = resolved.resolve(strict=True)
    except FileNotFoundError as exc:
        raise LauncherResolutionError(
            PYTHON_SYMLINK_DANGLING,
            "Python launcher and every symlink target exist",
            launcher_kind=launcher_kind,
            symlink_depth=len(relative_targets),
            inside_root=True,
            exception=exc,
        ) from exc
    except RuntimeError as exc:
        raise LauncherResolutionError(
            PYTHON_SYMLINK_LOOP,
            "Python launcher symlink chain is acyclic and bounded",
            launcher_kind=launcher_kind,
            symlink_depth=len(relative_targets),
            inside_root=True,
            exception=exc,
        ) from exc
    except OSError as exc:
        raise LauncherResolutionError(
            UNEXPECTED_CAPTURE_EXCEPTION,
            "canonical launcher resolution completes without unexpected error",
            launcher_kind=launcher_kind,
            symlink_depth=len(relative_targets),
            inside_root=True,
            exception=exc,
        ) from exc
    try:
        resolved_relative = _relative_inside(root, canonical)
    except LauncherResolutionError as exc:
        raise LauncherResolutionError(
            PYTHON_SYMLINK_ESCAPES_ENV,
            "canonical Python target remains inside exact environment root",
            launcher_kind=launcher_kind,
            symlink_depth=len(relative_targets),
            inside_root=False,
            exception=exc,
        ) from exc
    if canonical != resolved:
        raise LauncherResolutionError(
            PYTHON_SYMLINK_ESCAPES_ENV,
            "all launcher symlinks are explicitly represented in the bounded chain",
            launcher_kind=launcher_kind,
            symlink_depth=len(relative_targets),
            inside_root=True,
        )
    info = canonical.stat()
    if not stat.S_ISREG(info.st_mode):
        raise LauncherResolutionError(
            PYTHON_TARGET_NOT_REGULAR,
            "resolved Python target is a regular file",
            launcher_kind=launcher_kind,
            symlink_depth=len(relative_targets),
            inside_root=True,
        )
    if not info.st_mode & 0o111 or not os.access(canonical, os.X_OK):
        raise LauncherResolutionError(
            PYTHON_TARGET_NOT_EXECUTABLE,
            "resolved Python target is executable",
            launcher_kind=launcher_kind,
            symlink_depth=len(relative_targets),
            inside_root=True,
        )
    try:
        executable_sha256 = _sha256_file(canonical)
    except OSError as exc:
        raise LauncherResolutionError(
            UNEXPECTED_CAPTURE_EXCEPTION,
            "resolved Python executable bytes are readable",
            launcher_kind=launcher_kind,
            symlink_depth=len(relative_targets),
            inside_root=True,
            exception=exc,
        ) from exc
    return LauncherResolution(
        logical_launcher=logical,
        launcher_kind=launcher_kind,
        nodes=tuple(nodes),
        symlink_chain_relative_targets=tuple(relative_targets),
        resolved_executable=canonical,
        resolved_executable_relative_path=resolved_relative,
        resolved_executable_sha256=executable_sha256,
        resolved_executable_bytes=info.st_size,
        resolved_executable_mode=info.st_mode,
        resolved_device=info.st_dev,
        resolved_inode=info.st_ino,
        resolved_target_inside_root=True,
    )


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False


CommandRunner = Callable[[Sequence[str], Mapping[str, str]], CommandResult]


@dataclass(frozen=True, slots=True)
class CommandEvidenceV1:
    command_name: str
    argv_sha256: str
    executable_identity_sha256: str
    returncode: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    timed_out: bool

    def __post_init__(self) -> None:
        for label, value in (
            ("argv_sha256", self.argv_sha256),
            ("executable_identity_sha256", self.executable_identity_sha256),
            ("stdout_sha256", self.stdout_sha256),
            ("stderr_sha256", self.stderr_sha256),
        ):
            _require_sha256(value, label)
        if not self.command_name or self.stdout_bytes < 0 or self.stderr_bytes < 0:
            raise SnapshotSchemaError("command evidence is invalid")

    def to_mapping(self) -> dict[str, object]:
        return {
            "command_name": self.command_name,
            "argv_sha256": self.argv_sha256,
            "executable_identity_sha256": self.executable_identity_sha256,
            "returncode": self.returncode,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "timed_out": self.timed_out,
        }


@dataclass(frozen=True, slots=True)
class PythonIdentityV3:
    logical_launcher_relative_path: str
    launcher_kind: str
    launcher_lstat_digest: str
    symlink_chain_relative_targets: tuple[str, ...]
    symlink_chain_digest: str
    resolved_executable_relative_path: str
    resolved_executable_sha256: str
    resolved_executable_bytes: int
    resolved_executable_mode: int
    resolved_device: int
    resolved_inode: int
    version: str
    implementation: str

    def __post_init__(self) -> None:
        if self.launcher_kind not in {"regular", "symlink", "missing", "invalid"}:
            raise SnapshotSchemaError("launcher kind is invalid")
        if self.logical_launcher_relative_path != "bin/python":
            raise SnapshotSchemaError("logical launcher path is not bin/python")
        for label, value in (
            ("launcher_lstat_digest", self.launcher_lstat_digest),
            ("symlink_chain_digest", self.symlink_chain_digest),
            ("resolved_executable_sha256", self.resolved_executable_sha256),
        ):
            _require_sha256(value, label)
        if any(
            path.startswith("/") or ".." in Path(path).parts
            for path in self.symlink_chain_relative_targets
        ):
            raise SnapshotSchemaError("symlink chain contains non-portable target")
        if (
            self.resolved_executable_bytes < 0
            or self.resolved_executable_mode < 0
            or self.resolved_device < 0
            or self.resolved_inode < 0
            or not self.version
            or not self.implementation
        ):
            raise SnapshotSchemaError("Python identity contains invalid value")

    def to_mapping(self) -> dict[str, object]:
        return {
            "logical_launcher_relative_path": self.logical_launcher_relative_path,
            "launcher_kind": self.launcher_kind,
            "launcher_lstat_digest": self.launcher_lstat_digest,
            "symlink_chain_relative_targets": list(self.symlink_chain_relative_targets),
            "symlink_chain_digest": self.symlink_chain_digest,
            "resolved_executable_relative_path": self.resolved_executable_relative_path,
            "resolved_executable_sha256": self.resolved_executable_sha256,
            "resolved_executable_bytes": self.resolved_executable_bytes,
            "resolved_executable_mode": self.resolved_executable_mode,
            "resolved_device": self.resolved_device,
            "resolved_inode": self.resolved_inode,
            "version": self.version,
            "implementation": self.implementation,
        }

    def stable_mapping(self) -> dict[str, object]:
        payload = self.to_mapping()
        payload.pop("resolved_device")
        payload.pop("resolved_inode")
        return payload


@dataclass(frozen=True, slots=True)
class CaptureFailureV1:
    code: str
    stage: str
    assertion: str

    def __post_init__(self) -> None:
        if self.code not in FAILURE_CODES or not self.stage or not self.assertion:
            raise SnapshotSchemaError("capture failure must have registered non-empty fields")

    def to_mapping(self) -> dict[str, object]:
        return {"code": self.code, "stage": self.stage, "assertion": self.assertion}


@dataclass(frozen=True, slots=True)
class ProtectedObjectCaptureDiagnosticV1:
    object_id: str
    capture_state: str
    failure: CaptureFailureV1 | None
    launcher_classification: str
    launcher_relative_path: str
    symlink_depth: int
    resolved_target_inside_root: bool
    command_evidence: tuple[CommandEvidenceV1, ...]
    exception_class: str
    exception_message_digest: str
    diagnostic_details_digest: str
    schema_version: str = DIAGNOSTIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.capture_state not in SNAPSHOT_STATES or not self.object_id:
            raise SnapshotSchemaError("capture diagnostic identity is invalid")
        if self.launcher_relative_path != "bin/python" or self.symlink_depth < 0:
            raise SnapshotSchemaError("capture diagnostic launcher fields are invalid")
        _require_sha256(self.exception_message_digest, "exception_message_digest")
        _require_sha256(self.diagnostic_details_digest, "diagnostic_details_digest")
        names = [row.command_name for row in self.command_evidence]
        if len(names) != len(set(names)):
            raise SnapshotSchemaError("command diagnostic names must be unique")
        if self.capture_state == "present":
            if self.failure is not None:
                raise SnapshotSchemaError("present capture must have failure=null")
        elif self.failure is None:
            raise SnapshotSchemaError("non-present capture requires a specific failure")

    @property
    def diagnostic_status(self) -> str:
        return "passed" if self.failure is None else "failed"

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_id": self.object_id,
            "capture_state": self.capture_state,
            "failure": None if self.failure is None else self.failure.to_mapping(),
            "launcher_classification": self.launcher_classification,
            "launcher_relative_path": self.launcher_relative_path,
            "symlink_depth": self.symlink_depth,
            "resolved_target_inside_root": self.resolved_target_inside_root,
            "command_evidence": [row.to_mapping() for row in self.command_evidence],
            "exception_class": self.exception_class,
            "exception_message_digest": self.exception_message_digest,
            "diagnostic_details_digest": self.diagnostic_details_digest,
        }


@dataclass(frozen=True, slots=True)
class ProtectedObjectSnapshotV3:
    object_id: str
    state: str
    python_identity: PythonIdentityV3
    command_evidence: tuple[CommandEvidenceV1, ...]
    conda_history_sha256: str
    conda_explicit_sha256: str
    pip_freeze_sha256: str
    critical_distribution_identities: tuple[Mapping[str, object], ...]
    filesystem_entry_count: int
    regular_file_count: int
    regular_file_bytes: int
    tree_digest: str
    mtime_summary_digest: str
    object_kind: str = "conda_environment"
    schema_version: str = SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.object_id or self.state not in SNAPSHOT_STATES:
            raise SnapshotSchemaError("snapshot identity or state is invalid")
        if self.object_kind != "conda_environment":
            raise SnapshotSchemaError("snapshot object kind is invalid")
        for label, value in (
            ("conda_history_sha256", self.conda_history_sha256),
            ("conda_explicit_sha256", self.conda_explicit_sha256),
            ("pip_freeze_sha256", self.pip_freeze_sha256),
            ("tree_digest", self.tree_digest),
            ("mtime_summary_digest", self.mtime_summary_digest),
        ):
            _require_sha256(value, label)
        if min(self.filesystem_entry_count, self.regular_file_count, self.regular_file_bytes) < 0:
            raise SnapshotSchemaError("snapshot counts must be non-negative")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_id": self.object_id,
            "state": self.state,
            "object_kind": self.object_kind,
            "python_identity": self.python_identity.to_mapping(),
            "command_evidence": [row.to_mapping() for row in self.command_evidence],
            "conda_history_sha256": self.conda_history_sha256,
            "conda_explicit_sha256": self.conda_explicit_sha256,
            "pip_freeze_sha256": self.pip_freeze_sha256,
            "critical_distribution_identities": [
                dict(row) for row in self.critical_distribution_identities
            ],
            "filesystem_entry_count": self.filesystem_entry_count,
            "regular_file_count": self.regular_file_count,
            "regular_file_bytes": self.regular_file_bytes,
            "tree_digest": self.tree_digest,
            "mtime_summary_digest": self.mtime_summary_digest,
        }


@dataclass(frozen=True, slots=True)
class CaptureResultV1:
    snapshot: ProtectedObjectSnapshotV3
    diagnostic: ProtectedObjectCaptureDiagnosticV1

    def __post_init__(self) -> None:
        if (
            self.snapshot.object_id != self.diagnostic.object_id
            or self.snapshot.state != self.diagnostic.capture_state
        ):
            raise SnapshotSchemaError("snapshot and diagnostic disagree")


@dataclass(frozen=True, slots=True)
class ProtectedObjectIdentityProjectionV2:
    payload: Mapping[str, object]

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload)

    def sha256(self) -> str:
        return sha256_bytes(self.canonical_bytes())

    def to_mapping(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self.canonical_bytes()))


def build_stable_projection(
    snapshot: ProtectedObjectSnapshotV3,
) -> ProtectedObjectIdentityProjectionV2:
    payload = snapshot.to_mapping()
    payload.pop("schema_version")
    python_identity = snapshot.python_identity.stable_mapping()
    payload["python_identity"] = python_identity
    payload["projection_schema_version"] = PROJECTION_SCHEMA_VERSION
    return ProtectedObjectIdentityProjectionV2(payload)


@dataclass(frozen=True, slots=True)
class ProtectedObjectObservationReceiptV2:
    observation_phase: str
    observed_at_ns: int
    observer_pid: int
    attempt_id: str
    snapshot: ProtectedObjectSnapshotV3
    diagnostic: ProtectedObjectCaptureDiagnosticV1
    projection: ProtectedObjectIdentityProjectionV2
    projection_sha256: str
    schema_version: str = OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.observation_phase not in OBSERVATION_PHASES or not self.attempt_id:
            raise SnapshotSchemaError("observation metadata is invalid")
        if self.snapshot.object_id != self.diagnostic.object_id:
            raise SnapshotSchemaError("observation nested identities disagree")
        if self.projection_sha256 != self.projection.sha256():
            raise SnapshotSchemaError("observation projection digest is invalid")
        expected = build_stable_projection(self.snapshot)
        if self.projection.canonical_bytes() != expected.canonical_bytes():
            raise SnapshotSchemaError("observation projection was enriched")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "observation_phase": self.observation_phase,
            "observed_at_ns": self.observed_at_ns,
            "observer_pid": self.observer_pid,
            "attempt_id": self.attempt_id,
            "snapshot": self.snapshot.to_mapping(),
            "diagnostic": self.diagnostic.to_mapping(),
            "projection": self.projection.to_mapping(),
            "projection_sha256": self.projection_sha256,
        }


def build_observation_receipt(
    result: CaptureResultV1,
    *,
    observation_phase: str,
    attempt_id: str,
    observed_at_ns: int | None = None,
    observer_pid: int | None = None,
) -> ProtectedObjectObservationReceiptV2:
    projection = build_stable_projection(result.snapshot)
    return ProtectedObjectObservationReceiptV2(
        observation_phase=observation_phase,
        observed_at_ns=time.time_ns() if observed_at_ns is None else observed_at_ns,
        observer_pid=os.getpid() if observer_pid is None else observer_pid,
        attempt_id=attempt_id,
        snapshot=result.snapshot,
        diagnostic=result.diagnostic,
        projection=projection,
        projection_sha256=projection.sha256(),
    )


def _default_command_runner(argv: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
    try:
        process = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=300,
            env=dict(environment),
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=exc.stdout or b"",
            stderr=exc.stderr or b"",
            timed_out=True,
        )
    return CommandResult(process.returncode, process.stdout, process.stderr)


def _external_executable_identity(path: Path) -> str:
    info = path.stat()
    return sha256_bytes(
        canonical_json_bytes(
            {
                "sha256": _sha256_file(path),
                "bytes": info.st_size,
                "mode": info.st_mode,
                "device": info.st_dev,
                "inode": info.st_ino,
            }
        )
    )


def _command_evidence(
    name: str,
    argv: Sequence[str],
    executable_identity_sha256: str,
    result: CommandResult,
) -> CommandEvidenceV1:
    return CommandEvidenceV1(
        command_name=name,
        argv_sha256=sha256_bytes(canonical_json_bytes({"argv": list(argv)})),
        executable_identity_sha256=executable_identity_sha256,
        returncode=result.returncode,
        stdout_sha256=sha256_bytes(result.stdout),
        stderr_sha256=sha256_bytes(result.stderr),
        stdout_bytes=len(result.stdout),
        stderr_bytes=len(result.stderr),
        timed_out=result.timed_out,
    )


def _sentinel_python_identity() -> PythonIdentityV3:
    return PythonIdentityV3(
        logical_launcher_relative_path="bin/python",
        launcher_kind="invalid",
        launcher_lstat_digest=_EMPTY_SHA256,
        symlink_chain_relative_targets=(),
        symlink_chain_digest=sha256_bytes(canonical_json_bytes({"relative_targets": []})),
        resolved_executable_relative_path="invalid",
        resolved_executable_sha256=_EMPTY_SHA256,
        resolved_executable_bytes=0,
        resolved_executable_mode=0,
        resolved_device=0,
        resolved_inode=0,
        version="invalid",
        implementation="invalid",
    )


def _python_identity(
    resolution: LauncherResolution, *, version: str, implementation: str
) -> PythonIdentityV3:
    return PythonIdentityV3(
        logical_launcher_relative_path="bin/python",
        launcher_kind=resolution.launcher_kind,
        launcher_lstat_digest=resolution.launcher_lstat_digest,
        symlink_chain_relative_targets=resolution.symlink_chain_relative_targets,
        symlink_chain_digest=resolution.symlink_chain_digest,
        resolved_executable_relative_path=resolution.resolved_executable_relative_path,
        resolved_executable_sha256=resolution.resolved_executable_sha256,
        resolved_executable_bytes=resolution.resolved_executable_bytes,
        resolved_executable_mode=resolution.resolved_executable_mode,
        resolved_device=resolution.resolved_device,
        resolved_inode=resolution.resolved_inode,
        version=version,
        implementation=implementation,
    )


def _sentinel_snapshot(
    target: CaptureTarget,
    *,
    state: str,
    python_identity: PythonIdentityV3 | None,
    command_evidence: Sequence[CommandEvidenceV1],
) -> ProtectedObjectSnapshotV3:
    rows = tuple(
        {
            "distribution": name,
            "state": state,
            "version": state,
            "metadata_sha256": _EMPTY_SHA256,
            "record_sha256": _EMPTY_SHA256,
        }
        for name in CRITICAL_DISTRIBUTIONS
    )
    return ProtectedObjectSnapshotV3(
        object_id=target.object_id,
        state=state,
        python_identity=python_identity or _sentinel_python_identity(),
        command_evidence=tuple(command_evidence),
        conda_history_sha256=_EMPTY_SHA256,
        conda_explicit_sha256=_EMPTY_SHA256,
        pip_freeze_sha256=_EMPTY_SHA256,
        critical_distribution_identities=rows,
        filesystem_entry_count=0,
        regular_file_count=0,
        regular_file_bytes=0,
        tree_digest=_EMPTY_SHA256,
        mtime_summary_digest=_EMPTY_SHA256,
    )


def _diagnostic_digest_payload(
    *,
    code: str,
    stage: str,
    assertion: str,
    launcher_classification: str,
    symlink_depth: int,
    inside_root: bool,
    command_evidence: Sequence[CommandEvidenceV1],
    exception_class: str,
    exception_message_digest: str,
) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "code": code,
                "stage": stage,
                "assertion": assertion,
                "launcher_classification": launcher_classification,
                "symlink_depth": symlink_depth,
                "inside_root": inside_root,
                "command_evidence": [row.to_mapping() for row in command_evidence],
                "exception_class": exception_class,
                "exception_message_digest": exception_message_digest,
            }
        )
    )


def _failure_result(
    target: CaptureTarget,
    *,
    state: str,
    code: str,
    stage: str,
    assertion: str,
    resolution: LauncherResolution | None = None,
    launcher_kind: str = "unknown",
    symlink_depth: int = 0,
    inside_root: bool = False,
    command_evidence: Sequence[CommandEvidenceV1] = (),
    exception: BaseException | None = None,
    python_identity: PythonIdentityV3 | None = None,
) -> CaptureResultV1:
    exception_class = "none" if exception is None else type(exception).__name__
    exception_message_digest = sha256_bytes(
        b"" if exception is None else str(exception).encode("utf-8", "replace")
    )
    if resolution is not None:
        launcher_kind = resolution.launcher_kind
        symlink_depth = resolution.symlink_depth
        inside_root = resolution.resolved_target_inside_root
    diagnostic = ProtectedObjectCaptureDiagnosticV1(
        object_id=target.object_id,
        capture_state=state,
        failure=CaptureFailureV1(code, stage, assertion),
        launcher_classification=launcher_kind,
        launcher_relative_path="bin/python",
        symlink_depth=symlink_depth,
        resolved_target_inside_root=inside_root,
        command_evidence=tuple(command_evidence),
        exception_class=exception_class,
        exception_message_digest=exception_message_digest,
        diagnostic_details_digest=_diagnostic_digest_payload(
            code=code,
            stage=stage,
            assertion=assertion,
            launcher_classification=launcher_kind,
            symlink_depth=symlink_depth,
            inside_root=inside_root,
            command_evidence=command_evidence,
            exception_class=exception_class,
            exception_message_digest=exception_message_digest,
        ),
    )
    return CaptureResultV1(
        snapshot=_sentinel_snapshot(
            target,
            state=state,
            python_identity=python_identity,
            command_evidence=command_evidence,
        ),
        diagnostic=diagnostic,
    )


def _assert_resolution_stable(
    target: CaptureTarget, before: LauncherResolution
) -> LauncherResolution:
    after = resolve_environment_python_launcher(target)
    if (
        before.identity_digest != after.identity_digest
        or before.resolved_device != after.resolved_device
        or before.resolved_inode != after.resolved_inode
        or before.resolved_executable != after.resolved_executable
    ):
        raise LauncherResolutionError(
            PYTHON_IDENTITY_DRIFT,
            "launcher chain and resolved target identities remain unchanged after probe",
            launcher_kind=after.launcher_kind,
            symlink_depth=after.symlink_depth,
            inside_root=after.resolved_target_inside_root,
        )
    return after


def _tree_identity(root: Path) -> tuple[int, int, int, str, str]:
    tree_digest = hashlib.sha256()
    mtime_digest = hashlib.sha256()
    entries = regular = size = 0
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as iterator:
            children = sorted(iterator, key=lambda item: item.name)
        for child in children:
            path = Path(child.path)
            info = child.stat(follow_symlinks=False)
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(info.st_mode):
                kind = "d"
                stack.append(path)
            elif stat.S_ISREG(info.st_mode):
                kind = "f"
                regular += 1
                size += info.st_size
            elif stat.S_ISLNK(info.st_mode):
                kind = "l"
            else:
                kind = "o"
            entries += 1
            tree_digest.update(
                f"{relative}\0{kind}\0{info.st_mode:o}\0{info.st_size}\0{info.st_mtime_ns}\n".encode()
            )
            mtime_digest.update(f"{relative}\0{info.st_mtime_ns}\n".encode())
    return entries, regular, size, tree_digest.hexdigest(), mtime_digest.hexdigest()


def _metadata_name_version(raw: bytes) -> tuple[str, str]:
    name = version = ""
    for line in raw.decode("utf-8", "strict").splitlines():
        if line.startswith("Name: ") and not name:
            name = line[6:].strip()
        if line.startswith("Version: ") and not version:
            version = line[9:].strip()
    if not name or not version:
        raise ValueError("METADATA lacks Name or Version")
    return name, version


def _canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _distribution_identities(root: Path) -> tuple[Mapping[str, object], ...]:
    index: dict[str, list[tuple[Path, str]]] = {}
    for site_packages in sorted(root.glob("lib/python*/site-packages")):
        for info in sorted(site_packages.glob("*.dist-info")):
            metadata = info / "METADATA"
            if metadata.is_symlink() or not metadata.is_file():
                raise ValueError(f"invalid METADATA entry: {info.name}")
            name, version = _metadata_name_version(metadata.read_bytes())
            index.setdefault(_canonical_distribution_name(name), []).append((info, version))
    rows: list[Mapping[str, object]] = []
    for requested in CRITICAL_DISTRIBUTIONS:
        matches = index.get(_canonical_distribution_name(requested), [])
        if not matches:
            rows.append(
                {
                    "distribution": requested,
                    "state": "absent",
                    "version": "absent",
                    "metadata_sha256": _EMPTY_SHA256,
                    "record_sha256": _EMPTY_SHA256,
                }
            )
            continue
        if len(matches) != 1:
            raise ValueError(f"duplicate critical distribution: {requested}")
        info, version = matches[0]
        metadata = info / "METADATA"
        record = info / "RECORD"
        rows.append(
            {
                "distribution": requested,
                "state": "present",
                "version": version,
                "metadata_sha256": _sha256_file(metadata),
                "record_sha256": _sha256_file(record) if record.is_file() else _EMPTY_SHA256,
            }
        )
    return tuple(rows)


def capture_protected_object_snapshot(
    target: CaptureTarget,
    *,
    command_runner: CommandRunner = _default_command_runner,
) -> CaptureResultV1:
    """Capture one object with stage-specific, projection-external diagnostics."""

    try:
        root_info = target.root.lstat()
    except FileNotFoundError as exc:
        return _failure_result(
            target,
            state="absent",
            code=ROOT_ABSENT,
            stage="root_lstat",
            assertion="protected object root exists",
            exception=exc,
        )
    except OSError as exc:
        return _failure_result(
            target,
            state="unreadable",
            code=ROOT_UNREADABLE,
            stage="root_lstat",
            assertion="protected object root is readable",
            exception=exc,
        )
    if stat.S_ISLNK(root_info.st_mode):
        return _failure_result(
            target,
            state="invalid",
            code=ROOT_SYMLINK_FORBIDDEN,
            stage="root_classification",
            assertion="protected object root is not a symlink",
        )
    if not stat.S_ISDIR(root_info.st_mode):
        return _failure_result(
            target,
            state="invalid",
            code=ROOT_NOT_DIRECTORY,
            stage="root_classification",
            assertion="protected object root is a directory",
        )

    try:
        resolution = resolve_environment_python_launcher(target)
    except LauncherResolutionError as exc:
        state = "absent" if exc.code == PYTHON_LAUNCHER_MISSING else "invalid"
        return _failure_result(
            target,
            state=state,
            code=exc.code,
            stage="python_launcher_resolution",
            assertion=exc.assertion,
            launcher_kind=exc.launcher_kind,
            symlink_depth=exc.symlink_depth,
            inside_root=exc.inside_root,
            exception=exc.exception,
        )

    history = target.root / "conda-meta/history"
    try:
        history_info = history.lstat()
    except FileNotFoundError as exc:
        return _failure_result(
            target,
            state="invalid",
            code=CONDA_HISTORY_MISSING,
            stage="conda_history",
            assertion="conda history exists",
            resolution=resolution,
            exception=exc,
        )
    except OSError as exc:
        return _failure_result(
            target,
            state="invalid",
            code=CONDA_HISTORY_INVALID,
            stage="conda_history",
            assertion="conda history is readable",
            resolution=resolution,
            exception=exc,
        )
    if stat.S_ISLNK(history_info.st_mode) or not stat.S_ISREG(history_info.st_mode):
        return _failure_result(
            target,
            state="invalid",
            code=CONDA_HISTORY_INVALID,
            stage="conda_history",
            assertion="conda history is a regular non-symlink file",
            resolution=resolution,
        )

    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
        }
    )
    commands: list[CommandEvidenceV1] = []

    def invoke(
        name: str,
        argv: Sequence[str],
        executable_identity_sha256: str,
        failure_code: str,
    ) -> tuple[CommandResult | None, CaptureResultV1 | None]:
        try:
            result = command_runner(argv, environment)
        except Exception as exc:
            return None, _failure_result(
                target,
                state="invalid",
                code=UNEXPECTED_CAPTURE_EXCEPTION,
                stage=f"{name}_invoke",
                assertion=f"{name} command runner returns registered evidence",
                resolution=resolution,
                command_evidence=commands,
                exception=exc,
            )
        evidence = _command_evidence(name, argv, executable_identity_sha256, result)
        commands.append(evidence)
        try:
            _assert_resolution_stable(target, resolution)
        except (LauncherResolutionError, OSError) as exc:
            underlying = exc.exception if isinstance(exc, LauncherResolutionError) else exc
            return None, _failure_result(
                target,
                state="invalid",
                code=PYTHON_IDENTITY_DRIFT,
                stage=f"{name}_post_identity",
                assertion=(
                    "launcher chain and resolved target identities remain unchanged "
                    "after every probe"
                ),
                resolution=resolution,
                command_evidence=commands,
                exception=underlying,
            )
        if result.timed_out or result.returncode != 0:
            return None, _failure_result(
                target,
                state="invalid",
                code=failure_code,
                stage=name,
                assertion=f"{name} returns zero without timeout",
                resolution=resolution,
                command_evidence=commands,
            )
        return result, None

    python_argv = (
        str(resolution.resolved_executable),
        "-I",
        "-B",
        "-c",
        "import json,platform;print(json.dumps({'version':platform.python_version(),"
        "'implementation':platform.python_implementation()}))",
    )
    version_result, failure = invoke(
        "python_version_probe",
        python_argv,
        resolution.identity_digest,
        PYTHON_PROBE_FAILED,
    )
    if failure is not None:
        return failure
    assert version_result is not None
    try:
        version_payload = json.loads(version_result.stdout)
        if (
            not isinstance(version_payload, dict)
            or not isinstance(version_payload.get("version"), str)
            or not isinstance(version_payload.get("implementation"), str)
            or not version_payload["version"]
            or not version_payload["implementation"]
        ):
            raise ValueError("Python probe payload is not the exact object")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        return _failure_result(
            target,
            state="invalid",
            code=PYTHON_PROBE_FAILED,
            stage="python_version_probe_payload",
            assertion="Python probe returns exact version and implementation JSON",
            resolution=resolution,
            command_evidence=commands,
            exception=exc,
        )

    conda_argv = (
        str(target.conda_executable),
        "--offline",
        "list",
        "--prefix",
        str(target.root),
        "--explicit",
    )
    try:
        conda_identity = _external_executable_identity(target.conda_executable)
    except (OSError, ValueError) as exc:
        return _failure_result(
            target,
            state="invalid",
            code=CONDA_EXPLICIT_FAILED,
            stage="conda_executable_identity",
            assertion="exact conda executable identity is readable",
            resolution=resolution,
            command_evidence=commands,
            exception=exc,
        )
    explicit_result, failure = invoke(
        "conda_list_explicit", conda_argv, conda_identity, CONDA_EXPLICIT_FAILED
    )
    if failure is not None:
        return failure
    assert explicit_result is not None

    freeze_argv = (
        str(resolution.resolved_executable),
        "-I",
        "-B",
        "-m",
        "pip",
        "freeze",
        "--all",
    )
    freeze_result, failure = invoke(
        "pip_freeze_all", freeze_argv, resolution.identity_digest, PIP_FREEZE_FAILED
    )
    if failure is not None:
        return failure
    assert freeze_result is not None

    python_identity = _python_identity(
        resolution,
        version=cast(str, version_payload["version"]),
        implementation=cast(str, version_payload["implementation"]),
    )
    try:
        tree = _tree_identity(target.root)
    except OSError as exc:
        return _failure_result(
            target,
            state="unreadable",
            code=TREE_CAPTURE_FAILED,
            stage="tree_capture",
            assertion="protected object tree capture completes",
            resolution=resolution,
            command_evidence=commands,
            exception=exc,
            python_identity=python_identity,
        )
    except Exception as exc:
        return _failure_result(
            target,
            state="invalid",
            code=UNEXPECTED_CAPTURE_EXCEPTION,
            stage="tree_capture",
            assertion="tree capture raises only registered filesystem errors",
            resolution=resolution,
            command_evidence=commands,
            exception=exc,
            python_identity=python_identity,
        )
    try:
        distributions = _distribution_identities(target.root)
    except (OSError, UnicodeError, ValueError) as exc:
        return _failure_result(
            target,
            state="invalid",
            code=DISTRIBUTION_CAPTURE_FAILED,
            stage="distribution_capture",
            assertion="distribution METADATA and RECORD identities are valid",
            resolution=resolution,
            command_evidence=commands,
            exception=exc,
            python_identity=python_identity,
        )
    except Exception as exc:
        return _failure_result(
            target,
            state="invalid",
            code=UNEXPECTED_CAPTURE_EXCEPTION,
            stage="distribution_capture",
            assertion="distribution capture raises only registered parse errors",
            resolution=resolution,
            command_evidence=commands,
            exception=exc,
            python_identity=python_identity,
        )
    try:
        _assert_resolution_stable(target, resolution)
    except (LauncherResolutionError, OSError) as exc:
        underlying = exc.exception if isinstance(exc, LauncherResolutionError) else exc
        return _failure_result(
            target,
            state="invalid",
            code=PYTHON_IDENTITY_DRIFT,
            stage="capture_final_identity",
            assertion=(
                "launcher chain and resolved target identities remain unchanged "
                "through final snapshot assembly"
            ),
            resolution=resolution,
            command_evidence=commands,
            exception=underlying,
            python_identity=python_identity,
        )
    try:
        snapshot = ProtectedObjectSnapshotV3(
            object_id=target.object_id,
            state="present",
            python_identity=python_identity,
            command_evidence=tuple(commands),
            conda_history_sha256=_sha256_file(history),
            conda_explicit_sha256=sha256_bytes(explicit_result.stdout),
            pip_freeze_sha256=sha256_bytes(freeze_result.stdout),
            critical_distribution_identities=distributions,
            filesystem_entry_count=tree[0],
            regular_file_count=tree[1],
            regular_file_bytes=tree[2],
            tree_digest=tree[3],
            mtime_summary_digest=tree[4],
        )
        snapshot.to_mapping()
    except (OSError, SnapshotSchemaError, ValueError) as exc:
        return _failure_result(
            target,
            state="invalid",
            code=SNAPSHOT_SCHEMA_FAILED,
            stage="snapshot_schema",
            assertion="ProtectedObjectSnapshotV3 schema validates exactly",
            resolution=resolution,
            command_evidence=commands,
            exception=exc,
            python_identity=python_identity,
        )
    success_message_digest = _EMPTY_SHA256
    diagnostic = ProtectedObjectCaptureDiagnosticV1(
        object_id=target.object_id,
        capture_state="present",
        failure=None,
        launcher_classification=resolution.launcher_kind,
        launcher_relative_path="bin/python",
        symlink_depth=resolution.symlink_depth,
        resolved_target_inside_root=True,
        command_evidence=tuple(commands),
        exception_class="none",
        exception_message_digest=success_message_digest,
        diagnostic_details_digest=_diagnostic_digest_payload(
            code=NO_FAILURE,
            stage=NO_FAILURE,
            assertion=NO_FAILURE,
            launcher_classification=resolution.launcher_kind,
            symlink_depth=resolution.symlink_depth,
            inside_root=True,
            command_evidence=commands,
            exception_class="none",
            exception_message_digest=success_message_digest,
        ),
    )
    return CaptureResultV1(snapshot=snapshot, diagnostic=diagnostic)


@dataclass(frozen=True, slots=True)
class ProtectedObjectComparisonV2:
    object_id: str
    schema_keyset_equal: bool
    projection_keyset_equal: bool
    projection_bytes_equal: bool
    projection_sha256_equal: bool
    launcher_identity_equal: bool
    resolved_executable_identity_equal: bool
    before_projection_sha256: str
    after_projection_sha256: str
    failure_code: str
    schema_version: str = COMPARISON_SCHEMA_VERSION

    @property
    def passed(self) -> bool:
        return all(
            (
                self.schema_keyset_equal,
                self.projection_keyset_equal,
                self.projection_bytes_equal,
                self.projection_sha256_equal,
                self.launcher_identity_equal,
                self.resolved_executable_identity_equal,
                self.failure_code == NO_FAILURE,
            )
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_id": self.object_id,
            "schema_keyset_equal": self.schema_keyset_equal,
            "projection_keyset_equal": self.projection_keyset_equal,
            "projection_bytes_equal": self.projection_bytes_equal,
            "projection_sha256_equal": self.projection_sha256_equal,
            "launcher_identity_equal": self.launcher_identity_equal,
            "resolved_executable_identity_equal": (self.resolved_executable_identity_equal),
            "before_projection_sha256": self.before_projection_sha256,
            "after_projection_sha256": self.after_projection_sha256,
            "failure_code": self.failure_code,
        }


def compare_observations(
    before: ProtectedObjectObservationReceiptV2,
    after: ProtectedObjectObservationReceiptV2,
) -> ProtectedObjectComparisonV2:
    if not isinstance(before, ProtectedObjectObservationReceiptV2) or not isinstance(
        after, ProtectedObjectObservationReceiptV2
    ):
        raise SnapshotSchemaError(
            "observation receipts must be typed and their projections compared"
        )
    before_mapping = before.snapshot.to_mapping()
    after_mapping = after.snapshot.to_mapping()
    before_projection = before.projection.to_mapping()
    after_projection = after.projection.to_mapping()
    schema_equal = set(before_mapping) == set(after_mapping)
    projection_keys_equal = set(before_projection) == set(after_projection)
    bytes_equal = before.projection.canonical_bytes() == after.projection.canonical_bytes()
    sha_equal = before.projection_sha256 == after.projection_sha256
    left_python = before.snapshot.python_identity
    right_python = after.snapshot.python_identity
    launcher_equal = (
        left_python.launcher_kind == right_python.launcher_kind
        and left_python.launcher_lstat_digest == right_python.launcher_lstat_digest
        and left_python.symlink_chain_digest == right_python.symlink_chain_digest
    )
    executable_equal = (
        left_python.resolved_executable_relative_path
        == right_python.resolved_executable_relative_path
        and left_python.resolved_executable_sha256 == right_python.resolved_executable_sha256
        and left_python.resolved_executable_bytes == right_python.resolved_executable_bytes
        and left_python.resolved_executable_mode == right_python.resolved_executable_mode
    )
    passed = all(
        (
            schema_equal,
            projection_keys_equal,
            bytes_equal,
            sha_equal,
            launcher_equal,
            executable_equal,
        )
    )
    return ProtectedObjectComparisonV2(
        object_id=before.snapshot.object_id,
        schema_keyset_equal=schema_equal,
        projection_keyset_equal=projection_keys_equal,
        projection_bytes_equal=bytes_equal,
        projection_sha256_equal=sha_equal,
        launcher_identity_equal=launcher_equal,
        resolved_executable_identity_equal=executable_equal,
        before_projection_sha256=before.projection_sha256,
        after_projection_sha256=after.projection_sha256,
        failure_code=NO_FAILURE if passed else "PROTECTED_SNAPSHOT_CONTENT_DRIFT",
    )


@dataclass(frozen=True, slots=True)
class QualificationObjectResultV2:
    object_id: str
    launcher_kind: str
    symlink_depth: int
    symlink_chain_relative_targets: tuple[str, ...]
    resolved_executable_relative_path: str
    resolved_target_inside_root: bool
    snapshot_a_state: str
    snapshot_b_state: str
    diagnostic_a_status: str
    diagnostic_b_status: str
    diagnostic_a_failure_code: str
    diagnostic_b_failure_code: str
    snapshot_a_projection_sha256: str
    snapshot_b_projection_sha256: str
    comparison: ProtectedObjectComparisonV2
    qualification_result: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "launcher_kind": self.launcher_kind,
            "symlink_depth": self.symlink_depth,
            "symlink_chain_relative_targets": list(self.symlink_chain_relative_targets),
            "resolved_executable_relative_path": (self.resolved_executable_relative_path),
            "resolved_target_inside_root": self.resolved_target_inside_root,
            "snapshot_a_state": self.snapshot_a_state,
            "snapshot_b_state": self.snapshot_b_state,
            "diagnostic_a_status": self.diagnostic_a_status,
            "diagnostic_b_status": self.diagnostic_b_status,
            "diagnostic_a_failure_code": self.diagnostic_a_failure_code,
            "diagnostic_b_failure_code": self.diagnostic_b_failure_code,
            "snapshot_a_projection_sha256": self.snapshot_a_projection_sha256,
            "snapshot_b_projection_sha256": self.snapshot_b_projection_sha256,
            "comparison": self.comparison.to_mapping(),
            "qualification_result": self.qualification_result,
        }


@dataclass(frozen=True, slots=True)
class MeasurementQualificationReceiptV2:
    attempt_id: str
    helper_source_sha256: str
    object_results: tuple[QualificationObjectResultV2, ...]
    all_passed: bool
    server_write_performed_between_captures: bool = False
    schema_version: str = QUALIFICATION_SCHEMA_VERSION

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "helper_source_sha256": self.helper_source_sha256,
            "server_write_performed_between_captures": (
                self.server_write_performed_between_captures
            ),
            "all_passed": self.all_passed,
            "object_results": [row.to_mapping() for row in self.object_results],
        }


def qualify_measurement_system(
    targets: Sequence[CaptureTarget],
    *,
    attempt_id: str,
    helper_source_sha256: str,
    command_runner: CommandRunner = _default_command_runner,
    clock_ns: Callable[[], int] = time.time_ns,
    observer_pid: int | None = None,
) -> MeasurementQualificationReceiptV2:
    target_ids = [target.object_id for target in targets]
    if len(target_ids) != len(set(target_ids)) or set(target_ids) != U4_PROTECTED_OBJECT_IDS:
        raise SnapshotSchemaError("qualification targets must equal the frozen U4 set")
    _require_sha256(helper_source_sha256, "helper_source_sha256")
    pid = os.getpid() if observer_pid is None else observer_pid
    rows: list[QualificationObjectResultV2] = []
    for target in targets:
        capture_a = capture_protected_object_snapshot(target, command_runner=command_runner)
        observation_a = build_observation_receipt(
            capture_a,
            observation_phase="qualification_a",
            attempt_id=attempt_id,
            observed_at_ns=clock_ns(),
            observer_pid=pid,
        )
        capture_b = capture_protected_object_snapshot(target, command_runner=command_runner)
        observation_b = build_observation_receipt(
            capture_b,
            observation_phase="qualification_b",
            attempt_id=attempt_id,
            observed_at_ns=clock_ns(),
            observer_pid=pid,
        )
        comparison = compare_observations(observation_a, observation_b)
        diagnostic_a_code = (
            NO_FAILURE
            if capture_a.diagnostic.failure is None
            else capture_a.diagnostic.failure.code
        )
        diagnostic_b_code = (
            NO_FAILURE
            if capture_b.diagnostic.failure is None
            else capture_b.diagnostic.failure.code
        )
        passed = (
            capture_a.snapshot.state == capture_b.snapshot.state == "present"
            and capture_a.diagnostic.failure is None
            and capture_b.diagnostic.failure is None
            and capture_a.diagnostic.resolved_target_inside_root
            and capture_b.diagnostic.resolved_target_inside_root
            and comparison.passed
        )
        identity = capture_a.snapshot.python_identity
        rows.append(
            QualificationObjectResultV2(
                object_id=target.object_id,
                launcher_kind=identity.launcher_kind,
                symlink_depth=len(identity.symlink_chain_relative_targets),
                symlink_chain_relative_targets=identity.symlink_chain_relative_targets,
                resolved_executable_relative_path=(identity.resolved_executable_relative_path),
                resolved_target_inside_root=(
                    capture_a.diagnostic.resolved_target_inside_root
                    and capture_b.diagnostic.resolved_target_inside_root
                ),
                snapshot_a_state=capture_a.snapshot.state,
                snapshot_b_state=capture_b.snapshot.state,
                diagnostic_a_status=capture_a.diagnostic.diagnostic_status,
                diagnostic_b_status=capture_b.diagnostic.diagnostic_status,
                diagnostic_a_failure_code=diagnostic_a_code,
                diagnostic_b_failure_code=diagnostic_b_code,
                snapshot_a_projection_sha256=observation_a.projection_sha256,
                snapshot_b_projection_sha256=observation_b.projection_sha256,
                comparison=comparison,
                qualification_result="passed" if passed else "failed",
            )
        )
    return MeasurementQualificationReceiptV2(
        attempt_id=attempt_id,
        helper_source_sha256=helper_source_sha256,
        object_results=tuple(rows),
        all_passed=all(row.qualification_result == "passed" for row in rows),
    )
