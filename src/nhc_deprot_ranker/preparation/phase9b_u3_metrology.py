"""Qualified protected-object metrology for the independent Phase 9B-U3 attempt.

The module is standard-library-only and outside the runner source closure.  It
contains the one production snapshot helper used for qualification, protected
before, and protected after.  Snapshot identity, observation metadata, pairwise
comparison, and terminal failure are deliberately separate types.
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

SNAPSHOT_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-snapshot-v2"
PROJECTION_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-identity-projection-v1"
OBSERVATION_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-observation-receipt-v1"
COMPARISON_SCHEMA_VERSION: Final = "nhc-phase9b-protected-object-comparison-v1"
QUALIFICATION_SCHEMA_VERSION: Final = "nhc-phase9b-measurement-qualification-receipt-v1"
TERMINAL_SCHEMA_VERSION: Final = "nhc-phase9b-unified-v003-terminal-receipt-v1"
TARGET_LIFECYCLE_SCHEMA_VERSION: Final = "nhc-phase9b-target-environment-lifecycle-receipt-v1"

SCHEMA_ASYMMETRY: Final = "PROTECTED_SNAPSHOT_SCHEMA_ASYMMETRY"
CONTENT_DRIFT: Final = "PROTECTED_SNAPSHOT_CONTENT_DRIFT"
CAPTURE_FAILURE: Final = "PROTECTED_SNAPSHOT_CAPTURE_FAILURE"
EVIDENCE_INCOMPLETE: Final = "PROTECTED_SNAPSHOT_EVIDENCE_INCOMPLETE"
NO_FAILURE: Final = "none"

SNAPSHOT_STATES: Final = frozenset({"present", "absent", "unreadable", "invalid"})
OBJECT_KINDS: Final = frozenset({"conda_environment"})
OBSERVATION_PHASES: Final = frozenset(
    {"qualification_a", "qualification_b", "protected_before", "protected_after"}
)
TERMINAL_STATUSES: Final = frozenset(
    {
        "validated",
        "failed_before_environment_creation",
        "failed_incomplete_environment",
        "rejected_environment",
        "indeterminate_evidence_failure",
    }
)
U3_PROTECTED_OBJECT_IDS: Final = frozenset(
    {
        "project_mlff",
        "project_aimnet2",
        "project_gpupyscf",
        "shared_molecular",
        "phase9b_unified_v001_env",
        "phase9b_unified_v002_env",
    }
)

SNAPSHOT_KEYS: Final = frozenset(
    {
        "schema_version",
        "object_id",
        "state",
        "object_kind",
        "python_identity",
        "conda_history_sha256",
        "conda_explicit_sha256",
        "pip_freeze_sha256",
        "critical_distribution_identities",
        "filesystem_entry_count",
        "regular_file_count",
        "regular_file_bytes",
        "tree_digest",
        "mtime_summary_digest",
    }
)
PYTHON_IDENTITY_KEYS: Final = frozenset(
    {"executable_sha256", "executable_bytes", "version", "implementation"}
)
DISTRIBUTION_IDENTITY_KEYS: Final = frozenset(
    {"distribution", "state", "version", "metadata_sha256", "record_sha256"}
)
PROJECTION_KEYS: Final = frozenset(
    (SNAPSHOT_KEYS - {"schema_version"}) | {"projection_schema_version"}
)
OBSERVATION_KEYS: Final = frozenset(
    {
        "schema_version",
        "observation_phase",
        "observed_at_ns",
        "observer_pid",
        "attempt_id",
        "warnings",
        "snapshot",
        "projection",
        "projection_sha256",
    }
)

CRITICAL_DISTRIBUTIONS: Final = (
    "pip",
    "setuptools",
    "numpy",
    "scipy",
    "h5py",
    "torch",
    "ase",
    "aimnet",
    "pyscf",
    "geometric",
    "pyscf-dispersion",
    "networkx",
    "six",
    "nvalchemi-toolkit-ops",
    "nvalchemi-toolkit",
)

_SENTINEL_ABSENT: Final = "absent"
_SENTINEL_UNREADABLE: Final = "unreadable"
_SENTINEL_INVALID: Final = "invalid"
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")


class U3MetrologyError(RuntimeError):
    """The U3 measurement contract could not be proved."""


class SnapshotSchemaError(U3MetrologyError):
    """A snapshot, projection, observation, or terminal payload is invalid."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CAPTURE_FAILURE,
        assertion: str = "protected snapshot schema is exact",
        object_ids: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.assertion = assertion
        self.object_ids = tuple(object_ids)


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


CommandRunner = Callable[[Sequence[str], Mapping[str, str]], CommandResult]


@dataclass(frozen=True, slots=True)
class CaptureTarget:
    object_id: str
    root: Path
    conda_executable: Path
    object_kind: str = "conda_environment"

    def __post_init__(self) -> None:
        if not self.object_id or self.object_kind not in OBJECT_KINDS:
            raise ValueError("capture target identity is invalid")
        if not self.root.is_absolute() or not self.conda_executable.is_absolute():
            raise ValueError("capture paths must be absolute")


@dataclass(frozen=True, slots=True)
class ProtectedObjectSnapshotV2:
    object_id: str
    state: str
    object_kind: str
    python_identity: Mapping[str, object]
    conda_history_sha256: str
    conda_explicit_sha256: str
    pip_freeze_sha256: str
    critical_distribution_identities: tuple[Mapping[str, object], ...]
    filesystem_entry_count: int
    regular_file_count: int
    regular_file_bytes: int
    tree_digest: str
    mtime_summary_digest: str
    schema_version: str = SNAPSHOT_SCHEMA_VERSION

    def to_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "object_id": self.object_id,
            "state": self.state,
            "object_kind": self.object_kind,
            "python_identity": dict(self.python_identity),
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
        validate_snapshot_mapping(payload)
        return payload


@dataclass(frozen=True, slots=True)
class ProtectedObjectIdentityProjectionV1:
    payload: Mapping[str, object]

    def to_mapping(self) -> dict[str, object]:
        result = _deep_copy_mapping(self.payload)
        validate_projection_mapping(result)
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_mapping())

    def sha256(self) -> str:
        return sha256_bytes(self.canonical_bytes())


@dataclass(frozen=True, slots=True)
class ProtectedObjectObservationReceiptV1:
    observation_phase: str
    observed_at_ns: int
    observer_pid: int
    attempt_id: str
    warnings: tuple[str, ...]
    snapshot: ProtectedObjectSnapshotV2
    projection: ProtectedObjectIdentityProjectionV1
    projection_sha256: str
    schema_version: str = OBSERVATION_SCHEMA_VERSION

    def to_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "observation_phase": self.observation_phase,
            "observed_at_ns": self.observed_at_ns,
            "observer_pid": self.observer_pid,
            "attempt_id": self.attempt_id,
            "warnings": list(self.warnings),
            "snapshot": self.snapshot.to_mapping(),
            "projection": self.projection.to_mapping(),
            "projection_sha256": self.projection_sha256,
        }
        validate_observation_mapping(payload)
        return payload


@dataclass(frozen=True, slots=True)
class ProtectedObjectComparisonV1:
    object_id: str
    schema_keyset_equal: bool
    projection_keyset_equal: bool
    projection_bytes_equal: bool
    projection_sha256_equal: bool
    before_projection_sha256: str
    after_projection_sha256: str
    failure_code: str
    failure_assertion: str
    details_digest: str
    schema_version: str = COMPARISON_SCHEMA_VERSION

    @property
    def passed(self) -> bool:
        return (
            self.failure_code == NO_FAILURE
            and self.schema_keyset_equal
            and self.projection_keyset_equal
            and self.projection_bytes_equal
            and self.projection_sha256_equal
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_id": self.object_id,
            "schema_keyset_equal": self.schema_keyset_equal,
            "projection_keyset_equal": self.projection_keyset_equal,
            "projection_bytes_equal": self.projection_bytes_equal,
            "projection_sha256_equal": self.projection_sha256_equal,
            "before_projection_sha256": self.before_projection_sha256,
            "after_projection_sha256": self.after_projection_sha256,
            "failure_code": self.failure_code,
            "failure_assertion": self.failure_assertion,
            "details_digest": self.details_digest,
        }


@dataclass(frozen=True, slots=True)
class QualificationObjectResultV1:
    object_id: str
    snapshot_a_projection_sha256: str
    snapshot_b_projection_sha256: str
    schema_keyset_equal: bool
    projection_keyset_equal: bool
    projection_bytes_equal: bool
    projection_sha256_equal: bool
    qualification_result: str
    comparison: ProtectedObjectComparisonV1

    def to_mapping(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "snapshot_a_projection_sha256": self.snapshot_a_projection_sha256,
            "snapshot_b_projection_sha256": self.snapshot_b_projection_sha256,
            "schema_keyset_equal": self.schema_keyset_equal,
            "projection_keyset_equal": self.projection_keyset_equal,
            "projection_bytes_equal": self.projection_bytes_equal,
            "projection_sha256_equal": self.projection_sha256_equal,
            "qualification_result": self.qualification_result,
            "comparison": self.comparison.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class MeasurementQualificationReceiptV1:
    attempt_id: str
    helper_source_sha256: str
    object_results: tuple[QualificationObjectResultV1, ...]
    all_passed: bool
    server_write_performed_between_captures: bool = False
    schema_version: str = QUALIFICATION_SCHEMA_VERSION

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "helper_source_sha256": self.helper_source_sha256,
            "object_results": [row.to_mapping() for row in self.object_results],
            "all_passed": self.all_passed,
            "server_write_performed_between_captures": (
                self.server_write_performed_between_captures
            ),
        }


@dataclass(frozen=True, slots=True)
class TerminalFailureV1:
    code: str
    stage: str
    assertion: str
    object_ids: tuple[str, ...]
    details_digest: str

    def __post_init__(self) -> None:
        if not self.code or self.code == NO_FAILURE:
            raise SnapshotSchemaError("terminal failure code must be non-empty")
        if not self.stage or not self.assertion:
            raise SnapshotSchemaError("terminal failure stage and assertion must be non-empty")
        _require_sha256(self.details_digest, label="terminal failure details_digest")

    def to_mapping(self) -> dict[str, object]:
        return {
            "code": self.code,
            "stage": self.stage,
            "assertion": self.assertion,
            "object_ids": list(self.object_ids),
            "details_digest": self.details_digest,
        }


@dataclass(frozen=True, slots=True)
class TerminalReceiptV1:
    terminal_status: str
    failure: TerminalFailureV1 | None
    schema_version: str = TERMINAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.terminal_status not in TERMINAL_STATUSES:
            raise SnapshotSchemaError("terminal status is invalid")
        if self.terminal_status == "validated" and self.failure is not None:
            raise SnapshotSchemaError("successful terminal receipt must have failure=null")
        if self.terminal_status != "validated" and self.failure is None:
            raise SnapshotSchemaError("failed terminal receipt requires structured failure")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "terminal_status": self.terminal_status,
            "failure": None if self.failure is None else self.failure.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class TargetEnvironmentLifecycleReceiptV1:
    initial_state: str
    post_build_state: str
    post_capability_state: str
    post_build_projection_sha256: str
    post_capability_projection_sha256: str
    post_build_post_capability_equal: bool
    schema_version: str = TARGET_LIFECYCLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.initial_state != "absent":
            raise SnapshotSchemaError("target lifecycle initial state must be absent")
        if self.post_build_state != "present" or self.post_capability_state != "present":
            raise SnapshotSchemaError("target lifecycle built states must be present")
        _require_sha256(
            self.post_build_projection_sha256,
            label="target lifecycle post-build projection SHA256",
        )
        _require_sha256(
            self.post_capability_projection_sha256,
            label="target lifecycle post-capability projection SHA256",
        )
        expected_equal = self.post_build_projection_sha256 == self.post_capability_projection_sha256
        if self.post_build_post_capability_equal is not expected_equal:
            raise SnapshotSchemaError("target lifecycle equality flag is inconsistent")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "initial_state": self.initial_state,
            "post_build_state": self.post_build_state,
            "post_capability_state": self.post_capability_state,
            "post_build_projection_sha256": self.post_build_projection_sha256,
            "post_capability_projection_sha256": (self.post_capability_projection_sha256),
            "post_build_post_capability_equal": (self.post_build_post_capability_equal),
        }


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


def _deep_copy_mapping(payload: Mapping[str, object]) -> dict[str, object]:
    value = json.loads(canonical_json_bytes(payload))
    if not isinstance(value, dict):  # pragma: no cover - canonical object invariant
        raise SnapshotSchemaError("canonical payload is not an object")
    return cast(dict[str, object], value)


def _canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _require_exact_keys(
    payload: Mapping[str, object], expected: frozenset[str], *, label: str
) -> None:
    actual = frozenset(payload)
    if actual != expected:
        raise SnapshotSchemaError(
            f"{label} key set mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _require_no_null(value: object, *, label: str) -> None:
    if value is None:
        raise SnapshotSchemaError(f"{label} may not be null")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _require_no_null(item, label=f"{label}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _require_no_null(item, label=f"{label}[{index}]")


def _require_sha256(value: object, *, label: str, allow_sentinel: bool = False) -> str:
    if not isinstance(value, str):
        raise SnapshotSchemaError(f"{label} must be a string")
    if allow_sentinel and value in {
        _SENTINEL_ABSENT,
        _SENTINEL_UNREADABLE,
        _SENTINEL_INVALID,
    }:
        return value
    if not _SHA256_RE.fullmatch(value):
        raise SnapshotSchemaError(f"{label} must be a lowercase SHA256")
    return value


def validate_snapshot_mapping(payload: Mapping[str, object]) -> None:
    _require_exact_keys(payload, SNAPSHOT_KEYS, label="protected snapshot")
    _require_no_null(payload, label="protected snapshot")
    if payload["schema_version"] != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotSchemaError("protected snapshot schema version drifted")
    if not isinstance(payload["object_id"], str) or not payload["object_id"]:
        raise SnapshotSchemaError("protected snapshot object_id is invalid")
    if payload["state"] not in SNAPSHOT_STATES:
        raise SnapshotSchemaError("protected snapshot state is invalid")
    if payload["object_kind"] not in OBJECT_KINDS:
        raise SnapshotSchemaError("protected snapshot object_kind is invalid")
    python_identity = payload["python_identity"]
    if not isinstance(python_identity, Mapping):
        raise SnapshotSchemaError("python_identity must be an object")
    _require_exact_keys(python_identity, PYTHON_IDENTITY_KEYS, label="python_identity")
    if not isinstance(python_identity["executable_bytes"], int):
        raise SnapshotSchemaError("python_identity.executable_bytes must be an integer")
    for key in ("executable_sha256",):
        _require_sha256(python_identity[key], label=f"python_identity.{key}", allow_sentinel=True)
    for key in ("version", "implementation"):
        if not isinstance(python_identity[key], str) or not python_identity[key]:
            raise SnapshotSchemaError(f"python_identity.{key} must be non-empty")
    for key in (
        "conda_history_sha256",
        "conda_explicit_sha256",
        "pip_freeze_sha256",
        "tree_digest",
        "mtime_summary_digest",
    ):
        _require_sha256(payload[key], label=key, allow_sentinel=True)
    rows = payload["critical_distribution_identities"]
    if not isinstance(rows, list):
        raise SnapshotSchemaError("critical_distribution_identities must be a list")
    names: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise SnapshotSchemaError("critical distribution identity must be an object")
        _require_exact_keys(
            row, DISTRIBUTION_IDENTITY_KEYS, label=f"critical_distribution_identities[{index}]"
        )
        if row["state"] not in SNAPSHOT_STATES:
            raise SnapshotSchemaError("critical distribution state is invalid")
        if not isinstance(row["distribution"], str) or not row["distribution"]:
            raise SnapshotSchemaError("critical distribution name is invalid")
        names.append(row["distribution"])
        for key in ("version",):
            if not isinstance(row[key], str) or not row[key]:
                raise SnapshotSchemaError("critical distribution version sentinel is invalid")
        for key in ("metadata_sha256", "record_sha256"):
            _require_sha256(row[key], label=key, allow_sentinel=True)
    if names != sorted(names) or len(names) != len(set(names)):
        raise SnapshotSchemaError("critical distribution identities must be unique and sorted")
    for key in (
        "filesystem_entry_count",
        "regular_file_count",
        "regular_file_bytes",
    ):
        if not isinstance(payload[key], int) or cast(int, payload[key]) < 0:
            raise SnapshotSchemaError(f"{key} must be a non-negative integer")


def snapshot_from_mapping(payload: Mapping[str, object]) -> ProtectedObjectSnapshotV2:
    validate_snapshot_mapping(payload)
    python_identity = cast(Mapping[str, object], payload["python_identity"])
    rows = cast(list[Mapping[str, object]], payload["critical_distribution_identities"])
    return ProtectedObjectSnapshotV2(
        object_id=cast(str, payload["object_id"]),
        state=cast(str, payload["state"]),
        object_kind=cast(str, payload["object_kind"]),
        python_identity=dict(python_identity),
        conda_history_sha256=cast(str, payload["conda_history_sha256"]),
        conda_explicit_sha256=cast(str, payload["conda_explicit_sha256"]),
        pip_freeze_sha256=cast(str, payload["pip_freeze_sha256"]),
        critical_distribution_identities=tuple(dict(row) for row in rows),
        filesystem_entry_count=cast(int, payload["filesystem_entry_count"]),
        regular_file_count=cast(int, payload["regular_file_count"]),
        regular_file_bytes=cast(int, payload["regular_file_bytes"]),
        tree_digest=cast(str, payload["tree_digest"]),
        mtime_summary_digest=cast(str, payload["mtime_summary_digest"]),
    )


def build_stable_projection(
    snapshot: ProtectedObjectSnapshotV2,
) -> ProtectedObjectIdentityProjectionV1:
    stable = snapshot.to_mapping()
    stable.pop("schema_version")
    stable["projection_schema_version"] = PROJECTION_SCHEMA_VERSION
    return ProtectedObjectIdentityProjectionV1(stable)


def validate_projection_mapping(payload: Mapping[str, object]) -> None:
    _require_exact_keys(payload, PROJECTION_KEYS, label="protected projection")
    _require_no_null(payload, label="protected projection")
    if payload["projection_schema_version"] != PROJECTION_SCHEMA_VERSION:
        raise SnapshotSchemaError("protected projection schema version drifted")
    snapshot_payload = dict(payload)
    snapshot_payload.pop("projection_schema_version")
    snapshot_payload["schema_version"] = SNAPSHOT_SCHEMA_VERSION
    validate_snapshot_mapping(snapshot_payload)


def build_observation_receipt(
    snapshot: ProtectedObjectSnapshotV2,
    *,
    observation_phase: str,
    attempt_id: str,
    observed_at_ns: int | None = None,
    observer_pid: int | None = None,
    warnings: Sequence[str] = (),
) -> ProtectedObjectObservationReceiptV1:
    snapshot.to_mapping()
    if observation_phase not in OBSERVATION_PHASES:
        raise SnapshotSchemaError("observation phase is invalid")
    if not attempt_id:
        raise SnapshotSchemaError("observation attempt_id is empty")
    if any(not isinstance(row, str) for row in warnings):
        raise SnapshotSchemaError("observation warnings must be strings")
    projection = build_stable_projection(snapshot)
    return ProtectedObjectObservationReceiptV1(
        observation_phase=observation_phase,
        observed_at_ns=time.time_ns() if observed_at_ns is None else observed_at_ns,
        observer_pid=os.getpid() if observer_pid is None else observer_pid,
        attempt_id=attempt_id,
        warnings=tuple(warnings),
        snapshot=snapshot,
        projection=projection,
        projection_sha256=projection.sha256(),
    )


def build_observation_receipt_from_mapping(
    snapshot_payload: Mapping[str, object],
    **metadata: object,
) -> ProtectedObjectObservationReceiptV1:
    snapshot = snapshot_from_mapping(snapshot_payload)
    return build_observation_receipt(
        snapshot,
        observation_phase=cast(str, metadata["observation_phase"]),
        attempt_id=cast(str, metadata["attempt_id"]),
        observed_at_ns=cast(int | None, metadata.get("observed_at_ns")),
        observer_pid=cast(int | None, metadata.get("observer_pid")),
        warnings=cast(Sequence[str], metadata.get("warnings", ())),
    )


def validate_observation_mapping(payload: Mapping[str, object]) -> None:
    _require_exact_keys(payload, OBSERVATION_KEYS, label="protected observation")
    _require_no_null(payload, label="protected observation")
    if payload["schema_version"] != OBSERVATION_SCHEMA_VERSION:
        raise SnapshotSchemaError("protected observation schema version drifted")
    if payload["observation_phase"] not in OBSERVATION_PHASES:
        raise SnapshotSchemaError("protected observation phase is invalid")
    if not isinstance(payload["observed_at_ns"], int) or not isinstance(
        payload["observer_pid"], int
    ):
        raise SnapshotSchemaError("protected observation process metadata is invalid")
    if not isinstance(payload["attempt_id"], str) or not payload["attempt_id"]:
        raise SnapshotSchemaError("protected observation attempt_id is invalid")
    if not isinstance(payload["warnings"], list):
        raise SnapshotSchemaError("protected observation warnings must be a list")
    snapshot_payload = payload["snapshot"]
    projection_payload = payload["projection"]
    if not isinstance(snapshot_payload, Mapping) or not isinstance(projection_payload, Mapping):
        raise SnapshotSchemaError("protected observation nested payload is invalid")
    snapshot = snapshot_from_mapping(snapshot_payload)
    validate_projection_mapping(projection_payload)
    expected = build_stable_projection(snapshot)
    if canonical_json_bytes(projection_payload) != expected.canonical_bytes():
        raise SnapshotSchemaError("observation projection was enriched or rebuilt differently")
    if payload["projection_sha256"] != expected.sha256():
        raise SnapshotSchemaError("observation projection SHA256 drifted")


def _diagnostic(
    *,
    object_id: str,
    schema_equal: bool,
    projection_keyset_equal: bool,
    bytes_equal: bool,
    sha_equal: bool,
    before_sha: str,
    after_sha: str,
    code: str,
    assertion: str,
    details: Mapping[str, object],
) -> ProtectedObjectComparisonV1:
    return ProtectedObjectComparisonV1(
        object_id=object_id,
        schema_keyset_equal=schema_equal,
        projection_keyset_equal=projection_keyset_equal,
        projection_bytes_equal=bytes_equal,
        projection_sha256_equal=sha_equal,
        before_projection_sha256=before_sha,
        after_projection_sha256=after_sha,
        failure_code=code,
        failure_assertion=assertion,
        details_digest=sha256_bytes(canonical_json_bytes(details)),
    )


def diagnose_snapshot_pair(
    before: Mapping[str, object], after: Mapping[str, object]
) -> ProtectedObjectComparisonV1:
    before_id = before.get("object_id")
    after_id = after.get("object_id")
    object_id = (
        before_id if isinstance(before_id, str) and before_id else str(after_id or "unknown")
    )
    top_equal = set(before) == set(after)
    if not top_equal:
        return _diagnostic(
            object_id=object_id,
            schema_equal=False,
            projection_keyset_equal=False,
            bytes_equal=False,
            sha_equal=False,
            before_sha=_SENTINEL_INVALID,
            after_sha=_SENTINEL_INVALID,
            code=SCHEMA_ASYMMETRY,
            assertion="protected_before_snapshot_keys == protected_after_snapshot_keys",
            details={"before_keys": sorted(before), "after_keys": sorted(after)},
        )
    try:
        left = snapshot_from_mapping(before)
        right = snapshot_from_mapping(after)
        if left.object_id != right.object_id:
            raise SnapshotSchemaError("protected snapshot object ids differ")
        left_projection = build_stable_projection(left)
        right_projection = build_stable_projection(right)
        left_payload = left_projection.to_mapping()
        right_payload = right_projection.to_mapping()
    except SnapshotSchemaError as exc:
        return _diagnostic(
            object_id=object_id,
            schema_equal=True,
            projection_keyset_equal=False,
            bytes_equal=False,
            sha_equal=False,
            before_sha=_SENTINEL_INVALID,
            after_sha=_SENTINEL_INVALID,
            code=CAPTURE_FAILURE,
            assertion=exc.assertion,
            details={"error": str(exc)},
        )
    keysets_equal = set(left_payload) == set(right_payload) == set(PROJECTION_KEYS)
    left_bytes = left_projection.canonical_bytes()
    right_bytes = right_projection.canonical_bytes()
    left_sha = left_projection.sha256()
    right_sha = right_projection.sha256()
    bytes_equal = left_bytes == right_bytes
    sha_equal = left_sha == right_sha
    code = NO_FAILURE if keysets_equal and bytes_equal and sha_equal else CONTENT_DRIFT
    assertion = (
        "none"
        if code == NO_FAILURE
        else "protected_before_projection_sha256 == protected_after_projection_sha256"
    )
    return _diagnostic(
        object_id=object_id,
        schema_equal=True,
        projection_keyset_equal=keysets_equal,
        bytes_equal=bytes_equal,
        sha_equal=sha_equal,
        before_sha=left_sha,
        after_sha=right_sha,
        code=code,
        assertion=assertion,
        details={
            "projection_keyset_equal": keysets_equal,
            "projection_bytes_equal": bytes_equal,
            "projection_sha256_equal": sha_equal,
        },
    )


def compare_observations(
    before: ProtectedObjectObservationReceiptV1,
    after: ProtectedObjectObservationReceiptV1,
) -> ProtectedObjectComparisonV1:
    before.to_mapping()
    after.to_mapping()
    return diagnose_snapshot_pair(before.snapshot.to_mapping(), after.snapshot.to_mapping())


def require_comparison_passed(comparison: ProtectedObjectComparisonV1) -> None:
    if not comparison.passed:
        raise SnapshotSchemaError(
            f"protected object comparison failed: {comparison.failure_code}",
            code=comparison.failure_code,
            assertion=comparison.failure_assertion,
            object_ids=(comparison.object_id,),
        )


def terminal_failure_from_comparison(
    comparison: ProtectedObjectComparisonV1, *, stage: str
) -> TerminalFailureV1:
    if comparison.passed:
        raise SnapshotSchemaError("a passing comparison cannot create terminal failure")
    return TerminalFailureV1(
        code=comparison.failure_code,
        stage=stage,
        assertion=comparison.failure_assertion,
        object_ids=(comparison.object_id,),
        details_digest=comparison.details_digest,
    )


def build_terminal_receipt(
    *, terminal_status: str, failure: TerminalFailureV1 | None
) -> TerminalReceiptV1:
    return TerminalReceiptV1(terminal_status=terminal_status, failure=failure)


def _default_command_runner(argv: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
    process = subprocess.run(
        list(argv),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=300,
        env=dict(environment),
    )
    return CommandResult(process.returncode, process.stdout, process.stderr)


def _sentinel_snapshot(target: CaptureTarget, state: str) -> ProtectedObjectSnapshotV2:
    sentinel = {
        "absent": _SENTINEL_ABSENT,
        "unreadable": _SENTINEL_UNREADABLE,
        "invalid": _SENTINEL_INVALID,
    }[state]
    rows = tuple(
        {
            "distribution": name,
            "state": state,
            "version": sentinel,
            "metadata_sha256": sentinel,
            "record_sha256": sentinel,
        }
        for name in sorted(CRITICAL_DISTRIBUTIONS)
    )
    return ProtectedObjectSnapshotV2(
        object_id=target.object_id,
        state=state,
        object_kind=target.object_kind,
        python_identity={
            "executable_sha256": sentinel,
            "executable_bytes": 0,
            "version": sentinel,
            "implementation": sentinel,
        },
        conda_history_sha256=sentinel,
        conda_explicit_sha256=sentinel,
        pip_freeze_sha256=sentinel,
        critical_distribution_identities=rows,
        filesystem_entry_count=0,
        regular_file_count=0,
        regular_file_bytes=0,
        tree_digest=sentinel,
        mtime_summary_digest=sentinel,
    )


def _tree_identity(root: Path) -> tuple[int, int, int, str, str]:
    tree_digest = hashlib.sha256()
    mtime_digest = hashlib.sha256()
    entry_count = 0
    regular_count = 0
    regular_bytes = 0
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
        for entry in entries:
            path = Path(entry.path)
            info = entry.stat(follow_symlinks=False)
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(info.st_mode):
                kind = "d"
                stack.append(path)
            elif stat.S_ISREG(info.st_mode):
                kind = "f"
                regular_count += 1
                regular_bytes += info.st_size
            elif stat.S_ISLNK(info.st_mode):
                kind = "l"
            else:
                kind = "o"
            entry_count += 1
            tree_digest.update(
                f"{relative}\0{kind}\0{info.st_mode:o}\0{info.st_size}\0{info.st_mtime_ns}\n".encode()
            )
            mtime_digest.update(f"{relative}\0{info.st_mtime_ns}\n".encode())
    return (
        entry_count,
        regular_count,
        regular_bytes,
        tree_digest.hexdigest(),
        mtime_digest.hexdigest(),
    )


def _metadata_name_and_version(raw: bytes) -> tuple[str, str]:
    name = ""
    version = ""
    for line in raw.decode("utf-8", "replace").splitlines():
        if line.startswith("Name: ") and not name:
            name = line[6:].strip()
        elif line.startswith("Version: ") and not version:
            version = line[9:].strip()
        if name and version:
            break
    if not name or not version:
        raise SnapshotSchemaError("distribution METADATA lacks name or version")
    return name, version


def _critical_distribution_identities(root: Path) -> tuple[Mapping[str, object], ...]:
    index: dict[str, list[Path]] = {}
    for site_packages in root.glob("lib/python*/site-packages"):
        for info in site_packages.glob("*.dist-info"):
            metadata = info / "METADATA"
            if not metadata.is_file() or metadata.is_symlink():
                continue
            try:
                name, _version = _metadata_name_and_version(metadata.read_bytes())
            except (OSError, SnapshotSchemaError):
                continue
            index.setdefault(_canonical_distribution_name(name), []).append(info)
    rows: list[Mapping[str, object]] = []
    for requested in sorted(CRITICAL_DISTRIBUTIONS):
        matches = sorted(index.get(_canonical_distribution_name(requested), []))
        if not matches:
            rows.append(
                {
                    "distribution": requested,
                    "state": "absent",
                    "version": _SENTINEL_ABSENT,
                    "metadata_sha256": _SENTINEL_ABSENT,
                    "record_sha256": _SENTINEL_ABSENT,
                }
            )
            continue
        if len(matches) != 1:
            rows.append(
                {
                    "distribution": requested,
                    "state": "invalid",
                    "version": _SENTINEL_INVALID,
                    "metadata_sha256": _SENTINEL_INVALID,
                    "record_sha256": _SENTINEL_INVALID,
                }
            )
            continue
        info = matches[0]
        metadata = info / "METADATA"
        record = info / "RECORD"
        _name, version = _metadata_name_and_version(metadata.read_bytes())
        rows.append(
            {
                "distribution": requested,
                "state": "present",
                "version": version,
                "metadata_sha256": _sha256_file(metadata),
                "record_sha256": (_sha256_file(record) if record.is_file() else _SENTINEL_ABSENT),
            }
        )
    return tuple(rows)


def capture_protected_object_snapshot(
    target: CaptureTarget,
    *,
    command_runner: CommandRunner = _default_command_runner,
) -> ProtectedObjectSnapshotV2:
    """The only production protected-object capture function."""

    try:
        info = target.root.lstat()
    except FileNotFoundError:
        return _sentinel_snapshot(target, "absent")
    except OSError:
        return _sentinel_snapshot(target, "unreadable")
    if target.root.is_symlink() or not stat.S_ISDIR(info.st_mode):
        return _sentinel_snapshot(target, "invalid")
    python = target.root / "bin/python"
    history = target.root / "conda-meta/history"
    if python.is_symlink() or not python.is_file() or history.is_symlink() or not history.is_file():
        return _sentinel_snapshot(target, "invalid")
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    environment["HF_DATASETS_OFFLINE"] = "1"
    version = command_runner(
        [
            str(python),
            "-I",
            "-B",
            "-c",
            "import json,platform;print(json.dumps({'version':platform.python_version(),"
            "'implementation':platform.python_implementation()}))",
        ],
        environment,
    )
    explicit = command_runner(
        [
            str(target.conda_executable),
            "--offline",
            "list",
            "--prefix",
            str(target.root),
            "--explicit",
        ],
        environment,
    )
    freeze = command_runner(
        [str(python), "-I", "-B", "-m", "pip", "freeze", "--all"],
        environment,
    )
    if any(result.returncode != 0 for result in (version, explicit, freeze)):
        return _sentinel_snapshot(target, "invalid")
    try:
        version_payload = json.loads(version.stdout)
        if not isinstance(version_payload, dict):
            raise ValueError
        entry_count, regular_count, regular_bytes, tree_digest, mtime_digest = _tree_identity(
            target.root
        )
        snapshot = ProtectedObjectSnapshotV2(
            object_id=target.object_id,
            state="present",
            object_kind=target.object_kind,
            python_identity={
                "executable_sha256": _sha256_file(python),
                "executable_bytes": python.stat().st_size,
                "version": str(version_payload["version"]),
                "implementation": str(version_payload["implementation"]),
            },
            conda_history_sha256=_sha256_file(history),
            conda_explicit_sha256=sha256_bytes(explicit.stdout),
            pip_freeze_sha256=sha256_bytes(freeze.stdout),
            critical_distribution_identities=_critical_distribution_identities(target.root),
            filesystem_entry_count=entry_count,
            regular_file_count=regular_count,
            regular_file_bytes=regular_bytes,
            tree_digest=tree_digest,
            mtime_summary_digest=mtime_digest,
        )
        snapshot.to_mapping()
        return snapshot
    except (KeyError, OSError, ValueError, SnapshotSchemaError):
        return _sentinel_snapshot(target, "invalid")


def qualify_measurement_system(
    targets: Sequence[CaptureTarget],
    *,
    attempt_id: str,
    helper_source_sha256: str,
    command_runner: CommandRunner = _default_command_runner,
    clock_ns: Callable[[], int] = time.time_ns,
    observer_pid: int | None = None,
) -> MeasurementQualificationReceiptV1:
    """Capture A/B contiguously for every object without performing a write."""

    target_ids = [target.object_id for target in targets]
    if len(set(target_ids)) != len(target_ids):
        raise SnapshotSchemaError("qualification targets must be unique")
    if set(target_ids) != U3_PROTECTED_OBJECT_IDS:
        raise SnapshotSchemaError(
            "qualification target IDs must equal the frozen U3 protected-object set"
        )
    _require_sha256(helper_source_sha256, label="helper_source_sha256")
    results: list[QualificationObjectResultV1] = []
    pid = os.getpid() if observer_pid is None else observer_pid
    for target in targets:
        snapshot_a = capture_protected_object_snapshot(target, command_runner=command_runner)
        observation_a = build_observation_receipt(
            snapshot_a,
            observation_phase="qualification_a",
            attempt_id=attempt_id,
            observed_at_ns=clock_ns(),
            observer_pid=pid,
        )
        snapshot_b = capture_protected_object_snapshot(target, command_runner=command_runner)
        observation_b = build_observation_receipt(
            snapshot_b,
            observation_phase="qualification_b",
            attempt_id=attempt_id,
            observed_at_ns=clock_ns(),
            observer_pid=pid,
        )
        comparison = compare_observations(observation_a, observation_b)
        passed = comparison.passed and snapshot_a.state == snapshot_b.state == "present"
        results.append(
            QualificationObjectResultV1(
                object_id=target.object_id,
                snapshot_a_projection_sha256=observation_a.projection_sha256,
                snapshot_b_projection_sha256=observation_b.projection_sha256,
                schema_keyset_equal=comparison.schema_keyset_equal,
                projection_keyset_equal=comparison.projection_keyset_equal,
                projection_bytes_equal=comparison.projection_bytes_equal,
                projection_sha256_equal=comparison.projection_sha256_equal,
                qualification_result="passed" if passed else "failed",
                comparison=comparison,
            )
        )
    return MeasurementQualificationReceiptV1(
        attempt_id=attempt_id,
        helper_source_sha256=helper_source_sha256,
        object_results=tuple(results),
        all_passed=all(row.qualification_result == "passed" for row in results),
    )
