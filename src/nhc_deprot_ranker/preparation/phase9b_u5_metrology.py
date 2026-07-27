"""Conda-metadata-native protected-object metrology for Phase 9B-U5.

This module is deliberately independent from the retained U3/U4 helpers.  It
does not initialize a package manager or inspect user configuration.  The only
subprocess it permits is the authenticated target-prefix Python executable,
used with isolated, bytecode-disabled flags for a standard-library probe.
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
from email.parser import Parser
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlsplit, urlunsplit

SNAPSHOT_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-snapshot-v4"
PROJECTION_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-identity-projection-v3"
OBSERVATION_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-observation-receipt-v4"
COMPARISON_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-comparison-receipt-v4"
DIAGNOSTIC_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-capture-diagnostic-v2"
CONDA_INVENTORY_SCHEMA_VERSION: Final = "nhc-phase9b-conda-prefix-inventory-v1"
DISTRIBUTION_INVENTORY_SCHEMA_VERSION: Final = "nhc-phase9b-python-distribution-inventory-v1"
QUALIFICATION_SCHEMA_VERSION: Final = "nhc-phase9b-measurement-qualification-receipt-v3"

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
PYTHON_PROBE_FAILED: Final = "PYTHON_PROBE_FAILED"
CONDA_META_DIRECTORY_MISSING: Final = "CONDA_META_DIRECTORY_MISSING"
CONDA_META_DIRECTORY_INVALID: Final = "CONDA_META_DIRECTORY_INVALID"
CONDA_META_DIRECTORY_UNREADABLE: Final = "CONDA_META_DIRECTORY_UNREADABLE"
CONDA_HISTORY_MISSING: Final = "CONDA_HISTORY_MISSING"
CONDA_HISTORY_INVALID: Final = "CONDA_HISTORY_INVALID"
CONDA_HISTORY_UNREADABLE: Final = "CONDA_HISTORY_UNREADABLE"
CONDA_RECORD_SET_EMPTY: Final = "CONDA_RECORD_SET_EMPTY"
CONDA_RECORD_INVALID: Final = "CONDA_RECORD_INVALID"
CONDA_RECORD_UNREADABLE: Final = "CONDA_RECORD_UNREADABLE"
CONDA_RECORD_REQUIRED_FIELD_MISSING: Final = "CONDA_RECORD_REQUIRED_FIELD_MISSING"
CONDA_RECORD_FIELD_TYPE_INVALID: Final = "CONDA_RECORD_FIELD_TYPE_INVALID"
DISTRIBUTION_METADATA_MISSING: Final = "DISTRIBUTION_METADATA_MISSING"
DISTRIBUTION_METADATA_INVALID: Final = "DISTRIBUTION_METADATA_INVALID"
DISTRIBUTION_METADATA_UNREADABLE: Final = "DISTRIBUTION_METADATA_UNREADABLE"
DISTRIBUTION_METADATA_SYMLINK: Final = "DISTRIBUTION_METADATA_SYMLINK"
DISTRIBUTION_CAPTURE_FAILED: Final = "DISTRIBUTION_CAPTURE_FAILED"
TREE_CAPTURE_FAILED: Final = "TREE_CAPTURE_FAILED"
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
        PYTHON_PROBE_FAILED,
        CONDA_META_DIRECTORY_MISSING,
        CONDA_META_DIRECTORY_INVALID,
        CONDA_META_DIRECTORY_UNREADABLE,
        CONDA_HISTORY_MISSING,
        CONDA_HISTORY_INVALID,
        CONDA_HISTORY_UNREADABLE,
        CONDA_RECORD_SET_EMPTY,
        CONDA_RECORD_INVALID,
        CONDA_RECORD_UNREADABLE,
        CONDA_RECORD_REQUIRED_FIELD_MISSING,
        CONDA_RECORD_FIELD_TYPE_INVALID,
        DISTRIBUTION_METADATA_MISSING,
        DISTRIBUTION_METADATA_INVALID,
        DISTRIBUTION_METADATA_UNREADABLE,
        DISTRIBUTION_METADATA_SYMLINK,
        DISTRIBUTION_CAPTURE_FAILED,
        TREE_CAPTURE_FAILED,
        SNAPSHOT_SCHEMA_FAILED,
        UNEXPECTED_CAPTURE_EXCEPTION,
        EVIDENCE_INCOMPLETE,
    }
)
SNAPSHOT_STATES: Final = frozenset({"present", "absent", "unreadable", "invalid"})
OBSERVATION_PHASES: Final = frozenset(
    {"qualification_a", "qualification_b", "protected_before", "protected_after"}
)
U5_PROTECTED_OBJECT_IDS: Final = frozenset(
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
REQUIRED_CONDA_FIELDS: Final = frozenset({"name", "version", "build", "build_number"})
OPTIONAL_CONDA_FIELDS: Final = frozenset(
    {
        "channel",
        "subdir",
        "fn",
        "url",
        "md5",
        "sha256",
        "depends",
        "constrains",
        "noarch",
        "package_type",
        "requested_spec",
        "requested_specs",
    }
)
IGNORED_PREFIX_LOCAL_FIELDS: Final = frozenset(
    {
        "link",
        "files",
        "paths_data",
        "extracted_package_dir",
        "package_tarball_full_path",
        "prefix",
        "cache_path",
        "_source",
    }
)
MAX_SYMLINK_DEPTH: Final = 16
TREE_FULL_HASH_THRESHOLD_BYTES: Final = 1024 * 1024
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_NAME_RE: Final = re.compile(r"[-_.]+")
_SHARED_LIBRARY_RE: Final = re.compile(r"(?:\.so(?:\.|$)|\.dylib$|\.dll$)")
_EMPTY_SHA256: Final = hashlib.sha256(b"").hexdigest()


class U5MetrologyError(RuntimeError):
    """A frozen U5 metrology assertion could not be proved."""


class SnapshotSchemaError(U5MetrologyError):
    """A U5 strongly typed payload violated its schema."""


class StageCaptureError(U5MetrologyError):
    """A registered capture-stage failure with portable diagnostics."""

    def __init__(
        self,
        code: str,
        stage: str,
        assertion: str,
        *,
        state: str = "invalid",
        cause: BaseException | None = None,
        partial_evidence: object | None = None,
    ) -> None:
        super().__init__(assertion)
        if code not in FAILURE_CODES or state not in SNAPSHOT_STATES - {"present"}:
            raise ValueError("unregistered capture failure")
        self.code = code
        self.stage = stage
        self.assertion = assertion
        self.state = state
        self.cause = cause
        self.partial_evidence = partial_evidence


def canonical_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_name(value: str) -> str:
    return _CANONICAL_NAME_RE.sub("-", value).lower()


def _require_sha256(value: str, label: str) -> None:
    if not _SHA256_RE.fullmatch(value):
        raise SnapshotSchemaError(f"{label} must be a lowercase SHA256")


def _relative_inside(root: Path, candidate: Path, *, stage: str) -> str:
    normalized_root = Path(os.path.normpath(str(root)))
    normalized_candidate = Path(os.path.normpath(str(candidate)))
    try:
        common = Path(os.path.commonpath((normalized_root, normalized_candidate)))
    except ValueError as exc:
        raise StageCaptureError(
            PYTHON_SYMLINK_ESCAPES_ENV,
            stage,
            "candidate remains inside exact environment root",
            cause=exc,
        ) from exc
    if common != normalized_root:
        raise StageCaptureError(
            PYTHON_SYMLINK_ESCAPES_ENV,
            stage,
            "candidate remains inside exact environment root",
        )
    return normalized_candidate.relative_to(normalized_root).as_posix()


@dataclass(frozen=True, slots=True)
class CaptureTarget:
    object_id: str
    root: Path

    def __post_init__(self) -> None:
        if not self.object_id or not self.root.is_absolute():
            raise ValueError("capture target requires object ID and absolute root")


@dataclass(frozen=True, slots=True)
class FileIdentity:
    relative_path: str
    kind: str
    mode: int
    size: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int
    link_target: str

    def to_mapping(self, *, portable: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "relative_path": self.relative_path,
            "kind": self.kind,
            "mode": self.mode,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "ctime_ns": self.ctime_ns,
            "link_target": self.link_target,
        }
        if not portable:
            payload.update({"device": self.device, "inode": self.inode})
        return payload

    def digest(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_mapping()))


def _node_identity(root: Path, path: Path) -> FileIdentity:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        kind, link_target = "symlink", os.readlink(path)
    elif stat.S_ISREG(info.st_mode):
        kind, link_target = "regular", ""
    elif stat.S_ISDIR(info.st_mode):
        kind, link_target = "directory", ""
    else:
        kind, link_target = "other", ""
    return FileIdentity(
        relative_path=_relative_inside(root, path, stage="filesystem_identity"),
        kind=kind,
        mode=info.st_mode,
        size=info.st_size,
        device=info.st_dev,
        inode=info.st_ino,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
        link_target=link_target,
    )


@dataclass(frozen=True, slots=True)
class LauncherEvidence:
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
    resolved_target_inside_root: bool
    private_chain_identities: tuple[FileIdentity, ...]
    resolved_executable: Path

    @property
    def symlink_depth(self) -> int:
        return len(self.symlink_chain_relative_targets)

    @property
    def identity_digest(self) -> str:
        return sha256_bytes(
            canonical_json_bytes(
                {
                    "chain": [row.to_mapping() for row in self.private_chain_identities],
                    "resolved_relative": self.resolved_executable_relative_path,
                    "resolved_sha256": self.resolved_executable_sha256,
                    "resolved_bytes": self.resolved_executable_bytes,
                    "resolved_mode": self.resolved_executable_mode,
                    "resolved_device": self.resolved_device,
                    "resolved_inode": self.resolved_inode,
                }
            )
        )

    def stable_mapping(self) -> dict[str, object]:
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
            "resolved_target_inside_root": self.resolved_target_inside_root,
        }

    def evidence_mapping(self) -> dict[str, object]:
        payload = self.stable_mapping()
        payload.update(
            {
                "resolved_device": self.resolved_device,
                "resolved_inode": self.resolved_inode,
                "private_chain_identities": [
                    row.to_mapping() for row in self.private_chain_identities
                ],
                "identity_digest": self.identity_digest,
            }
        )
        return payload


def resolve_environment_python_launcher(target: CaptureTarget) -> LauncherEvidence:
    """Authenticate a regular or environment-local symlinked Python launcher."""

    root = Path(os.path.normpath(str(target.root)))
    logical = root / "bin/python"
    current = logical
    visited: set[str] = set()
    nodes: list[FileIdentity] = []
    relative_targets: list[str] = []
    launcher_kind = "missing"
    for depth in range(MAX_SYMLINK_DEPTH + 1):
        current = Path(os.path.normpath(str(current)))
        current_key = str(current)
        if current_key in visited:
            raise StageCaptureError(
                PYTHON_SYMLINK_LOOP,
                "python_launcher_resolution",
                "Python launcher symlink chain is acyclic and bounded",
            )
        visited.add(current_key)
        try:
            node = _node_identity(root, current)
        except FileNotFoundError as exc:
            code = PYTHON_LAUNCHER_MISSING if depth == 0 else PYTHON_SYMLINK_DANGLING
            raise StageCaptureError(
                code,
                "python_launcher_resolution",
                "Python launcher and every symlink target exist",
                cause=exc,
            ) from exc
        except PermissionError as exc:
            raise StageCaptureError(
                ROOT_UNREADABLE,
                "python_launcher_resolution",
                "Python launcher chain is readable",
                state="unreadable",
                cause=exc,
            ) from exc
        if depth == 0:
            launcher_kind = node.kind
        nodes.append(node)
        if node.kind != "symlink":
            break
        if depth == MAX_SYMLINK_DEPTH:
            raise StageCaptureError(
                PYTHON_SYMLINK_LOOP,
                "python_launcher_resolution",
                "Python launcher symlink chain is acyclic and bounded",
            )
        candidate = (
            Path(node.link_target)
            if os.path.isabs(node.link_target)
            else current.parent / node.link_target
        )
        candidate = Path(os.path.normpath(str(candidate)))
        relative_targets.append(
            _relative_inside(root, candidate, stage="python_launcher_containment")
        )
        current = candidate
    final = nodes[-1]
    if final.kind != "regular":
        raise StageCaptureError(
            PYTHON_TARGET_NOT_REGULAR,
            "python_launcher_resolution",
            "resolved Python target is a regular file",
        )
    try:
        canonical = current.resolve(strict=True)
    except FileNotFoundError as exc:
        raise StageCaptureError(
            PYTHON_SYMLINK_DANGLING,
            "python_launcher_resolution",
            "resolved Python target exists",
            cause=exc,
        ) from exc
    except RuntimeError as exc:
        raise StageCaptureError(
            PYTHON_SYMLINK_LOOP,
            "python_launcher_resolution",
            "Python launcher symlink chain is acyclic",
            cause=exc,
        ) from exc
    resolved_relative = _relative_inside(
        root, canonical, stage="python_launcher_canonical_containment"
    )
    if canonical != current:
        raise StageCaptureError(
            PYTHON_SYMLINK_ESCAPES_ENV,
            "python_launcher_resolution",
            "every symlink in the launcher chain is explicitly authenticated",
        )
    info = canonical.stat()
    if not stat.S_ISREG(info.st_mode):
        raise StageCaptureError(
            PYTHON_TARGET_NOT_REGULAR,
            "python_launcher_resolution",
            "resolved Python target is a regular file",
        )
    if not info.st_mode & 0o111 or not os.access(canonical, os.X_OK):
        raise StageCaptureError(
            PYTHON_TARGET_NOT_EXECUTABLE,
            "python_launcher_resolution",
            "resolved Python target is executable",
        )
    try:
        executable_sha256 = _sha256_file(canonical)
    except OSError as exc:
        raise StageCaptureError(
            ROOT_UNREADABLE,
            "python_launcher_hash",
            "resolved Python target bytes are readable",
            state="unreadable",
            cause=exc,
        ) from exc
    return LauncherEvidence(
        logical_launcher_relative_path="bin/python",
        launcher_kind=launcher_kind,
        launcher_lstat_digest=nodes[0].digest(),
        symlink_chain_relative_targets=tuple(relative_targets),
        symlink_chain_digest=sha256_bytes(
            canonical_json_bytes({"relative_targets": relative_targets})
        ),
        resolved_executable_relative_path=resolved_relative,
        resolved_executable_sha256=executable_sha256,
        resolved_executable_bytes=info.st_size,
        resolved_executable_mode=info.st_mode,
        resolved_device=info.st_dev,
        resolved_inode=info.st_ino,
        resolved_target_inside_root=True,
        private_chain_identities=tuple(nodes),
        resolved_executable=canonical,
    )


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False


CommandRunner = Callable[[Sequence[str], Mapping[str, str]], CommandResult]


@dataclass(frozen=True, slots=True)
class PythonProbeEvidence:
    argv_sha256: str
    executable_identity_sha256: str
    returncode: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    timed_out: bool
    version: str
    implementation: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "argv_sha256": self.argv_sha256,
            "executable_identity_sha256": self.executable_identity_sha256,
            "returncode": self.returncode,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "timed_out": self.timed_out,
            "version": self.version,
            "implementation": self.implementation,
        }


def _default_command_runner(argv: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            env=dict(environment),
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=exc.stdout or b"",
            stderr=exc.stderr or b"",
            timed_out=True,
        )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


_PYTHON_PROBE_SOURCE: Final = (
    "import json,platform;"
    "print(json.dumps({'implementation':platform.python_implementation(),"
    "'version':platform.python_version()},sort_keys=True))"
)


def capture_python_probe(
    target: CaptureTarget,
    launcher: LauncherEvidence,
    runner: CommandRunner,
) -> PythonProbeEvidence:
    argv = (str(launcher.resolved_executable), "-I", "-B", "-c", _PYTHON_PROBE_SOURCE)
    environment = {
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
    }
    try:
        result = runner(argv, environment)
    except Exception as exc:
        raise StageCaptureError(
            UNEXPECTED_CAPTURE_EXCEPTION,
            "python_probe_invoke",
            "authenticated Python probe returns registered command evidence",
            cause=exc,
        ) from exc
    argv_sha256 = sha256_bytes(canonical_json_bytes(list(argv)))
    stdout_sha256 = sha256_bytes(result.stdout)
    stderr_sha256 = sha256_bytes(result.stderr)
    partial = PythonProbeEvidence(
        argv_sha256=argv_sha256,
        executable_identity_sha256=launcher.identity_digest,
        returncode=result.returncode,
        stdout_sha256=stdout_sha256,
        stderr_sha256=stderr_sha256,
        stdout_bytes=len(result.stdout),
        stderr_bytes=len(result.stderr),
        timed_out=result.timed_out,
        version="unavailable",
        implementation="unavailable",
    )
    if result.timed_out or result.returncode != 0:
        raise StageCaptureError(
            PYTHON_PROBE_FAILED,
            "python_probe_command",
            "isolated authenticated Python probe returns zero without timeout",
            partial_evidence=partial,
        )
    try:
        payload = json.loads(result.stdout.decode("utf-8", errors="strict"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"implementation", "version"}
            or not isinstance(payload["implementation"], str)
            or not isinstance(payload["version"], str)
            or not payload["implementation"]
            or not payload["version"]
        ):
            raise ValueError("probe payload keyset or value type invalid")
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise StageCaptureError(
            PYTHON_PROBE_FAILED,
            "python_probe_payload",
            "isolated Python probe returns exact version/implementation JSON",
            cause=exc,
            partial_evidence=partial,
        ) from exc
    after = resolve_environment_python_launcher(target)
    if launcher.identity_digest != after.identity_digest:
        raise StageCaptureError(
            PYTHON_IDENTITY_DRIFT,
            "python_probe_post_identity",
            "launcher chain and resolved executable identity are stable across probe",
            partial_evidence=partial,
        )
    return PythonProbeEvidence(
        argv_sha256=argv_sha256,
        executable_identity_sha256=launcher.identity_digest,
        returncode=result.returncode,
        stdout_sha256=stdout_sha256,
        stderr_sha256=stderr_sha256,
        stdout_bytes=len(result.stdout),
        stderr_bytes=len(result.stderr),
        timed_out=result.timed_out,
        version=payload["version"],
        implementation=payload["implementation"],
    )


def _strict_json_object(raw: bytes, *, filename: str) -> dict[str, object]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise StageCaptureError(
            CONDA_RECORD_INVALID,
            "conda_record_decode",
            f"{filename} is strict UTF-8",
            cause=exc,
        ) from exc

    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        parsed = json.loads(text, object_pairs_hook=pairs_hook, parse_constant=reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise StageCaptureError(
            CONDA_RECORD_INVALID,
            "conda_record_parse",
            f"{filename} is a strict JSON object without duplicate keys",
            cause=exc,
        ) from exc
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise StageCaptureError(
            CONDA_RECORD_INVALID,
            "conda_record_parse",
            f"{filename} top-level value is a JSON object with string keys",
        )
    return cast(dict[str, object], parsed)


def _sanitize_locator(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        port = f":{parsed.port}" if parsed.port is not None else ""
        tail = Path(parsed.path).name
        path = f"/<redacted>/{tail}" if tail else "/<redacted>"
        return urlunsplit((parsed.scheme, f"{parsed.hostname}{port}", path, "", ""))
    if parsed.scheme == "file" or os.path.isabs(value) or value.startswith("~"):
        return f"<local>/{Path(parsed.path or value).name}"
    if "/" in value or "\\" in value:
        return f"<locator>/{Path(value).name}"
    return value


def _normalized_optional_value(name: str, value: object) -> object:
    if name in {"channel", "url"}:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be string")
        return _sanitize_locator(value)
    if name in {"subdir", "fn", "md5", "sha256", "package_type"}:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be string")
        return value
    if name in {"depends", "constrains"}:
        if not isinstance(value, list) or not all(isinstance(row, str) for row in value):
            raise TypeError(f"{name} must be list[str]")
        return sorted(value)
    if name == "requested_specs":
        if isinstance(value, list) and all(isinstance(row, str) for row in value):
            return sorted(value)
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            return cast(dict[str, object], value)
        raise TypeError("requested_specs must be list[str] or object")
    if name == "requested_spec":
        if isinstance(value, (str, dict, list)):
            return value
        raise TypeError("requested_spec must be string, list, or object")
    if name == "noarch":
        if value is None or isinstance(value, (str, bool, dict)):
            return value
        raise TypeError("noarch must be null, string, boolean, or object")
    raise AssertionError(f"unhandled optional field {name}")


def _normalize_conda_record(
    record: Mapping[str, object], *, filename: str, raw_sha256: str
) -> dict[str, object]:
    missing = sorted(REQUIRED_CONDA_FIELDS - record.keys())
    if missing:
        raise StageCaptureError(
            CONDA_RECORD_REQUIRED_FIELD_MISSING,
            "conda_record_normalization",
            f"{filename} contains required fields: {','.join(missing)}",
        )
    for name in ("name", "version", "build"):
        if not isinstance(record[name], str) or not cast(str, record[name]):
            raise StageCaptureError(
                CONDA_RECORD_FIELD_TYPE_INVALID,
                "conda_record_normalization",
                f"{filename}.{name} is a non-empty string",
            )
    if isinstance(record["build_number"], bool) or not isinstance(record["build_number"], int):
        raise StageCaptureError(
            CONDA_RECORD_FIELD_TYPE_INVALID,
            "conda_record_normalization",
            f"{filename}.build_number is an integer",
        )
    optional: dict[str, object] = {}
    try:
        for name in sorted(OPTIONAL_CONDA_FIELDS & record.keys()):
            optional[name] = _normalized_optional_value(name, record[name])
    except TypeError as exc:
        raise StageCaptureError(
            CONDA_RECORD_FIELD_TYPE_INVALID,
            "conda_record_normalization",
            f"{filename} optional identity field types are valid",
            cause=exc,
        ) from exc
    ignored_names = sorted(IGNORED_PREFIX_LOCAL_FIELDS & record.keys())
    ignored_payload = {name: record[name] for name in ignored_names}
    known = REQUIRED_CONDA_FIELDS | OPTIONAL_CONDA_FIELDS | IGNORED_PREFIX_LOCAL_FIELDS
    unknown_names = sorted(record.keys() - known)
    return {
        "canonical_name": _canonical_name(cast(str, record["name"])),
        "version": record["version"],
        "build": record["build"],
        "build_number": record["build_number"],
        "optional_identity_fields": optional,
        "ignored_field_names": ignored_names,
        "ignored_fields_digest": sha256_bytes(canonical_json_bytes(ignored_payload)),
        "unknown_field_names": unknown_names,
        "source_record_raw_sha256": raw_sha256,
    }


def _stable_read(
    path: Path, *, error_code: str, stage: str, assertion: str
) -> tuple[bytes, os.stat_result]:
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise StageCaptureError(error_code, stage, assertion)
        raw = path.read_bytes()
        after = path.lstat()
    except StageCaptureError:
        raise
    except FileNotFoundError as exc:
        raise StageCaptureError(error_code, stage, assertion, cause=exc) from exc
    except PermissionError as exc:
        raise StageCaptureError(
            error_code, stage, assertion, state="unreadable", cause=exc
        ) from exc
    except OSError as exc:
        raise StageCaptureError(error_code, stage, assertion, cause=exc) from exc
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, name) != getattr(after, name) for name in fields):
        raise StageCaptureError(error_code, stage, f"{assertion}; identity remains stable")
    return raw, after


def capture_conda_prefix_inventory(root: Path) -> dict[str, object]:
    """Read the installed-prefix inventory directly from ``conda-meta``."""

    meta = root / "conda-meta"
    try:
        meta_before = meta.lstat()
    except FileNotFoundError as exc:
        raise StageCaptureError(
            CONDA_META_DIRECTORY_MISSING,
            "conda_meta_directory",
            "conda-meta directory exists",
            cause=exc,
        ) from exc
    except PermissionError as exc:
        raise StageCaptureError(
            CONDA_META_DIRECTORY_UNREADABLE,
            "conda_meta_directory",
            "conda-meta directory is readable",
            state="unreadable",
            cause=exc,
        ) from exc
    if stat.S_ISLNK(meta_before.st_mode) or not stat.S_ISDIR(meta_before.st_mode):
        raise StageCaptureError(
            CONDA_META_DIRECTORY_INVALID,
            "conda_meta_directory",
            "conda-meta is a non-symlink directory",
        )
    _relative_inside(root, meta, stage="conda_meta_containment")
    history_path = meta / "history"
    if not history_path.exists():
        raise StageCaptureError(
            CONDA_HISTORY_MISSING,
            "conda_history",
            "conda-meta/history exists",
        )
    history_raw, history_stat = _stable_read(
        history_path,
        error_code=CONDA_HISTORY_INVALID,
        stage="conda_history",
        assertion="conda-meta/history is a stable non-symlink regular file",
    )
    try:
        names = sorted(path.name for path in meta.iterdir() if path.name.endswith(".json"))
    except PermissionError as exc:
        raise StageCaptureError(
            CONDA_META_DIRECTORY_UNREADABLE,
            "conda_record_enumeration",
            "conda-meta entries are readable",
            state="unreadable",
            cause=exc,
        ) from exc
    if not names:
        raise StageCaptureError(
            CONDA_RECORD_SET_EMPTY,
            "conda_record_enumeration",
            "conda-meta contains at least one package record",
        )
    if len(names) != len(set(names)):
        raise StageCaptureError(
            CONDA_RECORD_INVALID,
            "conda_record_enumeration",
            "conda record basenames are unique",
        )
    records: list[dict[str, object]] = []
    unknown_names: set[str] = set()
    for filename in names:
        path = meta / filename
        raw, _ = _stable_read(
            path,
            error_code=CONDA_RECORD_UNREADABLE,
            stage="conda_record_read",
            assertion=f"{filename} is a stable non-symlink regular file",
        )
        raw_sha256 = sha256_bytes(raw)
        record = _strict_json_object(raw, filename=filename)
        normalized = _normalize_conda_record(record, filename=filename, raw_sha256=raw_sha256)
        unknown_names.update(cast(list[str], normalized["unknown_field_names"]))
        records.append(
            {
                "record_filename": filename,
                "raw_sha256": raw_sha256,
                "raw_bytes": len(raw),
                "normalized_projection": normalized,
            }
        )
    try:
        meta_after = meta.lstat()
    except OSError as exc:
        raise StageCaptureError(
            CONDA_META_DIRECTORY_UNREADABLE,
            "conda_meta_post_identity",
            "conda-meta identity is readable after capture",
            state="unreadable",
            cause=exc,
        ) from exc
    stable_fields = ("st_dev", "st_ino", "st_mode", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(meta_before, name) != getattr(meta_after, name) for name in stable_fields):
        raise StageCaptureError(
            CONDA_META_DIRECTORY_INVALID,
            "conda_meta_post_identity",
            "conda-meta directory identity remains stable during capture",
        )
    raw_set = [
        {"filename": row["record_filename"], "sha256": row["raw_sha256"], "bytes": row["raw_bytes"]}
        for row in records
    ]
    normalized_set = [row["normalized_projection"] for row in records]
    return {
        "schema_version": CONDA_INVENTORY_SCHEMA_VERSION,
        "history_sha256": sha256_bytes(history_raw),
        "history_bytes": len(history_raw),
        "history_mtime_ns": history_stat.st_mtime_ns,
        "history_line_count": len(history_raw.splitlines()),
        "record_count": len(records),
        "records": records,
        "raw_record_set_sha256": sha256_bytes(canonical_json_bytes(raw_set)),
        "normalized_record_set_sha256": sha256_bytes(canonical_json_bytes(normalized_set)),
        "record_filename_set_sha256": sha256_bytes(canonical_json_bytes(names)),
        "unknown_field_name_set_sha256": sha256_bytes(canonical_json_bytes(sorted(unknown_names))),
    }


def _optional_dist_file(directory: Path, filename: str) -> dict[str, object]:
    path = directory / filename
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"state": "absent", "sha256": None, "bytes": 0}
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise StageCaptureError(
            DISTRIBUTION_METADATA_INVALID,
            "distribution_auxiliary_file",
            f"{directory.name}/{filename} is absent or a non-symlink regular file",
        )
    raw, _ = _stable_read(
        path,
        error_code=DISTRIBUTION_METADATA_UNREADABLE,
        stage="distribution_auxiliary_file",
        assertion=f"{directory.name}/{filename} is stable and readable",
    )
    return {"state": "present", "sha256": sha256_bytes(raw), "bytes": len(raw)}


def capture_python_distribution_inventory(root: Path) -> dict[str, object]:
    """Capture every ``*.dist-info`` directly, without a package-management CLI."""

    candidates: set[Path] = set()
    for lib_name in ("lib", "lib64"):
        lib = root / lib_name
        if not lib.is_dir() or lib.is_symlink():
            continue
        for python_dir in sorted(lib.glob("python*")):
            site_packages = python_dir / "site-packages"
            if not site_packages.is_dir() or site_packages.is_symlink():
                continue
            candidates.update(site_packages.glob("*.dist-info"))
    rows: list[dict[str, object]] = []
    for directory in sorted(candidates, key=lambda path: path.relative_to(root).as_posix()):
        try:
            directory_info = directory.lstat()
        except OSError as exc:
            raise StageCaptureError(
                DISTRIBUTION_CAPTURE_FAILED,
                "distribution_directory",
                "dist-info directory identity is readable",
                cause=exc,
            ) from exc
        if stat.S_ISLNK(directory_info.st_mode) or not stat.S_ISDIR(directory_info.st_mode):
            raise StageCaptureError(
                DISTRIBUTION_CAPTURE_FAILED,
                "distribution_directory",
                "dist-info entry is a non-symlink directory",
            )
        metadata = directory / "METADATA"
        try:
            metadata_info = metadata.lstat()
        except FileNotFoundError as exc:
            raise StageCaptureError(
                DISTRIBUTION_METADATA_MISSING,
                "distribution_metadata",
                f"{directory.name}/METADATA exists",
                cause=exc,
            ) from exc
        if stat.S_ISLNK(metadata_info.st_mode):
            raise StageCaptureError(
                DISTRIBUTION_METADATA_SYMLINK,
                "distribution_metadata",
                f"{directory.name}/METADATA is not a symlink",
            )
        raw, _ = _stable_read(
            metadata,
            error_code=DISTRIBUTION_METADATA_UNREADABLE,
            stage="distribution_metadata",
            assertion=f"{directory.name}/METADATA is stable and readable",
        )
        try:
            text = raw.decode("utf-8", errors="strict")
            message = Parser().parsestr(text)
            name, version = message.get("Name"), message.get("Version")
            if not name or not version:
                raise ValueError("Name and Version headers are required")
        except (UnicodeError, ValueError) as exc:
            raise StageCaptureError(
                DISTRIBUTION_METADATA_INVALID,
                "distribution_metadata_parse",
                f"{directory.name}/METADATA is strict UTF-8 with Name and Version",
                cause=exc,
            ) from exc
        row: dict[str, object] = {
            "directory_name": directory.name,
            "relative_directory": directory.relative_to(root).as_posix(),
            "metadata_sha256": sha256_bytes(raw),
            "name": name,
            "canonical_name": _canonical_name(name),
            "version": version,
        }
        for filename, key in (
            ("RECORD", "record"),
            ("INSTALLER", "installer"),
            ("REQUESTED", "requested"),
            ("direct_url.json", "direct_url"),
            ("entry_points.txt", "entry_points"),
            ("top_level.txt", "top_level"),
            ("WHEEL", "wheel"),
        ):
            row[key] = _optional_dist_file(directory, filename)
        rows.append(row)
    by_name: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_name.setdefault(cast(str, row["canonical_name"]), []).append(row)
    duplicate_report = [
        {
            "canonical_name": name,
            "versions": sorted({cast(str, row["version"]) for row in name_rows}),
            "directory_names": sorted(cast(str, row["directory_name"]) for row in name_rows),
        }
        for name, name_rows in sorted(by_name.items())
        if len(name_rows) > 1
    ]
    critical_projection = [
        {
            "canonical_name": name,
            "state": "present" if name in by_name else "absent",
            "identities": [
                {
                    "version": row["version"],
                    "metadata_sha256": row["metadata_sha256"],
                    "record": row["record"],
                    "wheel": row["wheel"],
                }
                for row in by_name.get(name, [])
            ],
        }
        for name in CRITICAL_DISTRIBUTIONS
    ]
    name_versions = [
        [row["canonical_name"], row["version"]]
        for row in sorted(rows, key=lambda item: cast(str, item["relative_directory"]))
    ]
    return {
        "schema_version": DISTRIBUTION_INVENTORY_SCHEMA_VERSION,
        "all_distribution_count": len(rows),
        "distributions": rows,
        "all_distribution_inventory_sha256": sha256_bytes(canonical_json_bytes(rows)),
        "canonical_name_version_sha256": sha256_bytes(canonical_json_bytes(name_versions)),
        "duplicate_name_report": duplicate_report,
        "critical_distribution_projection": critical_projection,
    }


def _tree_requires_full_hash(relative: str, size: int) -> bool:
    path = Path(relative)
    return (
        size <= TREE_FULL_HASH_THRESHOLD_BYTES
        or relative.startswith("conda-meta/")
        or ".dist-info/" in relative
        or relative.startswith("bin/")
        or bool(_SHARED_LIBRARY_RE.search(path.name))
    )


def capture_tree_identity(root: Path) -> dict[str, object]:
    """Capture a non-following, frozen-policy full-prefix tree identity."""

    structure_rows: list[dict[str, object]] = []
    content_rows: list[dict[str, object]] = []
    mtime_rows: list[list[object]] = []
    counts = {
        "entry": 0,
        "regular": 0,
        "regular_bytes": 0,
        "directory": 0,
        "symlink": 0,
        "other": 0,
    }
    stack = [root]
    try:
        while stack:
            directory = stack.pop()
            entries = sorted(os.scandir(directory), key=lambda row: row.name)
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                info = entry.stat(follow_symlinks=False)
                counts["entry"] += 1
                if stat.S_ISREG(info.st_mode):
                    kind = "regular"
                    counts["regular"] += 1
                    counts["regular_bytes"] += info.st_size
                elif stat.S_ISDIR(info.st_mode):
                    kind = "directory"
                    counts["directory"] += 1
                    stack.append(path)
                elif stat.S_ISLNK(info.st_mode):
                    kind = "symlink"
                    counts["symlink"] += 1
                else:
                    kind = "other"
                    counts["other"] += 1
                structure_rows.append(
                    {
                        "path": relative,
                        "kind": kind,
                        "mode": info.st_mode,
                        "size": info.st_size,
                        "mtime_ns": info.st_mtime_ns,
                        "link_target": os.readlink(path) if kind == "symlink" else "",
                    }
                )
                mtime_rows.append([relative, info.st_mtime_ns])
                if kind == "regular":
                    if _tree_requires_full_hash(relative, info.st_size):
                        content_rows.append(
                            {
                                "path": relative,
                                "policy": "full_sha256",
                                "size": info.st_size,
                                "sha256": _sha256_file(path),
                            }
                        )
                    else:
                        content_rows.append(
                            {
                                "path": relative,
                                "policy": "stat_identity",
                                "size": info.st_size,
                                "mode": info.st_mode,
                                "mtime_ns": info.st_mtime_ns,
                            }
                        )
    except OSError as exc:
        raise StageCaptureError(
            TREE_CAPTURE_FAILED,
            "tree_capture",
            "tree scan and frozen content policy complete without filesystem error",
            state="unreadable" if isinstance(exc, PermissionError) else "invalid",
            cause=exc,
        ) from exc
    structure_rows.sort(key=lambda row: cast(str, row["path"]))
    content_rows.sort(key=lambda row: cast(str, row["path"]))
    mtime_rows.sort(key=lambda row: cast(str, row[0]))
    return {
        "entry_count": counts["entry"],
        "regular_file_count": counts["regular"],
        "regular_file_bytes": counts["regular_bytes"],
        "directory_count": counts["directory"],
        "symlink_count": counts["symlink"],
        "other_count": counts["other"],
        "full_hash_threshold_bytes": TREE_FULL_HASH_THRESHOLD_BYTES,
        "tree_structure_digest": sha256_bytes(canonical_json_bytes(structure_rows)),
        "tree_content_identity_digest": sha256_bytes(canonical_json_bytes(content_rows)),
        "mtime_summary_digest": sha256_bytes(canonical_json_bytes(mtime_rows)),
    }


@dataclass(frozen=True, slots=True)
class CaptureFailure:
    code: str
    stage: str
    assertion: str
    object_id: str
    exception_class: str
    exception_message_digest: str
    details_digest: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "code": self.code,
            "stage": self.stage,
            "assertion": self.assertion,
            "object_id": self.object_id,
            "exception_class": self.exception_class,
            "exception_message_digest": self.exception_message_digest,
            "details_digest": self.details_digest,
        }


def _capture_failure(target: CaptureTarget, error: StageCaptureError) -> CaptureFailure:
    cause = error.cause
    exception_class = "none" if cause is None else type(cause).__name__
    message_digest = _EMPTY_SHA256 if cause is None else sha256_bytes(str(cause).encode())
    details = {
        "code": error.code,
        "stage": error.stage,
        "assertion": error.assertion,
        "object_id": target.object_id,
        "exception_class": exception_class,
        "exception_message_digest": message_digest,
    }
    return CaptureFailure(
        code=error.code,
        stage=error.stage,
        assertion=error.assertion,
        object_id=target.object_id,
        exception_class=exception_class,
        exception_message_digest=message_digest,
        details_digest=sha256_bytes(canonical_json_bytes(details)),
    )


@dataclass(frozen=True, slots=True)
class ProtectedObjectSnapshotV4:
    object_id: str
    state: str
    root_evidence: Mapping[str, object] | None
    launcher_evidence: LauncherEvidence | None
    python_probe_evidence: PythonProbeEvidence | None
    conda_meta_evidence: Mapping[str, object] | None
    distribution_evidence: Mapping[str, object] | None
    tree_evidence: Mapping[str, object] | None
    failure: CaptureFailure | None
    object_kind: str = "conda_environment"
    schema_version: str = SNAPSHOT_SCHEMA_VERSION

    def to_mapping(self, *, portable: bool = False) -> dict[str, object]:
        launcher = None
        if self.launcher_evidence is not None:
            launcher = (
                self.launcher_evidence.stable_mapping()
                if portable
                else self.launcher_evidence.evidence_mapping()
            )
        return {
            "schema_version": self.schema_version,
            "object_id": self.object_id,
            "state": self.state,
            "object_kind": self.object_kind,
            "root_evidence": self.root_evidence,
            "launcher_evidence": launcher,
            "python_probe_evidence": (
                None
                if self.python_probe_evidence is None
                else self.python_probe_evidence.to_mapping()
            ),
            "conda_meta_evidence": self.conda_meta_evidence,
            "distribution_evidence": self.distribution_evidence,
            "tree_evidence": self.tree_evidence,
            "failure": None if self.failure is None else self.failure.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class CaptureResultV2:
    snapshot: ProtectedObjectSnapshotV4
    diagnostic: Mapping[str, object]


def _diagnostic(
    target: CaptureTarget,
    snapshot: ProtectedObjectSnapshotV4,
) -> dict[str, object]:
    launcher = snapshot.launcher_evidence
    probe = snapshot.python_probe_evidence
    failure = snapshot.failure
    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "object_id": target.object_id,
        "capture_state": snapshot.state,
        "failure": None if failure is None else failure.to_mapping(),
        "launcher_classification": "not_captured" if launcher is None else launcher.launcher_kind,
        "launcher_relative_path": "bin/python",
        "symlink_depth": 0 if launcher is None else launcher.symlink_depth,
        "resolved_target_inside_root": (
            False if launcher is None else launcher.resolved_target_inside_root
        ),
        "python_probe_return_code": None if probe is None else probe.returncode,
        "python_probe_stdout_sha256": None if probe is None else probe.stdout_sha256,
        "python_probe_stderr_sha256": None if probe is None else probe.stderr_sha256,
        "portable_evidence_complete": True,
    }


def _root_evidence(target: CaptureTarget) -> dict[str, object]:
    try:
        info = target.root.lstat()
    except FileNotFoundError as exc:
        raise StageCaptureError(
            ROOT_ABSENT,
            "root_authentication",
            "protected environment root exists",
            state="absent",
            cause=exc,
        ) from exc
    except PermissionError as exc:
        raise StageCaptureError(
            ROOT_UNREADABLE,
            "root_authentication",
            "protected environment root is readable",
            state="unreadable",
            cause=exc,
        ) from exc
    if stat.S_ISLNK(info.st_mode):
        raise StageCaptureError(
            ROOT_SYMLINK_FORBIDDEN,
            "root_authentication",
            "protected environment root is not a symlink",
        )
    if not stat.S_ISDIR(info.st_mode):
        raise StageCaptureError(
            ROOT_NOT_DIRECTORY,
            "root_authentication",
            "protected environment root is a directory",
        )
    return {
        "root_kind": "directory",
        "root_mode": info.st_mode,
        "root_lstat_digest": sha256_bytes(
            canonical_json_bytes(
                {
                    "device": info.st_dev,
                    "inode": info.st_ino,
                    "mode": info.st_mode,
                    "ctime_ns": info.st_ctime_ns,
                }
            )
        ),
    }


def _validate_snapshot(snapshot: ProtectedObjectSnapshotV4) -> None:
    expected = {
        "schema_version",
        "object_id",
        "state",
        "object_kind",
        "root_evidence",
        "launcher_evidence",
        "python_probe_evidence",
        "conda_meta_evidence",
        "distribution_evidence",
        "tree_evidence",
        "failure",
    }
    if set(snapshot.to_mapping()) != expected:
        raise SnapshotSchemaError("snapshot top-level keyset differs from V4")
    if snapshot.schema_version != SNAPSHOT_SCHEMA_VERSION or snapshot.state not in SNAPSHOT_STATES:
        raise SnapshotSchemaError("snapshot version or state is invalid")
    parts = (
        snapshot.root_evidence,
        snapshot.launcher_evidence,
        snapshot.python_probe_evidence,
        snapshot.conda_meta_evidence,
        snapshot.distribution_evidence,
        snapshot.tree_evidence,
    )
    if snapshot.state == "present":
        if snapshot.failure is not None or any(part is None for part in parts):
            raise SnapshotSchemaError("present snapshot requires all evidence and failure=null")
    elif snapshot.failure is None or snapshot.failure.code not in FAILURE_CODES:
        raise SnapshotSchemaError("non-present snapshot requires complete registered failure")


def capture_protected_object_snapshot(
    target: CaptureTarget,
    *,
    command_runner: CommandRunner = _default_command_runner,
    tree_capturer: Callable[[Path], Mapping[str, object]] = capture_tree_identity,
    conda_capturer: Callable[[Path], Mapping[str, object]] = capture_conda_prefix_inventory,
    distribution_capturer: Callable[[Path], Mapping[str, object]] = (
        capture_python_distribution_inventory
    ),
) -> CaptureResultV2:
    """Capture a snapshot while retaining every successfully completed stage."""

    root: Mapping[str, object] | None = None
    launcher: LauncherEvidence | None = None
    probe: PythonProbeEvidence | None = None
    conda: Mapping[str, object] | None = None
    distributions: Mapping[str, object] | None = None
    tree: Mapping[str, object] | None = None
    stage = "root_authentication"
    pending_probe_error: StageCaptureError | None = None
    try:
        root = _root_evidence(target)
        stage = "python_launcher_resolution"
        launcher = resolve_environment_python_launcher(target)
        stage = "python_probe"
        try:
            probe = capture_python_probe(target, launcher, command_runner)
        except StageCaptureError as exc:
            if isinstance(exc.partial_evidence, PythonProbeEvidence):
                probe = exc.partial_evidence
            pending_probe_error = exc
        stage = "conda_meta_capture"
        conda = conda_capturer(target.root)
        stage = "distribution_capture"
        distributions = distribution_capturer(target.root)
        stage = "tree_capture"
        tree = tree_capturer(target.root)
        stage = "capture_final_launcher_identity"
        if launcher.identity_digest != resolve_environment_python_launcher(target).identity_digest:
            raise StageCaptureError(
                PYTHON_IDENTITY_DRIFT,
                stage,
                "launcher identity remains stable through complete capture",
            )
        if pending_probe_error is not None:
            raise pending_probe_error
        snapshot = ProtectedObjectSnapshotV4(
            object_id=target.object_id,
            state="present",
            root_evidence=root,
            launcher_evidence=launcher,
            python_probe_evidence=probe,
            conda_meta_evidence=conda,
            distribution_evidence=distributions,
            tree_evidence=tree,
            failure=None,
        )
        _validate_snapshot(snapshot)
    except StageCaptureError as exc:
        failure = _capture_failure(target, exc)
        snapshot = ProtectedObjectSnapshotV4(
            object_id=target.object_id,
            state=exc.state,
            root_evidence=root,
            launcher_evidence=launcher,
            python_probe_evidence=probe,
            conda_meta_evidence=conda,
            distribution_evidence=distributions,
            tree_evidence=tree,
            failure=failure,
        )
        _validate_snapshot(snapshot)
    except SnapshotSchemaError as exc:
        registered = StageCaptureError(
            SNAPSHOT_SCHEMA_FAILED,
            "snapshot_schema",
            "ProtectedObjectSnapshotV4 validates exactly",
            cause=exc,
        )
        failure = _capture_failure(target, registered)
        snapshot = ProtectedObjectSnapshotV4(
            target.object_id,
            "invalid",
            root,
            launcher,
            probe,
            conda,
            distributions,
            tree,
            failure,
        )
    except Exception as exc:
        registered = StageCaptureError(
            UNEXPECTED_CAPTURE_EXCEPTION,
            stage,
            "capture raises only registered stage failures",
            cause=exc,
        )
        failure = _capture_failure(target, registered)
        snapshot = ProtectedObjectSnapshotV4(
            target.object_id,
            "invalid",
            root,
            launcher,
            probe,
            conda,
            distributions,
            tree,
            failure,
        )
    return CaptureResultV2(snapshot=snapshot, diagnostic=_diagnostic(target, snapshot))


@dataclass(frozen=True, slots=True)
class ProtectedObjectIdentityProjectionV3:
    payload: Mapping[str, object]

    @classmethod
    def from_snapshot(
        cls, snapshot: ProtectedObjectSnapshotV4
    ) -> ProtectedObjectIdentityProjectionV3:
        conda = snapshot.conda_meta_evidence
        distributions = snapshot.distribution_evidence
        probe = snapshot.python_probe_evidence
        payload: dict[str, object] = {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "object_id": snapshot.object_id,
            "state": snapshot.state,
            "root_kind_identity": snapshot.root_evidence,
            "python_launcher_stable_identity": (
                None
                if snapshot.launcher_evidence is None
                else snapshot.launcher_evidence.stable_mapping()
            ),
            "python_identity": (
                None
                if probe is None
                else {"version": probe.version, "implementation": probe.implementation}
            ),
            "conda_history_sha256": None if conda is None else conda["history_sha256"],
            "conda_raw_inventory_sha256": (
                None if conda is None else conda["raw_record_set_sha256"]
            ),
            "conda_normalized_inventory_sha256": (
                None if conda is None else conda["normalized_record_set_sha256"]
            ),
            "conda_record_count": None if conda is None else conda["record_count"],
            "conda_record_filename_set_sha256": (
                None if conda is None else conda["record_filename_set_sha256"]
            ),
            "distribution_inventory_sha256": (
                None
                if distributions is None
                else distributions["all_distribution_inventory_sha256"]
            ),
            "distribution_count": (
                None if distributions is None else distributions["all_distribution_count"]
            ),
            "critical_distribution_projection": (
                None if distributions is None else distributions["critical_distribution_projection"]
            ),
            "tree_identity": snapshot.tree_evidence,
        }
        return cls(payload)

    def to_mapping(self) -> dict[str, object]:
        return dict(self.payload)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload)

    @property
    def sha256(self) -> str:
        return sha256_bytes(self.canonical_bytes())


@dataclass(frozen=True, slots=True)
class ProtectedObjectObservationReceiptV4:
    observation_phase: str
    attempt_id: str
    observed_at_ns: int
    observer_pid: int
    snapshot: ProtectedObjectSnapshotV4
    diagnostic: Mapping[str, object]
    projection: ProtectedObjectIdentityProjectionV3
    projection_sha256: str
    schema_version: str = OBSERVATION_SCHEMA_VERSION

    def to_mapping(self, *, portable: bool = False) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "observation_phase": self.observation_phase,
            "attempt_id": self.attempt_id,
            "observed_at_ns": self.observed_at_ns,
            "observer_pid": self.observer_pid,
            "snapshot": self.snapshot.to_mapping(portable=portable),
            "diagnostic": dict(self.diagnostic),
            "stable_projection": self.projection.to_mapping(),
            "stable_projection_sha256": self.projection_sha256,
        }


def build_observation_receipt(
    capture: CaptureResultV2,
    *,
    observation_phase: str,
    attempt_id: str,
    observed_at_ns: int,
    observer_pid: int,
) -> ProtectedObjectObservationReceiptV4:
    if observation_phase not in OBSERVATION_PHASES or not attempt_id:
        raise SnapshotSchemaError("observation metadata violates V4 schema")
    projection = ProtectedObjectIdentityProjectionV3.from_snapshot(capture.snapshot)
    return ProtectedObjectObservationReceiptV4(
        observation_phase,
        attempt_id,
        observed_at_ns,
        observer_pid,
        capture.snapshot,
        capture.diagnostic,
        projection,
        projection.sha256,
    )


@dataclass(frozen=True, slots=True)
class ProtectedObjectComparisonReceiptV4:
    object_id: str
    schema_keyset_equal: bool
    projection_keyset_equal: bool
    projection_bytes_equal: bool
    projection_sha256_equal: bool
    launcher_identity_equal: bool
    python_identity_equal: bool
    conda_history_equal: bool
    conda_raw_inventory_equal: bool
    conda_normalized_inventory_equal: bool
    distribution_inventory_equal: bool
    tree_identity_equal: bool
    before_projection_sha256: str
    after_projection_sha256: str
    failure_code: str
    schema_version: str = COMPARISON_SCHEMA_VERSION

    @property
    def passed(self) -> bool:
        return self.failure_code == NO_FAILURE and all(
            (
                self.schema_keyset_equal,
                self.projection_keyset_equal,
                self.projection_bytes_equal,
                self.projection_sha256_equal,
                self.launcher_identity_equal,
                self.python_identity_equal,
                self.conda_history_equal,
                self.conda_raw_inventory_equal,
                self.conda_normalized_inventory_equal,
                self.distribution_inventory_equal,
                self.tree_identity_equal,
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
            "python_identity_equal": self.python_identity_equal,
            "conda_history_equal": self.conda_history_equal,
            "conda_raw_inventory_equal": self.conda_raw_inventory_equal,
            "conda_normalized_inventory_equal": self.conda_normalized_inventory_equal,
            "distribution_inventory_equal": self.distribution_inventory_equal,
            "tree_identity_equal": self.tree_identity_equal,
            "before_projection_sha256": self.before_projection_sha256,
            "after_projection_sha256": self.after_projection_sha256,
            "failure_code": self.failure_code,
        }


def compare_observations(
    before: ProtectedObjectObservationReceiptV4,
    after: ProtectedObjectObservationReceiptV4,
) -> ProtectedObjectComparisonReceiptV4:
    if not isinstance(before, ProtectedObjectObservationReceiptV4) or not isinstance(
        after, ProtectedObjectObservationReceiptV4
    ):
        raise SnapshotSchemaError("typed observations are required; compare projections only")
    if before.snapshot.object_id != after.snapshot.object_id:
        raise SnapshotSchemaError("observation object IDs differ")
    left, right = before.projection.to_mapping(), after.projection.to_mapping()
    schema_equal = set(before.snapshot.to_mapping()) == set(after.snapshot.to_mapping())
    projection_keys_equal = set(left) == set(right)
    checks = {
        "launcher": left["python_launcher_stable_identity"]
        == right["python_launcher_stable_identity"],
        "python": left["python_identity"] == right["python_identity"],
        "history": left["conda_history_sha256"] == right["conda_history_sha256"],
        "raw": left["conda_raw_inventory_sha256"] == right["conda_raw_inventory_sha256"],
        "normalized": left["conda_normalized_inventory_sha256"]
        == right["conda_normalized_inventory_sha256"],
        "distribution": left["distribution_inventory_sha256"]
        == right["distribution_inventory_sha256"],
        "tree": left["tree_identity"] == right["tree_identity"],
    }
    bytes_equal = before.projection.canonical_bytes() == after.projection.canonical_bytes()
    sha_equal = before.projection_sha256 == after.projection_sha256
    present = before.snapshot.state == after.snapshot.state == "present"
    no_failures = before.snapshot.failure is None and after.snapshot.failure is None
    passed = (
        schema_equal
        and projection_keys_equal
        and bytes_equal
        and sha_equal
        and present
        and no_failures
        and all(checks.values())
    )
    return ProtectedObjectComparisonReceiptV4(
        object_id=before.snapshot.object_id,
        schema_keyset_equal=schema_equal,
        projection_keyset_equal=projection_keys_equal,
        projection_bytes_equal=bytes_equal,
        projection_sha256_equal=sha_equal,
        launcher_identity_equal=checks["launcher"],
        python_identity_equal=checks["python"],
        conda_history_equal=checks["history"],
        conda_raw_inventory_equal=checks["raw"],
        conda_normalized_inventory_equal=checks["normalized"],
        distribution_inventory_equal=checks["distribution"],
        tree_identity_equal=checks["tree"],
        before_projection_sha256=before.projection_sha256,
        after_projection_sha256=after.projection_sha256,
        failure_code=NO_FAILURE if passed else "PROTECTED_SNAPSHOT_CONTENT_DRIFT",
    )


@dataclass(frozen=True, slots=True)
class MeasurementQualificationReceiptV3:
    attempt_id: str
    helper_source_sha256: str
    object_results: tuple[Mapping[str, object], ...]
    all_passed: bool
    server_write_performed_between_captures: bool = False
    package_manager_cli_invocations: int = 0
    schema_version: str = QUALIFICATION_SCHEMA_VERSION

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "helper_source_sha256": self.helper_source_sha256,
            "server_write_performed_between_captures": self.server_write_performed_between_captures,
            "package_manager_cli_invocations": self.package_manager_cli_invocations,
            "all_passed": self.all_passed,
            "object_results": [dict(row) for row in self.object_results],
        }


def qualify_measurement_system(
    targets: Sequence[CaptureTarget],
    *,
    attempt_id: str,
    helper_source_sha256: str,
    command_runner: CommandRunner = _default_command_runner,
    clock_ns: Callable[[], int] = time.time_ns,
    observer_pid: int | None = None,
) -> MeasurementQualificationReceiptV3:
    ids = [target.object_id for target in targets]
    if len(ids) != len(set(ids)) or set(ids) != U5_PROTECTED_OBJECT_IDS:
        raise SnapshotSchemaError("qualification targets must equal the frozen U5 set")
    _require_sha256(helper_source_sha256, "helper_source_sha256")
    pid = os.getpid() if observer_pid is None else observer_pid
    rows: list[Mapping[str, object]] = []
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
        launcher = capture_a.snapshot.launcher_evidence
        probe = capture_a.snapshot.python_probe_evidence
        conda = capture_a.snapshot.conda_meta_evidence
        distributions = capture_a.snapshot.distribution_evidence
        tree = capture_a.snapshot.tree_evidence
        failure_a = capture_a.snapshot.failure
        failure_b = capture_b.snapshot.failure
        passed = comparison.passed
        rows.append(
            {
                "object_id": target.object_id,
                "snapshot_a_state": capture_a.snapshot.state,
                "snapshot_b_state": capture_b.snapshot.state,
                "failure_a": None if failure_a is None else failure_a.to_mapping(),
                "failure_b": None if failure_b is None else failure_b.to_mapping(),
                "launcher_kind": None if launcher is None else launcher.launcher_kind,
                "symlink_depth": None if launcher is None else launcher.symlink_depth,
                "symlink_chain_relative_targets": (
                    None if launcher is None else list(launcher.symlink_chain_relative_targets)
                ),
                "resolved_executable_relative_path": (
                    None if launcher is None else launcher.resolved_executable_relative_path
                ),
                "resolved_target_inside_root": (
                    False if launcher is None else launcher.resolved_target_inside_root
                ),
                "python_version": None if probe is None else probe.version,
                "python_implementation": None if probe is None else probe.implementation,
                "conda_record_count": None if conda is None else conda["record_count"],
                "conda_history_sha256": None if conda is None else conda["history_sha256"],
                "conda_raw_inventory_sha256": (
                    None if conda is None else conda["raw_record_set_sha256"]
                ),
                "conda_normalized_inventory_sha256": (
                    None if conda is None else conda["normalized_record_set_sha256"]
                ),
                "distribution_count": (
                    None if distributions is None else distributions["all_distribution_count"]
                ),
                "distribution_inventory_sha256": (
                    None
                    if distributions is None
                    else distributions["all_distribution_inventory_sha256"]
                ),
                "tree_identity": tree,
                "snapshot_a_projection_sha256": observation_a.projection_sha256,
                "snapshot_b_projection_sha256": observation_b.projection_sha256,
                "comparison": comparison.to_mapping(),
                "qualification_result": "passed" if passed else "failed",
            }
        )
    return MeasurementQualificationReceiptV3(
        attempt_id=attempt_id,
        helper_source_sha256=helper_source_sha256,
        object_results=tuple(rows),
        all_passed=all(row["qualification_result"] == "passed" for row in rows),
    )
