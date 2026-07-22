"""Chemistry-free transaction layer for the one Phase 8B execution.

The module deliberately imports only the Python standard library and the
standard-library-only :mod:`linux_guardian` primitives.  It owns the durable
worker-registration/guardian-acknowledgement protocol and provides a generic
outer-guardian orchestration seam.  Chemistry imports remain behind
``worker_bootstrap`` and therefore cannot happen before the exact ACK/release
handshake succeeds.

The orchestration functions do not grant execution authority.  A caller must
consume the separately validated one-shot permit before the injected spawn
callback is reached.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol, cast

from nhc_deprot_ranker.quantum.linux_guardian import (
    GuardianPolicy,
    GuardianResult,
    ProcessIdentity,
    enable_child_subreaper,
    guard_process_group,
    install_parent_death_signal,
    read_process_identity,
    read_task_affinities,
    require_affinity,
    require_same_process,
    same_process,
    send_start_release,
    start_release_frame,
)

REGISTRATION_SCHEMA_VERSION: Final = "nhc-phase8b-worker-registration-v1"
ACKNOWLEDGEMENT_SCHEMA_VERSION: Final = "nhc-phase8b-guardian-ack-v1"
COMPUTE_CLAIM_SCHEMA_VERSION: Final = "nhc-phase8b-compute-claim-v1"
RECEIPT_SCHEMA_VERSION: Final = "nhc-phase8b-guardian-receipt-v1"

FROZEN_ALLOWED_CPUS: Final = frozenset({0, 1, 2, 3})
FROZEN_TRANSACTION_ID: Final = "attempt-phase8b-qxh-v001"
FROZEN_REQUEST_ID: Final = "phase8b-qxh-smoke-v001"
FROZEN_INCHIKEY: Final = "QXHIEGFUWOLQIJ-UHFFFAOYSA-N"
FROZEN_ELECTRON_COUNT: Final = 120
FROZEN_TIMEOUT_NS: Final = 7_200_000_000_000
FROZEN_TERMINATE_GRACE_NS: Final = 10_000_000_000
FROZEN_KILL_WAIT_NS: Final = 5_000_000_000
FROZEN_POLL_INTERVAL_NS: Final = 100_000_000

_PRIVATE_FILE_MODE: Final = 0o600
_PRIVATE_DIRECTORY_MODE: Final = 0o700
_MAX_RECORD_BYTES: Final = 64 * 1024
_MAX_ERROR_CODE_LENGTH: Final = 96
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_TRANSACTION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class Phase8BExecutionError(RuntimeError):
    """Base class for fail-closed transaction failures."""


class ExecutionRecordError(Phase8BExecutionError):
    """A durable coordination record or its filesystem identity is invalid."""


class ExecutionIdentityError(Phase8BExecutionError):
    """A guardian, supervisor, or worker identity failed an exact binding."""


class ExecutionDeadlineError(Phase8BExecutionError):
    """The one absolute monotonic deadline expired before a safe transition."""


class SupervisorLaunchError(Phase8BExecutionError):
    """The supervisor could not be started or verified safely."""


@dataclass(frozen=True, slots=True)
class TransactionPaths:
    """Four immutable coordination records inside one private directory."""

    registration: Path
    acknowledgement: Path
    compute_claim: Path
    receipt: Path

    def __post_init__(self) -> None:
        paths = (
            self.registration,
            self.acknowledgement,
            self.compute_claim,
            self.receipt,
        )
        if any(not path.is_absolute() for path in paths):
            raise ValueError("transaction record paths must be absolute")
        if len(set(paths)) != len(paths):
            raise ValueError("transaction record paths must be distinct")
        parents = {path.parent for path in paths}
        if len(parents) != 1:
            raise ValueError("transaction records must share one private directory")
        if any(path.name in {"", ".", ".."} for path in paths):
            raise ValueError("transaction record names are invalid")

    @property
    def private_directory(self) -> Path:
        """Directory whose mode and owner protect all transaction records."""

        return self.registration.parent


@dataclass(frozen=True, slots=True)
class TransactionPolicy:
    """Frozen transaction timing and CPU ceiling before a deadline is chosen."""

    timeout_ns: int = FROZEN_TIMEOUT_NS
    allowed_cpus: frozenset[int] = FROZEN_ALLOWED_CPUS
    terminate_grace_ns: int = FROZEN_TERMINATE_GRACE_NS
    kill_wait_ns: int = FROZEN_KILL_WAIT_NS
    poll_interval_ns: int = FROZEN_POLL_INTERVAL_NS

    def __post_init__(self) -> None:
        timings = (
            self.timeout_ns,
            self.terminate_grace_ns,
            self.kill_wait_ns,
            self.poll_interval_ns,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in timings):
            raise TypeError("transaction timing values must be integer nanoseconds")
        if self.timeout_ns <= 0 or self.poll_interval_ns <= 0:
            raise ValueError("timeout and poll interval must be positive")
        if self.terminate_grace_ns < 0 or self.kill_wait_ns < 0:
            raise ValueError("cleanup windows must be non-negative")
        if not self.allowed_cpus or any(
            isinstance(cpu, bool) or not isinstance(cpu, int) or cpu < 0
            for cpu in self.allowed_cpus
        ):
            raise ValueError("allowed_cpus must contain non-negative integers")

    def choose_absolute_deadline(self, *, clock_ns: Callable[[], int] = time.monotonic_ns) -> int:
        """Choose the only request deadline before permit consumption."""

        started_ns = clock_ns()
        if isinstance(started_ns, bool) or not isinstance(started_ns, int) or started_ns <= 0:
            raise ExecutionDeadlineError("monotonic clock returned an invalid value")
        return started_ns + self.timeout_ns

    def guardian_policy(self, absolute_deadline_ns: int) -> GuardianPolicy:
        """Bind the lower-level process-group guardian to the same deadline."""

        return GuardianPolicy(
            absolute_deadline_ns=absolute_deadline_ns,
            allowed_cpus=self.allowed_cpus,
            terminate_grace_ns=self.terminate_grace_ns,
            kill_wait_ns=self.kill_wait_ns,
            poll_interval_ns=self.poll_interval_ns,
        )


_FROZEN_TRANSACTION_POLICY: Final = TransactionPolicy()


@dataclass(frozen=True, slots=True)
class WorkerRegistration:
    """Supervisor-published exact identity of the pre-import worker."""

    transaction_id: str
    absolute_deadline_ns: int
    allowed_cpus: frozenset[int]
    release_token_sha256: str
    created_monotonic_ns: int
    guardian: ProcessIdentity
    supervisor: ProcessIdentity
    worker: ProcessIdentity


@dataclass(frozen=True, slots=True)
class GuardianAcknowledgement:
    """Guardian's durable proof that it independently verified registration."""

    transaction_id: str
    absolute_deadline_ns: int
    registration_sha256: str
    release_token_sha256: str
    created_monotonic_ns: int
    guardian: ProcessIdentity
    supervisor: ProcessIdentity
    worker: ProcessIdentity


@dataclass(frozen=True, slots=True)
class ComputeClaimAuthority:
    """Exact non-process authority embedded in the permanent compute claim."""

    transport_inventory_sha256: str
    payload_manifest_sha256: str
    permit_sha256: str
    request_sha256: str
    runner_source_sha256: str
    protocol_sha256: str
    resources_sha256: str
    cation_xyz_sha256: str
    neutral_xyz_sha256: str
    endpoint_atom_map_sha256: str
    legacy_atom_map_sha256: str
    geometry_validation_sha256: str
    electron_count: int
    request_id: str
    inchikey: str
    attempt_id: str
    project_root: Path
    run_root: Path
    request_path: Path
    output_root: Path


@dataclass(frozen=True, slots=True)
class ComputeClaim:
    """Permanent, process-bound authorization for exactly one worker import."""

    transaction_id: str
    absolute_deadline_ns: int
    allowed_cpus: frozenset[int]
    release_token_sha256: str
    registration_sha256: str
    acknowledgement_sha256: str
    created_monotonic_ns: int
    authority: ComputeClaimAuthority
    paths: TransactionPaths
    worker_scratch_path: Path
    guardian: ProcessIdentity
    supervisor: ProcessIdentity
    worker: ProcessIdentity


@dataclass(frozen=True, slots=True)
class ComputeClaimEvidence:
    """Canonical compute claim paired with the hash of its durable bytes."""

    claim: ComputeClaim
    compute_claim_sha256: str

    def __post_init__(self) -> None:
        _require_sha256(self.compute_claim_sha256, label="compute_claim_sha256")


ReceiptOutcome = Literal[
    "clean",
    "permit_consumption_failed",
    "authority_failed",
    "spawn_failed",
    "registration_failed",
    "worker_guard_failed",
    "supervisor_nonzero",
    "cleanup_failed",
    "internal_error",
]


@dataclass(frozen=True, slots=True)
class ConsumedPermitEvidence:
    """Opaque consumed permit plus the hash available for terminal evidence.

    The execution layer intentionally does not import the permit or bundle
    modules.  Production integration wraps ``ConsumedPhase8BPermit`` here and
    supplies a mandatory validator that rechecks the actual request, payload,
    source closure, paths, resources, candidate, and endpoint identities.
    """

    permit_sha256: str
    authority: object

    def __post_init__(self) -> None:
        _require_sha256(self.permit_sha256, label="permit_sha256")


@dataclass(frozen=True, slots=True)
class GuardianReceipt:
    """Immutable outer-guardian result written after permit consumption."""

    transaction_id: str
    permit_sha256: str
    absolute_deadline_ns: int
    started_monotonic_ns: int
    finished_monotonic_ns: int
    outcome: ReceiptOutcome
    error_code: str | None
    authority_validated: bool
    acknowledgement_published: bool
    worker_registration_sha256: str | None
    compute_claim_sha256: str | None
    supervisor_returncode: int | None
    guardian: ProcessIdentity
    supervisor: ProcessIdentity | None
    worker: ProcessIdentity | None
    worker_guardian_result: GuardianResult | None
    supervisor_guardian_result: GuardianResult | None

    @property
    def succeeded(self) -> bool:
        """Whether worker and supervisor both completed under the guardian."""

        return self.outcome == "clean" and self.supervisor_returncode == 0


@dataclass(frozen=True, slots=True)
class GuardianLaunchContext:
    """Exact metadata supplied to the injected supervisor launcher."""

    transaction_id: str
    paths: TransactionPaths
    policy: TransactionPolicy
    absolute_deadline_ns: int
    release_token: str
    guardian: ProcessIdentity


@dataclass(frozen=True, slots=True)
class FinalAcceptanceContext:
    """Hash-closed context available only after a clean receipt is durable."""

    transaction_id: str
    permit_sha256: str
    worker_registration_sha256: str
    compute_claim_sha256: str
    guardian_receipt: GuardianReceipt
    guardian_receipt_sha256: str
    consumed_authority: object
    validated_authority: object


@dataclass(frozen=True, slots=True)
class PublishedFinalAcceptance:
    """Hashes of final ``success.json`` and last-published ``_SUCCESS``."""

    success_json_sha256: str
    success_marker_sha256: str

    def __post_init__(self) -> None:
        _require_sha256(self.success_json_sha256, label="success_json_sha256")
        _require_sha256(self.success_marker_sha256, label="success_marker_sha256")


@dataclass(frozen=True, slots=True)
class GuardianTransactionResult:
    """In-memory result paired with the hash of its durable receipt."""

    receipt: GuardianReceipt
    receipt_sha256: str
    final_acceptance: PublishedFinalAcceptance | None


class SupervisorProcess(Protocol):
    """Minimal unreaped child handle required by the outer guardian."""

    pid: int

    def wait(self, timeout: float | None = None) -> int:
        """Reap the supervisor and return its exit status."""


SpawnSupervisor = Callable[[GuardianLaunchContext], SupervisorProcess]
PublishFinalAcceptance = Callable[[FinalAcceptanceContext], PublishedFinalAcceptance]
IdentityReader = Callable[[int], ProcessIdentity]
TaskAffinityReader = Callable[[int], Mapping[int, frozenset[int]]]
ChildExitObserver = Callable[[int], bool]


def _require_transaction_id(value: str) -> str:
    if not isinstance(value, str) or _TRANSACTION_RE.fullmatch(value) is None:
        raise ExecutionRecordError("transaction_id is malformed")
    return value


def _require_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ExecutionRecordError(f"{label} must be a lowercase SHA256")
    return value


def _require_positive_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ExecutionRecordError(f"{label} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionRecordError(f"{label} must be a non-negative integer")
    return value


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _identity_payload(identity: ProcessIdentity) -> dict[str, object]:
    return {
        "pid": identity.pid,
        "ppid": identity.ppid,
        "pgid": identity.pgid,
        "sid": identity.sid,
        "starttime_ticks": identity.starttime_ticks,
        "state": identity.state,
        "boot_id": identity.boot_id,
        "cpus_allowed": sorted(identity.cpus_allowed),
    }


def _strict_object(value: object, *, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ExecutionRecordError(f"{label} must be an object")
    result = cast(dict[str, object], value)
    if set(result) != keys:
        raise ExecutionRecordError(f"{label} fields drifted")
    return result


def _identity_from_payload(value: object, *, label: str) -> ProcessIdentity:
    payload = _strict_object(
        value,
        keys={
            "pid",
            "ppid",
            "pgid",
            "sid",
            "starttime_ticks",
            "state",
            "boot_id",
            "cpus_allowed",
        },
        label=label,
    )
    raw_state = payload["state"]
    raw_boot_id = payload["boot_id"]
    raw_cpus = payload["cpus_allowed"]
    if not isinstance(raw_state, str) or len(raw_state) != 1:
        raise ExecutionRecordError(f"{label}.state is malformed")
    if (
        not isinstance(raw_boot_id, str)
        or not raw_boot_id
        or any(character.isspace() for character in raw_boot_id)
    ):
        raise ExecutionRecordError(f"{label}.boot_id is malformed")
    if not isinstance(raw_cpus, list) or not raw_cpus:
        raise ExecutionRecordError(f"{label}.cpus_allowed is malformed")
    cpus: list[int] = []
    for raw_cpu in raw_cpus:
        cpus.append(_require_nonnegative_int(raw_cpu, label=f"{label}.cpus_allowed"))
    if cpus != sorted(set(cpus)):
        raise ExecutionRecordError(f"{label}.cpus_allowed must be sorted and unique")
    return ProcessIdentity(
        pid=_require_positive_int(payload["pid"], label=f"{label}.pid"),
        ppid=_require_nonnegative_int(payload["ppid"], label=f"{label}.ppid"),
        pgid=_require_positive_int(payload["pgid"], label=f"{label}.pgid"),
        sid=_require_positive_int(payload["sid"], label=f"{label}.sid"),
        starttime_ticks=_require_positive_int(
            payload["starttime_ticks"], label=f"{label}.starttime_ticks"
        ),
        state=raw_state,
        boot_id=raw_boot_id,
        cpus_allowed=frozenset(cpus),
    )


def _registration_payload(record: WorkerRegistration) -> dict[str, object]:
    return {
        "schema_version": REGISTRATION_SCHEMA_VERSION,
        "transaction_id": record.transaction_id,
        "absolute_deadline_ns": record.absolute_deadline_ns,
        "allowed_cpus": sorted(record.allowed_cpus),
        "release_token_sha256": record.release_token_sha256,
        "created_monotonic_ns": record.created_monotonic_ns,
        "guardian": _identity_payload(record.guardian),
        "supervisor": _identity_payload(record.supervisor),
        "worker": _identity_payload(record.worker),
    }


def registration_bytes(record: WorkerRegistration) -> bytes:
    """Return the canonical bytes whose hash is acknowledged by the guardian."""

    validate_registration_structure(record)
    return _canonical_json_bytes(_registration_payload(record))


def registration_sha256(record: WorkerRegistration) -> str:
    """Hash the complete immutable registration identity."""

    return _sha256_bytes(registration_bytes(record))


def _acknowledgement_payload(record: GuardianAcknowledgement) -> dict[str, object]:
    return {
        "schema_version": ACKNOWLEDGEMENT_SCHEMA_VERSION,
        "transaction_id": record.transaction_id,
        "absolute_deadline_ns": record.absolute_deadline_ns,
        "registration_sha256": record.registration_sha256,
        "release_token_sha256": record.release_token_sha256,
        "created_monotonic_ns": record.created_monotonic_ns,
        "guardian": _identity_payload(record.guardian),
        "supervisor": _identity_payload(record.supervisor),
        "worker": _identity_payload(record.worker),
    }


def acknowledgement_bytes(record: GuardianAcknowledgement) -> bytes:
    """Return canonical guardian-ACK bytes."""

    validate_acknowledgement_structure(record)
    return _canonical_json_bytes(_acknowledgement_payload(record))


def acknowledgement_sha256(record: GuardianAcknowledgement) -> str:
    """Hash the complete immutable guardian acknowledgement."""

    return _sha256_bytes(acknowledgement_bytes(record))


def _claim_authority_payload(record: ComputeClaimAuthority) -> dict[str, object]:
    return {
        "transport_inventory_sha256": record.transport_inventory_sha256,
        "payload_manifest_sha256": record.payload_manifest_sha256,
        "permit_sha256": record.permit_sha256,
        "request_sha256": record.request_sha256,
        "runner_source_sha256": record.runner_source_sha256,
        "protocol_sha256": record.protocol_sha256,
        "resources_sha256": record.resources_sha256,
        "cation_xyz_sha256": record.cation_xyz_sha256,
        "neutral_xyz_sha256": record.neutral_xyz_sha256,
        "endpoint_atom_map_sha256": record.endpoint_atom_map_sha256,
        "legacy_atom_map_sha256": record.legacy_atom_map_sha256,
        "geometry_validation_sha256": record.geometry_validation_sha256,
        "electron_count": record.electron_count,
        "request_id": record.request_id,
        "inchikey": record.inchikey,
        "attempt_id": record.attempt_id,
        "project_root": record.project_root.as_posix(),
        "run_root": record.run_root.as_posix(),
        "request_path": record.request_path.as_posix(),
        "output_root": record.output_root.as_posix(),
    }


def _transaction_paths_payload(paths: TransactionPaths) -> dict[str, str]:
    return {
        "registration": paths.registration.as_posix(),
        "acknowledgement": paths.acknowledgement.as_posix(),
        "compute_claim": paths.compute_claim.as_posix(),
        "receipt": paths.receipt.as_posix(),
    }


def _compute_claim_payload(record: ComputeClaim) -> dict[str, object]:
    return {
        "schema_version": COMPUTE_CLAIM_SCHEMA_VERSION,
        "transaction_id": record.transaction_id,
        "absolute_deadline_ns": record.absolute_deadline_ns,
        "allowed_cpus": sorted(record.allowed_cpus),
        "release_token_sha256": record.release_token_sha256,
        "registration_sha256": record.registration_sha256,
        "acknowledgement_sha256": record.acknowledgement_sha256,
        "created_monotonic_ns": record.created_monotonic_ns,
        "authority": _claim_authority_payload(record.authority),
        "paths": _transaction_paths_payload(record.paths),
        "worker_scratch_path": record.worker_scratch_path.as_posix(),
        "guardian": _identity_payload(record.guardian),
        "supervisor": _identity_payload(record.supervisor),
        "worker": _identity_payload(record.worker),
    }


def compute_claim_bytes(record: ComputeClaim) -> bytes:
    """Return canonical bytes for the permanent compute claim."""

    validate_compute_claim_structure(record)
    return _canonical_json_bytes(_compute_claim_payload(record))


def compute_claim_sha256(record: ComputeClaim) -> str:
    """Hash the complete permanent compute claim."""

    return _sha256_bytes(compute_claim_bytes(record))


def _guardian_result_payload(result: GuardianResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        "outcome": result.outcome,
        "trigger": result.trigger,
        "term_sent": result.term_sent,
        "kill_sent": result.kill_sent,
        "group_cleanup_confirmed": result.group_cleanup_confirmed,
        "duration_ns": result.duration_ns,
        "error_message": result.error_message,
    }


def _receipt_payload(record: GuardianReceipt) -> dict[str, object]:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "transaction_id": record.transaction_id,
        "permit_sha256": record.permit_sha256,
        "absolute_deadline_ns": record.absolute_deadline_ns,
        "started_monotonic_ns": record.started_monotonic_ns,
        "finished_monotonic_ns": record.finished_monotonic_ns,
        "outcome": record.outcome,
        "error_code": record.error_code,
        "authority_validated": record.authority_validated,
        "acknowledgement_published": record.acknowledgement_published,
        "worker_registration_sha256": record.worker_registration_sha256,
        "compute_claim_sha256": record.compute_claim_sha256,
        "supervisor_returncode": record.supervisor_returncode,
        "guardian": _identity_payload(record.guardian),
        "supervisor": (None if record.supervisor is None else _identity_payload(record.supervisor)),
        "worker": None if record.worker is None else _identity_payload(record.worker),
        "worker_guardian_result": _guardian_result_payload(record.worker_guardian_result),
        "supervisor_guardian_result": _guardian_result_payload(record.supervisor_guardian_result),
    }


def receipt_bytes(record: GuardianReceipt) -> bytes:
    """Return canonical immutable receipt bytes."""

    validate_receipt_structure(record)
    return _canonical_json_bytes(_receipt_payload(record))


def _parse_json(raw: bytes, *, label: str) -> dict[str, object]:
    if not raw or len(raw) > _MAX_RECORD_BYTES:
        raise ExecutionRecordError(f"{label} size is invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExecutionRecordError(f"{label} must be UTF-8") from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ExecutionRecordError(f"{label} contains duplicate key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise ExecutionRecordError(f"{label} contains non-finite number: {value}")

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except ExecutionRecordError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ExecutionRecordError(f"{label} is not strict JSON") from exc
    if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
        raise ExecutionRecordError(f"{label} must be an object")
    return cast(dict[str, object], decoded)


def _cpus_from_payload(value: object, *, label: str) -> frozenset[int]:
    if not isinstance(value, list) or not value:
        raise ExecutionRecordError(f"{label} must be a non-empty list")
    cpus = [_require_nonnegative_int(cpu, label=label) for cpu in value]
    if cpus != sorted(set(cpus)):
        raise ExecutionRecordError(f"{label} must be sorted and unique")
    return frozenset(cpus)


def _absolute_path_from_payload(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ExecutionRecordError(f"{label} must be an absolute POSIX path")
    path = Path(value)
    if (
        not path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or Path(os.path.abspath(path)) != path
    ):
        raise ExecutionRecordError(f"{label} must be a canonical absolute path")
    return path


def parse_registration(raw: bytes) -> WorkerRegistration:
    """Parse exact registration JSON without accepting extension fields."""

    payload = _strict_object(
        _parse_json(raw, label="worker registration"),
        keys={
            "schema_version",
            "transaction_id",
            "absolute_deadline_ns",
            "allowed_cpus",
            "release_token_sha256",
            "created_monotonic_ns",
            "guardian",
            "supervisor",
            "worker",
        },
        label="worker registration",
    )
    if payload["schema_version"] != REGISTRATION_SCHEMA_VERSION:
        raise ExecutionRecordError("worker registration schema drifted")
    transaction = payload["transaction_id"]
    release_hash = payload["release_token_sha256"]
    if not isinstance(transaction, str) or not isinstance(release_hash, str):
        raise ExecutionRecordError("worker registration strings are malformed")
    record = WorkerRegistration(
        transaction_id=_require_transaction_id(transaction),
        absolute_deadline_ns=_require_positive_int(
            payload["absolute_deadline_ns"], label="absolute_deadline_ns"
        ),
        allowed_cpus=_cpus_from_payload(payload["allowed_cpus"], label="allowed_cpus"),
        release_token_sha256=_require_sha256(release_hash, label="release_token_sha256"),
        created_monotonic_ns=_require_positive_int(
            payload["created_monotonic_ns"], label="created_monotonic_ns"
        ),
        guardian=_identity_from_payload(payload["guardian"], label="guardian"),
        supervisor=_identity_from_payload(payload["supervisor"], label="supervisor"),
        worker=_identity_from_payload(payload["worker"], label="worker"),
    )
    validate_registration_structure(record)
    if registration_bytes(record) != raw:
        raise ExecutionRecordError("worker registration is not canonical")
    return record


def parse_acknowledgement(raw: bytes) -> GuardianAcknowledgement:
    """Parse exact ACK JSON without accepting extension fields."""

    payload = _strict_object(
        _parse_json(raw, label="guardian acknowledgement"),
        keys={
            "schema_version",
            "transaction_id",
            "absolute_deadline_ns",
            "registration_sha256",
            "release_token_sha256",
            "created_monotonic_ns",
            "guardian",
            "supervisor",
            "worker",
        },
        label="guardian acknowledgement",
    )
    if payload["schema_version"] != ACKNOWLEDGEMENT_SCHEMA_VERSION:
        raise ExecutionRecordError("guardian acknowledgement schema drifted")
    strings = (
        payload["transaction_id"],
        payload["registration_sha256"],
        payload["release_token_sha256"],
    )
    if any(not isinstance(value, str) for value in strings):
        raise ExecutionRecordError("guardian acknowledgement strings are malformed")
    record = GuardianAcknowledgement(
        transaction_id=_require_transaction_id(cast(str, strings[0])),
        absolute_deadline_ns=_require_positive_int(
            payload["absolute_deadline_ns"], label="absolute_deadline_ns"
        ),
        registration_sha256=_require_sha256(cast(str, strings[1]), label="registration_sha256"),
        release_token_sha256=_require_sha256(cast(str, strings[2]), label="release_token_sha256"),
        created_monotonic_ns=_require_positive_int(
            payload["created_monotonic_ns"], label="created_monotonic_ns"
        ),
        guardian=_identity_from_payload(payload["guardian"], label="guardian"),
        supervisor=_identity_from_payload(payload["supervisor"], label="supervisor"),
        worker=_identity_from_payload(payload["worker"], label="worker"),
    )
    validate_acknowledgement_structure(record)
    if acknowledgement_bytes(record) != raw:
        raise ExecutionRecordError("guardian acknowledgement is not canonical")
    return record


def _claim_authority_from_payload(value: object) -> ComputeClaimAuthority:
    keys = {
        "transport_inventory_sha256",
        "payload_manifest_sha256",
        "permit_sha256",
        "request_sha256",
        "runner_source_sha256",
        "protocol_sha256",
        "resources_sha256",
        "cation_xyz_sha256",
        "neutral_xyz_sha256",
        "endpoint_atom_map_sha256",
        "legacy_atom_map_sha256",
        "geometry_validation_sha256",
        "electron_count",
        "request_id",
        "inchikey",
        "attempt_id",
        "project_root",
        "run_root",
        "request_path",
        "output_root",
    }
    payload = _strict_object(value, keys=keys, label="compute claim authority")
    sha_fields = (
        "transport_inventory_sha256",
        "payload_manifest_sha256",
        "permit_sha256",
        "request_sha256",
        "runner_source_sha256",
        "protocol_sha256",
        "resources_sha256",
        "cation_xyz_sha256",
        "neutral_xyz_sha256",
        "endpoint_atom_map_sha256",
        "legacy_atom_map_sha256",
        "geometry_validation_sha256",
    )
    hashes: dict[str, str] = {}
    for field in sha_fields:
        raw_hash = payload[field]
        if not isinstance(raw_hash, str):
            raise ExecutionRecordError(f"compute claim authority {field} is malformed")
        hashes[field] = _require_sha256(raw_hash, label=field)
    strings = (payload["request_id"], payload["inchikey"], payload["attempt_id"])
    if any(not isinstance(item, str) for item in strings):
        raise ExecutionRecordError("compute claim authority identity strings are malformed")
    record = ComputeClaimAuthority(
        **hashes,
        electron_count=_require_positive_int(payload["electron_count"], label="electron_count"),
        request_id=cast(str, strings[0]),
        inchikey=cast(str, strings[1]),
        attempt_id=cast(str, strings[2]),
        project_root=_absolute_path_from_payload(payload["project_root"], label="project_root"),
        run_root=_absolute_path_from_payload(payload["run_root"], label="run_root"),
        request_path=_absolute_path_from_payload(payload["request_path"], label="request_path"),
        output_root=_absolute_path_from_payload(payload["output_root"], label="output_root"),
    )
    validate_compute_claim_authority(record)
    return record


def _transaction_paths_from_payload(value: object) -> TransactionPaths:
    payload = _strict_object(
        value,
        keys={"registration", "acknowledgement", "compute_claim", "receipt"},
        label="compute claim paths",
    )
    return TransactionPaths(
        registration=_absolute_path_from_payload(payload["registration"], label="registration"),
        acknowledgement=_absolute_path_from_payload(
            payload["acknowledgement"], label="acknowledgement"
        ),
        compute_claim=_absolute_path_from_payload(payload["compute_claim"], label="compute_claim"),
        receipt=_absolute_path_from_payload(payload["receipt"], label="receipt"),
    )


def parse_compute_claim(raw: bytes) -> ComputeClaim:
    """Parse one exact canonical compute claim without extension fields."""

    payload = _strict_object(
        _parse_json(raw, label="compute claim"),
        keys={
            "schema_version",
            "transaction_id",
            "absolute_deadline_ns",
            "allowed_cpus",
            "release_token_sha256",
            "registration_sha256",
            "acknowledgement_sha256",
            "created_monotonic_ns",
            "authority",
            "paths",
            "worker_scratch_path",
            "guardian",
            "supervisor",
            "worker",
        },
        label="compute claim",
    )
    if payload["schema_version"] != COMPUTE_CLAIM_SCHEMA_VERSION:
        raise ExecutionRecordError("compute claim schema drifted")
    strings = (
        payload["transaction_id"],
        payload["release_token_sha256"],
        payload["registration_sha256"],
        payload["acknowledgement_sha256"],
    )
    if any(not isinstance(item, str) for item in strings):
        raise ExecutionRecordError("compute claim strings are malformed")
    record = ComputeClaim(
        transaction_id=_require_transaction_id(cast(str, strings[0])),
        absolute_deadline_ns=_require_positive_int(
            payload["absolute_deadline_ns"], label="absolute_deadline_ns"
        ),
        allowed_cpus=_cpus_from_payload(payload["allowed_cpus"], label="allowed_cpus"),
        release_token_sha256=_require_sha256(cast(str, strings[1]), label="release_token_sha256"),
        registration_sha256=_require_sha256(cast(str, strings[2]), label="registration_sha256"),
        acknowledgement_sha256=_require_sha256(
            cast(str, strings[3]), label="acknowledgement_sha256"
        ),
        created_monotonic_ns=_require_positive_int(
            payload["created_monotonic_ns"], label="created_monotonic_ns"
        ),
        authority=_claim_authority_from_payload(payload["authority"]),
        paths=_transaction_paths_from_payload(payload["paths"]),
        worker_scratch_path=_absolute_path_from_payload(
            payload["worker_scratch_path"], label="worker_scratch_path"
        ),
        guardian=_identity_from_payload(payload["guardian"], label="guardian"),
        supervisor=_identity_from_payload(payload["supervisor"], label="supervisor"),
        worker=_identity_from_payload(payload["worker"], label="worker"),
    )
    validate_compute_claim_structure(record)
    if compute_claim_bytes(record) != raw:
        raise ExecutionRecordError("compute claim is not canonical")
    return record


def _validate_session_leader(
    identity: ProcessIdentity,
    *,
    label: str,
    allowed_cpus: frozenset[int],
    expected_parent_pid: int | None,
) -> None:
    if identity.pid <= 1 or identity.pgid != identity.pid or identity.sid != identity.pid:
        raise ExecutionIdentityError(f"{label} is not a safe session/process-group leader")
    if identity.state.upper() in {"X", "Z"}:
        raise ExecutionIdentityError(f"{label} is not live")
    if expected_parent_pid is not None and identity.ppid != expected_parent_pid:
        raise ExecutionIdentityError(f"{label} parent identity drifted")
    try:
        require_affinity(identity.cpus_allowed, allowed_cpus, exact=True)
    except Exception as exc:
        raise ExecutionIdentityError(f"{label} affinity drifted") from exc


def validate_registration_structure(record: WorkerRegistration) -> None:
    """Validate all immutable parent/session/boot/deadline bindings."""

    _require_transaction_id(record.transaction_id)
    _require_sha256(record.release_token_sha256, label="release_token_sha256")
    _require_positive_int(record.absolute_deadline_ns, label="absolute_deadline_ns")
    _require_positive_int(record.created_monotonic_ns, label="created_monotonic_ns")
    if record.created_monotonic_ns >= record.absolute_deadline_ns:
        raise ExecutionDeadlineError("registration was created at or after the deadline")
    if not record.allowed_cpus:
        raise ExecutionIdentityError("registration CPU set is empty")
    _validate_session_leader(
        record.guardian,
        label="guardian",
        allowed_cpus=record.allowed_cpus,
        expected_parent_pid=None,
    )
    _validate_session_leader(
        record.supervisor,
        label="supervisor",
        allowed_cpus=record.allowed_cpus,
        expected_parent_pid=record.guardian.pid,
    )
    _validate_session_leader(
        record.worker,
        label="worker",
        allowed_cpus=record.allowed_cpus,
        expected_parent_pid=record.supervisor.pid,
    )
    if len({record.guardian.pid, record.supervisor.pid, record.worker.pid}) != 3:
        raise ExecutionIdentityError("guardian, supervisor, and worker PIDs must be distinct")
    if len({record.guardian.boot_id, record.supervisor.boot_id, record.worker.boot_id}) != 1:
        raise ExecutionIdentityError("transaction crossed a Linux boot identity")


def validate_acknowledgement_structure(record: GuardianAcknowledgement) -> None:
    """Validate the ACK's complete immutable binding."""

    _require_transaction_id(record.transaction_id)
    _require_sha256(record.registration_sha256, label="registration_sha256")
    _require_sha256(record.release_token_sha256, label="release_token_sha256")
    _require_positive_int(record.absolute_deadline_ns, label="absolute_deadline_ns")
    _require_positive_int(record.created_monotonic_ns, label="created_monotonic_ns")
    if record.created_monotonic_ns >= record.absolute_deadline_ns:
        raise ExecutionDeadlineError("acknowledgement was created at or after the deadline")
    # Reuse the strict hierarchy validation without inventing an alternate
    # identity contract for the acknowledgement.
    validate_registration_structure(
        WorkerRegistration(
            transaction_id=record.transaction_id,
            absolute_deadline_ns=record.absolute_deadline_ns,
            allowed_cpus=record.guardian.cpus_allowed,
            release_token_sha256=record.release_token_sha256,
            created_monotonic_ns=record.created_monotonic_ns,
            guardian=record.guardian,
            supervisor=record.supervisor,
            worker=record.worker,
        )
    )


def validate_compute_claim_authority(record: ComputeClaimAuthority) -> None:
    """Validate exact frozen identities, hashes, and absolute path relations."""

    for field in (
        "transport_inventory_sha256",
        "payload_manifest_sha256",
        "permit_sha256",
        "request_sha256",
        "runner_source_sha256",
        "protocol_sha256",
        "resources_sha256",
        "cation_xyz_sha256",
        "neutral_xyz_sha256",
        "endpoint_atom_map_sha256",
        "legacy_atom_map_sha256",
        "geometry_validation_sha256",
    ):
        _require_sha256(cast(str, getattr(record, field)), label=field)
    if (
        record.request_id != FROZEN_REQUEST_ID
        or record.inchikey != FROZEN_INCHIKEY
        or record.attempt_id != FROZEN_TRANSACTION_ID
        or record.electron_count != FROZEN_ELECTRON_COUNT
    ):
        raise ExecutionIdentityError("compute claim frozen authority identity drifted")
    paths = (record.project_root, record.run_root, record.request_path, record.output_root)
    if any(
        not isinstance(path, Path)
        or not path.is_absolute()
        or Path(os.path.abspath(path)) != path
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        for path in paths
    ):
        raise ExecutionIdentityError("compute claim authority path is not canonical and absolute")
    try:
        run_relative = record.run_root.relative_to(record.project_root)
        request_relative = record.request_path.relative_to(record.run_root)
        output_relative = record.output_root.relative_to(record.run_root)
    except ValueError as exc:
        raise ExecutionIdentityError("compute claim authority path escaped its root") from exc
    if (
        not run_relative.parts
        or request_relative.as_posix() != "input/request.json"
        or output_relative.as_posix() != "runtime/output"
    ):
        raise ExecutionIdentityError("compute claim authority path binding drifted")


def validate_compute_claim_structure(record: ComputeClaim) -> None:
    """Validate all immutable fields of one permanent compute claim."""

    _require_transaction_id(record.transaction_id)
    _require_sha256(record.release_token_sha256, label="release_token_sha256")
    _require_sha256(record.registration_sha256, label="registration_sha256")
    _require_sha256(record.acknowledgement_sha256, label="acknowledgement_sha256")
    _require_positive_int(record.absolute_deadline_ns, label="absolute_deadline_ns")
    _require_positive_int(record.created_monotonic_ns, label="created_monotonic_ns")
    validate_compute_claim_authority(record.authority)
    if (
        record.transaction_id != FROZEN_TRANSACTION_ID
        or record.transaction_id != record.authority.attempt_id
        or record.allowed_cpus != FROZEN_ALLOWED_CPUS
        or record.created_monotonic_ns >= record.absolute_deadline_ns
    ):
        raise ExecutionIdentityError("compute claim transaction, CPU, or deadline binding drifted")
    expected_names = {
        "registration": "worker_registration.json",
        "acknowledgement": "guardian_acknowledgement.json",
        "compute_claim": "compute_claim.json",
        "receipt": "guardian_receipt.json",
    }
    if any(getattr(record.paths, field).name != name for field, name in expected_names.items()):
        raise ExecutionIdentityError("compute claim coordination path names drifted")
    if record.paths.private_directory != record.authority.run_root / "private":
        raise ExecutionIdentityError("compute claim private directory drifted")
    scratch = record.worker_scratch_path
    if (
        not scratch.is_absolute()
        or Path(os.path.abspath(scratch)) != scratch
        or scratch.parent != record.authority.output_root.parent
        or not scratch.name.startswith(f".worker-{record.authority.attempt_id}-")
    ):
        raise ExecutionIdentityError("compute claim worker scratch path drifted")
    registration = WorkerRegistration(
        transaction_id=record.transaction_id,
        absolute_deadline_ns=record.absolute_deadline_ns,
        allowed_cpus=record.allowed_cpus,
        release_token_sha256=record.release_token_sha256,
        created_monotonic_ns=record.created_monotonic_ns,
        guardian=record.guardian,
        supervisor=record.supervisor,
        worker=record.worker,
    )
    validate_registration_structure(registration)


def validate_compute_claim_chain(
    claim: ComputeClaim,
    registration: WorkerRegistration,
    acknowledgement: GuardianAcknowledgement,
) -> None:
    """Bind the claim to the exact immutable registration and guardian ACK."""

    validate_compute_claim_structure(claim)
    validate_registration_structure(registration)
    validate_acknowledgement_structure(acknowledgement)
    if (
        claim.registration_sha256 != registration_sha256(registration)
        or claim.acknowledgement_sha256 != acknowledgement_sha256(acknowledgement)
        or acknowledgement.registration_sha256 != claim.registration_sha256
        or claim.transaction_id != registration.transaction_id
        or claim.absolute_deadline_ns != registration.absolute_deadline_ns
        or claim.allowed_cpus != registration.allowed_cpus
        or claim.release_token_sha256 != registration.release_token_sha256
        or claim.guardian != registration.guardian
        or claim.supervisor != registration.supervisor
        or claim.worker != registration.worker
        or acknowledgement.transaction_id != claim.transaction_id
        or acknowledgement.absolute_deadline_ns != claim.absolute_deadline_ns
        or acknowledgement.release_token_sha256 != claim.release_token_sha256
        or acknowledgement.guardian != claim.guardian
        or acknowledgement.supervisor != claim.supervisor
        or acknowledgement.worker != claim.worker
        or claim.created_monotonic_ns < acknowledgement.created_monotonic_ns
    ):
        raise ExecutionIdentityError("compute claim registration/ACK hash chain drifted")


def _validate_observed_identity(
    expected: ProcessIdentity,
    observed: ProcessIdentity,
    *,
    label: str,
    allowed_cpus: frozenset[int],
    expected_parent_pid: int | None,
    task_affinities: Mapping[int, frozenset[int]],
) -> None:
    try:
        require_same_process(expected, observed)
    except Exception as exc:
        raise ExecutionIdentityError(f"{label} PID/starttime/boot/PGID/SID drifted") from exc
    _validate_session_leader(
        observed,
        label=label,
        allowed_cpus=allowed_cpus,
        expected_parent_pid=expected_parent_pid,
    )
    if not task_affinities:
        raise ExecutionIdentityError(f"{label} task affinity inventory is empty")
    for affinity in task_affinities.values():
        try:
            require_affinity(affinity, allowed_cpus, exact=True)
        except Exception as exc:
            raise ExecutionIdentityError(f"{label} task affinity drifted") from exc


def validate_registration_observation(
    record: WorkerRegistration,
    *,
    expected_transaction_id: str,
    expected_absolute_deadline_ns: int,
    expected_allowed_cpus: frozenset[int],
    expected_release_token_sha256: str,
    observed_guardian: ProcessIdentity,
    observed_supervisor: ProcessIdentity,
    observed_worker: ProcessIdentity,
    guardian_task_affinities: Mapping[int, frozenset[int]],
    supervisor_task_affinities: Mapping[int, frozenset[int]],
    worker_task_affinities: Mapping[int, frozenset[int]],
) -> None:
    """Independently bind durable registration to live ``/proc`` identities."""

    validate_registration_structure(record)
    if (
        record.transaction_id != _require_transaction_id(expected_transaction_id)
        or record.absolute_deadline_ns != expected_absolute_deadline_ns
        or record.allowed_cpus != expected_allowed_cpus
        or record.release_token_sha256
        != _require_sha256(expected_release_token_sha256, label="release_token_sha256")
    ):
        raise ExecutionIdentityError("worker registration transaction bindings drifted")
    _validate_observed_identity(
        record.guardian,
        observed_guardian,
        label="guardian",
        allowed_cpus=expected_allowed_cpus,
        expected_parent_pid=None,
        task_affinities=guardian_task_affinities,
    )
    _validate_observed_identity(
        record.supervisor,
        observed_supervisor,
        label="supervisor",
        allowed_cpus=expected_allowed_cpus,
        expected_parent_pid=observed_guardian.pid,
        task_affinities=supervisor_task_affinities,
    )
    _validate_observed_identity(
        record.worker,
        observed_worker,
        label="worker",
        allowed_cpus=expected_allowed_cpus,
        expected_parent_pid=observed_supervisor.pid,
        task_affinities=worker_task_affinities,
    )


def validate_acknowledgement(
    acknowledgement: GuardianAcknowledgement,
    registration: WorkerRegistration,
    *,
    observed_guardian: ProcessIdentity,
    observed_supervisor: ProcessIdentity,
    observed_worker: ProcessIdentity,
    task_affinity_reader: TaskAffinityReader,
) -> None:
    """Supervisor-side validation required immediately before pipe release."""

    validate_acknowledgement_structure(acknowledgement)
    if (
        acknowledgement.transaction_id != registration.transaction_id
        or acknowledgement.absolute_deadline_ns != registration.absolute_deadline_ns
        or acknowledgement.registration_sha256 != registration_sha256(registration)
        or acknowledgement.release_token_sha256 != registration.release_token_sha256
        or acknowledgement.guardian != registration.guardian
        or acknowledgement.supervisor != registration.supervisor
        or acknowledgement.worker != registration.worker
    ):
        raise ExecutionIdentityError("guardian acknowledgement binding drifted")
    validate_registration_observation(
        registration,
        expected_transaction_id=registration.transaction_id,
        expected_absolute_deadline_ns=registration.absolute_deadline_ns,
        expected_allowed_cpus=registration.allowed_cpus,
        expected_release_token_sha256=registration.release_token_sha256,
        observed_guardian=observed_guardian,
        observed_supervisor=observed_supervisor,
        observed_worker=observed_worker,
        guardian_task_affinities=task_affinity_reader(observed_guardian.pid),
        supervisor_task_affinities=task_affinity_reader(observed_supervisor.pid),
        worker_task_affinities=task_affinity_reader(observed_worker.pid),
    )


def _validate_private_directory(path: Path) -> int:
    if not path.is_absolute():
        raise ExecutionRecordError("private transaction directory must be absolute")
    try:
        if path.resolve(strict=True) != path:
            raise ExecutionRecordError(
                "private transaction directory traverses a symlink or noncanonical path"
            )
    except ExecutionRecordError:
        raise
    except OSError as exc:
        raise ExecutionRecordError("private transaction directory is unavailable") from exc
    flags = os.O_RDONLY | os.O_CLOEXEC
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(path, flags)
    except OSError as exc:
        raise ExecutionRecordError("private transaction directory cannot be opened safely") from exc
    opened = os.fstat(directory_fd)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) != _PRIVATE_DIRECTORY_MODE
        or opened.st_uid != os.geteuid()
    ):
        os.close(directory_fd)
        raise ExecutionRecordError("private transaction directory identity or mode drifted")
    return directory_fd


def _validate_record_stat(observed: os.stat_result, *, label: str) -> None:
    if (
        not stat.S_ISREG(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != _PRIVATE_FILE_MODE
        or observed.st_nlink != 1
        or observed.st_uid != os.geteuid()
        or observed.st_size <= 0
        or observed.st_size > _MAX_RECORD_BYTES
    ):
        raise ExecutionRecordError(f"{label} filesystem identity or mode drifted")


def _write_exclusive(path: Path, raw: bytes, *, label: str) -> str:
    if not raw or len(raw) > _MAX_RECORD_BYTES:
        raise ExecutionRecordError(f"{label} size is invalid")
    directory_fd = _validate_private_directory(path.parent)
    file_fd: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            file_fd = os.open(path.name, flags, _PRIVATE_FILE_MODE, dir_fd=directory_fd)
        except FileExistsError as exc:
            raise ExecutionRecordError(f"{label} already exists") from exc
        except OSError as exc:
            raise ExecutionRecordError(f"{label} cannot be created safely") from exc
        view = memoryview(raw)
        written = 0
        while written < len(view):
            count = os.write(file_fd, view[written:])
            if count <= 0:
                raise ExecutionRecordError(f"{label} write made no progress")
            written += count
        os.fchmod(file_fd, _PRIVATE_FILE_MODE)
        os.fsync(file_fd)
        opened = os.fstat(file_fd)
        _validate_record_stat(opened, label=label)
        current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise ExecutionRecordError(f"{label} changed while being written")
        os.fsync(directory_fd)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)
    return _sha256_bytes(raw)


def _read_record(path: Path, *, label: str) -> bytes:
    directory_fd = _validate_private_directory(path.parent)
    file_fd: int | None = None
    try:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            file_fd = os.open(path.name, flags, dir_fd=directory_fd)
        except OSError as exc:
            raise ExecutionRecordError(f"{label} cannot be opened safely") from exc
        opened = os.fstat(file_fd)
        _validate_record_stat(opened, label=label)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(8192, _MAX_RECORD_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_RECORD_BYTES:
                raise ExecutionRecordError(f"{label} is too large")
        current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise ExecutionRecordError(f"{label} changed while being read")
        raw = b"".join(chunks)
        if len(raw) != opened.st_size:
            raise ExecutionRecordError(f"{label} size changed while being read")
        return raw
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


def _record_exists(path: Path) -> bool:
    directory_fd = _validate_private_directory(path.parent)
    try:
        try:
            os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True
    finally:
        os.close(directory_fd)


def _require_record_absent(path: Path, *, label: str) -> None:
    if _record_exists(path):
        raise ExecutionRecordError(f"{label} already exists")


def require_fresh_transaction_paths(paths: TransactionPaths) -> None:
    """Reject stale coordination state before consuming the one-shot permit."""

    directory_fd = _validate_private_directory(paths.private_directory)
    try:
        for path in (
            paths.registration,
            paths.acknowledgement,
            paths.compute_claim,
            paths.receipt,
        ):
            try:
                os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ExecutionRecordError(f"stale transaction record exists: {path.name}")
    finally:
        os.close(directory_fd)


def write_registration(path: Path, record: WorkerRegistration) -> str:
    """Publish one immutable, fsynced worker registration."""

    return _write_exclusive(path, registration_bytes(record), label="worker registration")


def read_registration(path: Path) -> WorkerRegistration:
    """Read and strictly parse one immutable worker registration."""

    return parse_registration(_read_record(path, label="worker registration"))


def write_acknowledgement(path: Path, record: GuardianAcknowledgement) -> str:
    """Publish one immutable, fsynced guardian acknowledgement."""

    return _write_exclusive(
        path,
        acknowledgement_bytes(record),
        label="guardian acknowledgement",
    )


def read_acknowledgement(path: Path) -> GuardianAcknowledgement:
    """Read and strictly parse one immutable guardian acknowledgement."""

    return parse_acknowledgement(_read_record(path, label="guardian acknowledgement"))


def write_compute_claim(path: Path, record: ComputeClaim) -> str:
    """Publish one permanent, exclusive, fsynced compute claim."""

    if path != record.paths.compute_claim:
        raise ExecutionIdentityError("compute claim publication path drifted")
    return _write_exclusive(path, compute_claim_bytes(record), label="compute claim")


def read_compute_claim(path: Path) -> ComputeClaimEvidence:
    """Read one immutable compute claim and retain its canonical byte hash."""

    raw = _read_record(path, label="compute claim")
    record = parse_compute_claim(raw)
    if record.paths.compute_claim != path:
        raise ExecutionIdentityError("compute claim self path drifted")
    return ComputeClaimEvidence(record, _sha256_bytes(raw))


def _validate_claim_scratch(path: Path) -> None:
    try:
        observed = path.lstat()
        if path.resolve(strict=True) != path:
            raise ExecutionIdentityError("compute claim worker scratch traverses a symlink")
        entries = tuple(path.iterdir())
    except ExecutionIdentityError:
        raise
    except OSError as exc:
        raise ExecutionIdentityError("compute claim worker scratch is unavailable") from exc
    if (
        not stat.S_ISDIR(observed.st_mode)
        or observed.st_uid != os.geteuid()
        or stat.S_IMODE(observed.st_mode) != _PRIVATE_DIRECTORY_MODE
        or entries
    ):
        raise ExecutionIdentityError("compute claim worker scratch identity or state drifted")


def load_and_validate_compute_claim_for_worker(
    claim_path: Path,
    *,
    release_token: str,
    expected_parent_pid: int,
    expected_absolute_deadline_ns: int,
    expected_allowed_cpus: frozenset[int],
    current_worker_pid: int | None = None,
    identity_reader: IdentityReader = read_process_identity,
    task_affinity_reader: TaskAffinityReader = read_task_affinities,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> ComputeClaimEvidence:
    """Re-read the full durable chain and bind it to the current live worker."""

    worker_pid = os.getpid() if current_worker_pid is None else current_worker_pid
    if (
        isinstance(worker_pid, bool)
        or not isinstance(worker_pid, int)
        or worker_pid <= 1
        or isinstance(expected_parent_pid, bool)
        or expected_parent_pid <= 1
    ):
        raise ExecutionIdentityError("current worker or parent PID is invalid")
    expected_release_hash = _release_token_sha256(release_token)
    first_claim = read_compute_claim(claim_path)
    claim = first_claim.claim
    registration = read_registration(claim.paths.registration)
    acknowledgement = read_acknowledgement(claim.paths.acknowledgement)
    validate_compute_claim_chain(claim, registration, acknowledgement)
    if (
        claim.paths.compute_claim != claim_path
        or claim.absolute_deadline_ns != expected_absolute_deadline_ns
        or claim.allowed_cpus != expected_allowed_cpus
        or claim.release_token_sha256 != expected_release_hash
        or claim.worker.pid != worker_pid
        or claim.supervisor.pid != expected_parent_pid
    ):
        raise ExecutionIdentityError("compute claim bootstrap binding drifted")
    now_ns = clock_ns()
    if (
        isinstance(now_ns, bool)
        or not isinstance(now_ns, int)
        or now_ns < claim.created_monotonic_ns
        or now_ns >= claim.absolute_deadline_ns
    ):
        raise ExecutionDeadlineError("compute claim deadline expired or monotonic clock drifted")
    _require_record_absent(claim.paths.receipt, label="guardian receipt")
    observed_guardian = identity_reader(claim.guardian.pid)
    observed_supervisor = identity_reader(claim.supervisor.pid)
    observed_worker = identity_reader(claim.worker.pid)
    validate_acknowledgement(
        acknowledgement,
        registration,
        observed_guardian=observed_guardian,
        observed_supervisor=observed_supervisor,
        observed_worker=observed_worker,
        task_affinity_reader=task_affinity_reader,
    )
    if observed_worker.pid != worker_pid or observed_worker.ppid != expected_parent_pid:
        raise ExecutionIdentityError("current worker parent identity drifted")
    _validate_claim_scratch(claim.worker_scratch_path)

    # Re-read all three immutable records after live validation so a replaced
    # ACK or claim cannot win the validation-to-import interval unnoticed.
    second_registration = read_registration(claim.paths.registration)
    second_acknowledgement = read_acknowledgement(claim.paths.acknowledgement)
    second_claim = read_compute_claim(claim_path)
    if (
        second_registration != registration
        or second_acknowledgement != acknowledgement
        or second_claim != first_claim
    ):
        raise ExecutionRecordError("compute claim chain changed during worker validation")
    validate_compute_claim_chain(
        second_claim.claim,
        second_registration,
        second_acknowledgement,
    )
    _require_record_absent(claim.paths.receipt, label="guardian receipt")
    if clock_ns() >= claim.absolute_deadline_ns:
        raise ExecutionDeadlineError("compute claim deadline expired before worker import")
    return second_claim


def write_receipt(path: Path, record: GuardianReceipt) -> str:
    """Publish the terminal immutable guardian receipt."""

    return _write_exclusive(path, receipt_bytes(record), label="guardian receipt")


def _release_token_sha256(token: str) -> str:
    # Reuse the bootstrap frame validator, so registration and pipe protocols
    # cannot disagree about the accepted token language.
    start_release_frame(token)
    return _sha256_bytes(token.encode("ascii"))


def make_registration(
    *,
    transaction_id: str,
    absolute_deadline_ns: int,
    allowed_cpus: frozenset[int],
    release_token: str,
    guardian: ProcessIdentity,
    supervisor: ProcessIdentity,
    worker: ProcessIdentity,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> WorkerRegistration:
    """Construct a fully bound registration before publishing it."""

    record = WorkerRegistration(
        transaction_id=_require_transaction_id(transaction_id),
        absolute_deadline_ns=absolute_deadline_ns,
        allowed_cpus=allowed_cpus,
        release_token_sha256=_release_token_sha256(release_token),
        created_monotonic_ns=clock_ns(),
        guardian=guardian,
        supervisor=supervisor,
        worker=worker,
    )
    validate_registration_structure(record)
    return record


def make_acknowledgement(
    registration: WorkerRegistration,
    *,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> GuardianAcknowledgement:
    """Construct an ACK only after live registration validation."""

    record = GuardianAcknowledgement(
        transaction_id=registration.transaction_id,
        absolute_deadline_ns=registration.absolute_deadline_ns,
        registration_sha256=registration_sha256(registration),
        release_token_sha256=registration.release_token_sha256,
        created_monotonic_ns=clock_ns(),
        guardian=registration.guardian,
        supervisor=registration.supervisor,
        worker=registration.worker,
    )
    validate_acknowledgement_structure(record)
    return record


def make_compute_claim(
    *,
    authority: ComputeClaimAuthority,
    paths: TransactionPaths,
    worker_scratch_path: Path,
    registration: WorkerRegistration,
    acknowledgement: GuardianAcknowledgement,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> ComputeClaim:
    """Construct the permanent claim from one already durable ACK chain."""

    record = ComputeClaim(
        transaction_id=registration.transaction_id,
        absolute_deadline_ns=registration.absolute_deadline_ns,
        allowed_cpus=registration.allowed_cpus,
        release_token_sha256=registration.release_token_sha256,
        registration_sha256=registration_sha256(registration),
        acknowledgement_sha256=acknowledgement_sha256(acknowledgement),
        created_monotonic_ns=clock_ns(),
        authority=authority,
        paths=paths,
        worker_scratch_path=worker_scratch_path,
        guardian=registration.guardian,
        supervisor=registration.supervisor,
        worker=registration.worker,
    )
    validate_compute_claim_chain(record, registration, acknowledgement)
    return record


def _sleep_until_poll(
    *,
    absolute_deadline_ns: int,
    poll_interval_ns: int,
    clock_ns: Callable[[], int],
    sleep: Callable[[float], None],
) -> None:
    now_ns = clock_ns()
    if now_ns >= absolute_deadline_ns:
        raise ExecutionDeadlineError("absolute deadline expired during transaction handshake")
    sleep(min(poll_interval_ns, absolute_deadline_ns - now_ns) / 1e9)


def supervisor_register_and_release(
    *,
    paths: TransactionPaths,
    transaction_id: str,
    absolute_deadline_ns: int,
    allowed_cpus: frozenset[int],
    release_token: str,
    guardian: ProcessIdentity,
    worker_pid: int,
    worker_scratch_path: Path,
    claim_authority: ComputeClaimAuthority,
    release_write_fd: int,
    identity_reader: IdentityReader = read_process_identity,
    task_affinity_reader: TaskAffinityReader = read_task_affinities,
    clock_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_ns: int = FROZEN_POLL_INTERVAL_NS,
    send_release: Callable[..., None] = send_start_release,
) -> WorkerRegistration:
    """Supervisor callback: register, ACK, permanently claim, then release.

    On every failure before release, the write end is closed.  The worker
    bootstrap consequently observes EOF and cannot import the worker module.
    """

    released = False
    try:
        _require_record_absent(
            paths.acknowledgement,
            label="guardian acknowledgement before registration",
        )
        _require_record_absent(paths.compute_claim, label="compute claim before registration")
        _require_record_absent(paths.receipt, label="guardian receipt before registration")
        observed_guardian = identity_reader(guardian.pid)
        observed_supervisor = identity_reader(os.getpid())
        observed_worker = identity_reader(worker_pid)
        registration = make_registration(
            transaction_id=transaction_id,
            absolute_deadline_ns=absolute_deadline_ns,
            allowed_cpus=allowed_cpus,
            release_token=release_token,
            guardian=guardian,
            supervisor=observed_supervisor,
            worker=observed_worker,
            clock_ns=clock_ns,
        )
        validate_registration_observation(
            registration,
            expected_transaction_id=transaction_id,
            expected_absolute_deadline_ns=absolute_deadline_ns,
            expected_allowed_cpus=allowed_cpus,
            expected_release_token_sha256=_release_token_sha256(release_token),
            observed_guardian=observed_guardian,
            observed_supervisor=observed_supervisor,
            observed_worker=observed_worker,
            guardian_task_affinities=task_affinity_reader(observed_guardian.pid),
            supervisor_task_affinities=task_affinity_reader(observed_supervisor.pid),
            worker_task_affinities=task_affinity_reader(observed_worker.pid),
        )
        write_registration(paths.registration, registration)
        while not paths.acknowledgement.exists():
            _sleep_until_poll(
                absolute_deadline_ns=absolute_deadline_ns,
                poll_interval_ns=poll_interval_ns,
                clock_ns=clock_ns,
                sleep=sleep,
            )
        acknowledgement = read_acknowledgement(paths.acknowledgement)
        validate_acknowledgement(
            acknowledgement,
            registration,
            observed_guardian=identity_reader(guardian.pid),
            observed_supervisor=identity_reader(observed_supervisor.pid),
            observed_worker=identity_reader(observed_worker.pid),
            task_affinity_reader=task_affinity_reader,
        )
        durable_registration = read_registration(paths.registration)
        durable_acknowledgement = read_acknowledgement(paths.acknowledgement)
        if durable_registration != registration or durable_acknowledgement != acknowledgement:
            raise ExecutionRecordError("registration or ACK changed before compute claim")
        validate_acknowledgement(
            durable_acknowledgement,
            durable_registration,
            observed_guardian=identity_reader(guardian.pid),
            observed_supervisor=identity_reader(observed_supervisor.pid),
            observed_worker=identity_reader(observed_worker.pid),
            task_affinity_reader=task_affinity_reader,
        )
        _require_record_absent(paths.receipt, label="guardian receipt before compute claim")
        _validate_claim_scratch(worker_scratch_path)
        claim = make_compute_claim(
            authority=claim_authority,
            paths=paths,
            worker_scratch_path=worker_scratch_path,
            registration=durable_registration,
            acknowledgement=durable_acknowledgement,
            clock_ns=clock_ns,
        )
        claim_hash = write_compute_claim(paths.compute_claim, claim)
        durable_claim = read_compute_claim(paths.compute_claim)
        if durable_claim.compute_claim_sha256 != claim_hash or durable_claim.claim != claim:
            raise ExecutionRecordError("compute claim changed during durable publication")
        validate_compute_claim_chain(
            durable_claim.claim,
            read_registration(paths.registration),
            read_acknowledgement(paths.acknowledgement),
        )
        validate_registration_observation(
            durable_registration,
            expected_transaction_id=transaction_id,
            expected_absolute_deadline_ns=absolute_deadline_ns,
            expected_allowed_cpus=allowed_cpus,
            expected_release_token_sha256=_release_token_sha256(release_token),
            observed_guardian=identity_reader(guardian.pid),
            observed_supervisor=identity_reader(observed_supervisor.pid),
            observed_worker=identity_reader(observed_worker.pid),
            guardian_task_affinities=task_affinity_reader(guardian.pid),
            supervisor_task_affinities=task_affinity_reader(observed_supervisor.pid),
            worker_task_affinities=task_affinity_reader(observed_worker.pid),
        )
        _require_record_absent(paths.receipt, label="guardian receipt before worker release")
        if clock_ns() >= absolute_deadline_ns:
            raise ExecutionDeadlineError("absolute deadline expired before worker release")
        send_release(release_write_fd, token=release_token)
        released = True
        return registration
    finally:
        if not released:
            with suppress(OSError):
                os.close(release_write_fd)


def guardian_acknowledge_registration(
    *,
    paths: TransactionPaths,
    transaction_id: str,
    absolute_deadline_ns: int,
    allowed_cpus: frozenset[int],
    release_token: str,
    guardian: ProcessIdentity,
    supervisor: ProcessIdentity,
    supervisor_exited: Callable[[], bool],
    identity_reader: IdentityReader = read_process_identity,
    task_affinity_reader: TaskAffinityReader = read_task_affinities,
    clock_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_ns: int = FROZEN_POLL_INTERVAL_NS,
) -> WorkerRegistration:
    """Guardian side: independently validate registration and durably ACK it."""

    while not paths.registration.exists():
        if supervisor_exited():
            raise ExecutionIdentityError("supervisor exited before worker registration")
        _sleep_until_poll(
            absolute_deadline_ns=absolute_deadline_ns,
            poll_interval_ns=poll_interval_ns,
            clock_ns=clock_ns,
            sleep=sleep,
        )
    registration = read_registration(paths.registration)
    observed_guardian = identity_reader(guardian.pid)
    observed_supervisor = identity_reader(supervisor.pid)
    observed_worker = identity_reader(registration.worker.pid)
    validate_registration_observation(
        registration,
        expected_transaction_id=transaction_id,
        expected_absolute_deadline_ns=absolute_deadline_ns,
        expected_allowed_cpus=allowed_cpus,
        expected_release_token_sha256=_release_token_sha256(release_token),
        observed_guardian=observed_guardian,
        observed_supervisor=observed_supervisor,
        observed_worker=observed_worker,
        guardian_task_affinities=task_affinity_reader(observed_guardian.pid),
        supervisor_task_affinities=task_affinity_reader(observed_supervisor.pid),
        worker_task_affinities=task_affinity_reader(observed_worker.pid),
    )
    acknowledgement = make_acknowledgement(registration, clock_ns=clock_ns)
    write_acknowledgement(paths.acknowledgement, acknowledgement)
    return registration


def _child_exited_without_reap(pid: int) -> bool:
    waitid = getattr(os, "waitid", None)
    if waitid is None:
        raise SupervisorLaunchError("waitid with WNOWAIT is required")
    try:
        return waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except InterruptedError:
        return False
    except ChildProcessError as exc:
        raise SupervisorLaunchError("supervisor became non-waitable before final reap") from exc


def spawn_supervisor_command(
    context: GuardianLaunchContext,
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    stdout: int | None = subprocess.DEVNULL,
    stderr: int | None = subprocess.DEVNULL,
) -> subprocess.Popen[bytes]:
    """Start one argv-only supervisor in a fresh session with PDEATHSIG.

    Production integration may inject a launcher with explicit log files; this
    helper intentionally never invokes a shell and never imports chemistry.
    """

    command = tuple(argv)
    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("supervisor argv must be non-empty strings")

    def contain_parent_death() -> None:
        install_parent_death_signal(context.guardian.pid)

    try:
        return subprocess.Popen(
            command,
            shell=False,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            cwd=None if cwd is None else str(cwd),
            env=None if env is None else dict(env),
            close_fds=True,
            preexec_fn=contain_parent_death,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SupervisorLaunchError("supervisor spawn failed") from exc


def _safe_error_code(exc: BaseException) -> str:
    value = type(exc).__name__
    if not value.isascii() or not value or len(value) > _MAX_ERROR_CODE_LENGTH:
        return "unclassified_error"
    return value


def _validate_guardian_result(result: GuardianResult) -> None:
    if not result.group_cleanup_confirmed:
        raise Phase8BExecutionError("process-group cleanup was not confirmed")


def _wait_reap(
    process: SupervisorProcess,
    *,
    deadline_ns: int,
    poll_interval_ns: int,
    clock_ns: Callable[[], int],
    validate_known_processes: Callable[[], None],
) -> int:
    while True:
        # Reap an already-exited supervisor before consulting /proc.  A normal
        # child may be a zombie immediately after the worker group disappears;
        # treating that transient Z state as identity drift would turn a clean
        # run into a false failure.
        try:
            return process.wait(timeout=0.0)
        except subprocess.TimeoutExpired:
            pass
        try:
            validate_known_processes()
        except Exception as validation_error:
            # Close the validation-to-exit race once more.  Preserve the
            # identity/affinity failure only if the supervisor is still live.
            try:
                return process.wait(timeout=0.0)
            except subprocess.TimeoutExpired:
                raise validation_error from None
        remaining_ns = deadline_ns - clock_ns()
        if remaining_ns <= 0:
            raise subprocess.TimeoutExpired(("phase8b-supervisor",), 0)
        timeout_seconds = min(poll_interval_ns, remaining_ns) / 1e9
        try:
            return process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            continue


def _reap_adopted_children() -> None:
    while True:
        try:
            child_pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        except InterruptedError:
            continue
        if child_pid == 0:
            return


def validate_receipt_structure(record: GuardianReceipt) -> None:
    """Validate bounded receipt fields before they become durable evidence."""

    _require_transaction_id(record.transaction_id)
    _require_sha256(record.permit_sha256, label="permit_sha256")
    _require_positive_int(record.absolute_deadline_ns, label="absolute_deadline_ns")
    _require_positive_int(record.started_monotonic_ns, label="started_monotonic_ns")
    _require_positive_int(record.finished_monotonic_ns, label="finished_monotonic_ns")
    if record.finished_monotonic_ns < record.started_monotonic_ns:
        raise ExecutionRecordError("receipt monotonic interval is reversed")
    if record.outcome not in {
        "clean",
        "permit_consumption_failed",
        "authority_failed",
        "spawn_failed",
        "registration_failed",
        "worker_guard_failed",
        "supervisor_nonzero",
        "cleanup_failed",
        "internal_error",
    }:
        raise ExecutionRecordError("receipt outcome is invalid")
    if record.error_code is not None and (
        not record.error_code.isascii()
        or not record.error_code
        or len(record.error_code) > _MAX_ERROR_CODE_LENGTH
    ):
        raise ExecutionRecordError("receipt error code is invalid")
    if record.worker_registration_sha256 is not None:
        _require_sha256(
            record.worker_registration_sha256,
            label="worker_registration_sha256",
        )
    if record.compute_claim_sha256 is not None:
        _require_sha256(record.compute_claim_sha256, label="compute_claim_sha256")
        if record.worker_registration_sha256 is None or not record.acknowledgement_published:
            raise ExecutionRecordError("receipt compute claim lacks its registration/ACK chain")
    if record.outcome == "clean" and (
        record.error_code is not None
        or record.finished_monotonic_ns >= record.absolute_deadline_ns
        or not record.authority_validated
        or not record.acknowledgement_published
        or record.worker_registration_sha256 is None
        or record.compute_claim_sha256 is None
        or record.supervisor_returncode != 0
        or record.supervisor is None
        or record.worker is None
        or record.worker_guardian_result is None
        or record.worker_guardian_result.outcome != "clean"
        or not record.worker_guardian_result.group_cleanup_confirmed
    ):
        raise ExecutionRecordError("clean receipt lacks success evidence")


def run_guardian_transaction(
    *,
    transaction_id: str,
    paths: TransactionPaths,
    release_token: str,
    consume_permit: Callable[[], ConsumedPermitEvidence],
    recover_consumed_permit: Callable[[], ConsumedPermitEvidence | None],
    validate_consumed_authority: Callable[[object], object],
    spawn_supervisor: SpawnSupervisor,
    publish_final_acceptance: PublishFinalAcceptance,
    policy: TransactionPolicy = _FROZEN_TRANSACTION_POLICY,
    identity_reader: IdentityReader = read_process_identity,
    task_affinity_reader: TaskAffinityReader = read_task_affinities,
    child_exited_without_reap: ChildExitObserver = _child_exited_without_reap,
    enable_subreaper: Callable[[], None] = enable_child_subreaper,
    guard_group: Callable[..., GuardianResult] = guard_process_group,
    clock_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
    reap_adopted_children: Callable[[], None] = _reap_adopted_children,
) -> GuardianTransactionResult:
    """Run the generic outer-guardian transaction around one supervisor.

    ``consume_permit`` is called exactly once and always before
    ``validate_consumed_authority`` and ``spawn_supervisor``.  The mandatory
    validator is the production integration point for exact request, payload,
    source, path, candidate, endpoint, protocol, resource, and electron-count
    cross-checks.  If consumption raises after its irreversible O_EXCL point,
    ``recover_consumed_permit`` must read and strictly validate the consumed
    record; observed consumption then produces a terminal failure receipt and
    never reaches spawn.  An exception is propagated without a receipt only
    when recovery confirms that no consumed permit exists.  Only after a clean
    receipt is fsynced may ``publish_final_acceptance`` create final
    ``success.json`` and publish ``_SUCCESS`` last; inner execution must leave
    only provisional output.  The caller decides how a non-clean outcome maps
    to its CLI exit status.
    """

    transaction = _require_transaction_id(transaction_id)
    if transaction != FROZEN_TRANSACTION_ID:
        raise Phase8BExecutionError("Phase 8B transaction identity drifted")
    ensure_frozen_policy(policy)
    release_hash = _release_token_sha256(release_token)
    del release_hash  # validated here; the digest is rederived for the ACK.
    require_fresh_transaction_paths(paths)
    started_ns = clock_ns()
    absolute_deadline_ns = policy.choose_absolute_deadline(clock_ns=lambda: started_ns)
    enable_subreaper()
    guardian = identity_reader(os.getpid())
    _validate_observed_identity(
        guardian,
        guardian,
        label="guardian",
        allowed_cpus=policy.allowed_cpus,
        expected_parent_pid=None,
        task_affinities=task_affinity_reader(guardian.pid),
    )

    # This is the authorization linearization seam.  Nothing below can restore
    # a permit, and the injected spawn callback is unreachable before it.
    consumption_error: BaseException | None = None
    try:
        consumed_evidence = consume_permit()
        if not isinstance(consumed_evidence, ConsumedPermitEvidence):
            raise TypeError("consume_permit must return ConsumedPermitEvidence")
    except Exception as exc:
        recovered_evidence = recover_consumed_permit()
        if recovered_evidence is None:
            raise
        if not isinstance(recovered_evidence, ConsumedPermitEvidence):
            raise TypeError(
                "recover_consumed_permit must return ConsumedPermitEvidence or None"
            ) from exc
        consumed_evidence = recovered_evidence
        consumption_error = exc
    permit_sha256 = consumed_evidence.permit_sha256

    supervisor_process: SupervisorProcess | None = None
    supervisor: ProcessIdentity | None = None
    worker: ProcessIdentity | None = None
    worker_guard_result: GuardianResult | None = None
    supervisor_guard_result: GuardianResult | None = None
    supervisor_returncode: int | None = None
    authority_validated = False
    validated_authority: object | None = None
    acknowledgement_published = False
    worker_registration_hash: str | None = None
    compute_claim_hash: str | None = None
    outcome: ReceiptOutcome = "internal_error"
    error_code: str | None = None

    context = GuardianLaunchContext(
        transaction_id=transaction,
        paths=paths,
        policy=policy,
        absolute_deadline_ns=absolute_deadline_ns,
        release_token=release_token,
        guardian=guardian,
    )
    try:
        if consumption_error is not None:
            outcome = "permit_consumption_failed"
            error_code = _safe_error_code(consumption_error)
        else:
            try:
                validated_authority = validate_consumed_authority(consumed_evidence.authority)
                if validated_authority is None:
                    raise TypeError(
                        "validate_consumed_authority must return exact validation evidence"
                    )
            except Exception as exc:
                outcome = "authority_failed"
                error_code = _safe_error_code(exc)
            else:
                authority_validated = True
        if consumption_error is not None:
            raise Phase8BExecutionError("permit consumption did not finish cleanly")
        if not authority_validated:
            raise ExecutionIdentityError("consumed authority validation failed")
        supervisor_process = spawn_supervisor(context)
        if (
            isinstance(supervisor_process.pid, bool)
            or not isinstance(supervisor_process.pid, int)
            or supervisor_process.pid <= 1
        ):
            raise SupervisorLaunchError("supervisor launcher returned an invalid PID")
        supervisor = identity_reader(supervisor_process.pid)
        _validate_observed_identity(
            supervisor,
            supervisor,
            label="supervisor",
            allowed_cpus=policy.allowed_cpus,
            expected_parent_pid=guardian.pid,
            task_affinities=task_affinity_reader(supervisor.pid),
        )
        registration = guardian_acknowledge_registration(
            paths=paths,
            transaction_id=transaction,
            absolute_deadline_ns=absolute_deadline_ns,
            allowed_cpus=policy.allowed_cpus,
            release_token=release_token,
            guardian=guardian,
            supervisor=supervisor,
            supervisor_exited=lambda: child_exited_without_reap(supervisor.pid),
            identity_reader=identity_reader,
            task_affinity_reader=task_affinity_reader,
            clock_ns=clock_ns,
            sleep=sleep,
            poll_interval_ns=policy.poll_interval_ns,
        )
        worker = registration.worker
        worker_registration_hash = registration_sha256(registration)
        acknowledgement_published = True

        def validate_known_processes() -> None:
            observed_guardian = identity_reader(guardian.pid)
            observed_supervisor = identity_reader(supervisor.pid)
            _validate_observed_identity(
                guardian,
                observed_guardian,
                label="guardian",
                allowed_cpus=policy.allowed_cpus,
                expected_parent_pid=None,
                task_affinities=task_affinity_reader(observed_guardian.pid),
            )
            _validate_observed_identity(
                supervisor,
                observed_supervisor,
                label="supervisor",
                allowed_cpus=policy.allowed_cpus,
                expected_parent_pid=guardian.pid,
                task_affinities=task_affinity_reader(observed_supervisor.pid),
            )

        outer_monitor_error: BaseException | None = None

        def worker_abort_requested() -> bool:
            nonlocal outer_monitor_error
            try:
                if child_exited_without_reap(supervisor.pid):
                    return True
                validate_known_processes()
            except Exception as exc:
                outer_monitor_error = exc
                return True
            return False

        worker_guard_result = guard_group(
            worker,
            policy=policy.guardian_policy(absolute_deadline_ns),
            abort_requested=worker_abort_requested,
            clock_ns=clock_ns,
            sleep=sleep,
            forbidden_pgids=frozenset({guardian.pgid, supervisor.pgid}),
        )
        _validate_guardian_result(worker_guard_result)
        if outer_monitor_error is not None:
            outcome = "worker_guard_failed"
            error_code = _safe_error_code(outer_monitor_error)
            raise Phase8BExecutionError("guardian/supervisor identity or affinity drifted")
        if worker_guard_result.outcome != "clean":
            outcome = "worker_guard_failed"
        cleanup_deadline_ns = absolute_deadline_ns + policy.terminate_grace_ns + policy.kill_wait_ns
        try:
            supervisor_returncode = _wait_reap(
                supervisor_process,
                deadline_ns=cleanup_deadline_ns,
                poll_interval_ns=policy.poll_interval_ns,
                clock_ns=clock_ns,
                validate_known_processes=validate_known_processes,
            )
        except subprocess.TimeoutExpired:
            supervisor_guard_result = guard_group(
                supervisor,
                policy=GuardianPolicy(
                    absolute_deadline_ns=clock_ns(),
                    allowed_cpus=policy.allowed_cpus,
                    terminate_grace_ns=policy.terminate_grace_ns,
                    kill_wait_ns=policy.kill_wait_ns,
                    poll_interval_ns=policy.poll_interval_ns,
                ),
                abort_requested=lambda: True,
                clock_ns=clock_ns,
                sleep=sleep,
                forbidden_pgids=frozenset({guardian.pgid, worker.pgid}),
            )
            _validate_guardian_result(supervisor_guard_result)
            supervisor_returncode = supervisor_process.wait(
                timeout=(policy.terminate_grace_ns + policy.kill_wait_ns) / 1e9 + 1.0
            )
        if worker_guard_result.outcome == "clean" and supervisor_returncode == 0:
            outcome = "clean"
        elif worker_guard_result.outcome == "clean":
            outcome = "supervisor_nonzero"
    except SupervisorLaunchError as exc:
        outcome = "spawn_failed"
        error_code = _safe_error_code(exc)
    except (ExecutionRecordError, ExecutionIdentityError, ExecutionDeadlineError) as exc:
        if outcome != "authority_failed":
            outcome = "registration_failed"
            error_code = _safe_error_code(exc)
    except Phase8BExecutionError as exc:
        if outcome not in {"permit_consumption_failed", "worker_guard_failed"}:
            outcome = "cleanup_failed"
            error_code = _safe_error_code(exc)
    except Exception as exc:  # fail closed at the transaction boundary
        outcome = "internal_error"
        error_code = _safe_error_code(exc)
    finally:
        if (
            supervisor_process is not None
            and supervisor is not None
            and supervisor_returncode is None
        ):
            try:
                supervisor_guard_result = guard_group(
                    supervisor,
                    policy=GuardianPolicy(
                        absolute_deadline_ns=min(clock_ns(), absolute_deadline_ns),
                        allowed_cpus=policy.allowed_cpus,
                        terminate_grace_ns=policy.terminate_grace_ns,
                        kill_wait_ns=policy.kill_wait_ns,
                        poll_interval_ns=policy.poll_interval_ns,
                    ),
                    abort_requested=lambda: True,
                    clock_ns=clock_ns,
                    sleep=sleep,
                    forbidden_pgids=frozenset(
                        {guardian.pgid, *(() if worker is None else (worker.pgid,))}
                    ),
                )
                _validate_guardian_result(supervisor_guard_result)
                supervisor_returncode = supervisor_process.wait(
                    timeout=(policy.terminate_grace_ns + policy.kill_wait_ns) / 1e9 + 1.0
                )
            except Exception as exc:
                outcome = "cleanup_failed"
                error_code = _safe_error_code(exc)
        try:
            reap_adopted_children()
        except Exception as exc:
            outcome = "cleanup_failed"
            error_code = _safe_error_code(exc)

    if outcome == "clean":
        try:
            observed_guardian = identity_reader(guardian.pid)
            _validate_observed_identity(
                guardian,
                observed_guardian,
                label="guardian",
                allowed_cpus=policy.allowed_cpus,
                expected_parent_pid=None,
                task_affinities=task_affinity_reader(observed_guardian.pid),
            )
        except Exception as exc:
            outcome = "cleanup_failed"
            error_code = _safe_error_code(exc)

    if _record_exists(paths.compute_claim):
        try:
            durable_claim = read_compute_claim(paths.compute_claim)
            durable_registration = read_registration(paths.registration)
            durable_acknowledgement = read_acknowledgement(paths.acknowledgement)
            validate_compute_claim_chain(
                durable_claim.claim,
                durable_registration,
                durable_acknowledgement,
            )
            claim = durable_claim.claim
            if (
                claim.transaction_id != transaction
                or claim.absolute_deadline_ns != absolute_deadline_ns
                or claim.authority.permit_sha256 != permit_sha256
                or not same_process(claim.guardian, guardian)
                or supervisor is None
                or not same_process(claim.supervisor, supervisor)
                or worker is None
                or not same_process(claim.worker, worker)
                or worker_registration_hash != claim.registration_sha256
            ):
                raise ExecutionIdentityError("terminal compute claim binding drifted")
            compute_claim_hash = durable_claim.compute_claim_sha256
        except Exception as exc:
            outcome = "cleanup_failed"
            error_code = _safe_error_code(exc)
            compute_claim_hash = None
    elif outcome == "clean":
        outcome = "cleanup_failed"
        error_code = "compute_claim_missing"

    finished_ns = max(started_ns, clock_ns())
    if outcome == "clean" and finished_ns >= absolute_deadline_ns:
        outcome = "cleanup_failed"
        error_code = "absolute_deadline_exceeded"

    if outcome == "clean":
        error_code = None
    elif error_code is None:
        error_code = outcome
    receipt = GuardianReceipt(
        transaction_id=transaction,
        permit_sha256=permit_sha256,
        absolute_deadline_ns=absolute_deadline_ns,
        started_monotonic_ns=started_ns,
        finished_monotonic_ns=finished_ns,
        outcome=outcome,
        error_code=error_code,
        authority_validated=authority_validated,
        acknowledgement_published=acknowledgement_published,
        worker_registration_sha256=worker_registration_hash,
        compute_claim_sha256=compute_claim_hash,
        supervisor_returncode=supervisor_returncode,
        guardian=guardian,
        supervisor=supervisor,
        worker=worker,
        worker_guardian_result=worker_guard_result,
        supervisor_guardian_result=supervisor_guard_result,
    )
    receipt_raw = receipt_bytes(receipt)
    receipt_hash = _write_exclusive(paths.receipt, receipt_raw, label="guardian receipt")
    final_acceptance: PublishedFinalAcceptance | None = None
    if receipt.succeeded:
        if worker_registration_hash is None:  # guarded by receipt validation
            raise ExecutionRecordError("clean receipt lacks worker registration hash")
        if compute_claim_hash is None:  # guarded by receipt validation
            raise ExecutionRecordError("clean receipt lacks compute claim hash")
        if validated_authority is None:  # guarded by receipt validation
            raise ExecutionRecordError("clean receipt lacks exact authority evidence")
        final_acceptance = publish_final_acceptance(
            FinalAcceptanceContext(
                transaction_id=transaction,
                permit_sha256=permit_sha256,
                worker_registration_sha256=worker_registration_hash,
                compute_claim_sha256=compute_claim_hash,
                guardian_receipt=receipt,
                guardian_receipt_sha256=receipt_hash,
                consumed_authority=consumed_evidence.authority,
                validated_authority=validated_authority,
            )
        )
        if not isinstance(final_acceptance, PublishedFinalAcceptance):
            raise TypeError("publish_final_acceptance must return PublishedFinalAcceptance")
    return GuardianTransactionResult(
        receipt=receipt,
        receipt_sha256=receipt_hash,
        final_acceptance=final_acceptance,
    )


def ensure_frozen_policy(policy: TransactionPolicy) -> None:
    """Fail if production integration tries to widen any frozen resource."""

    if policy != TransactionPolicy():
        raise Phase8BExecutionError("Phase 8B transaction policy drifted from frozen resources")
    if not math.isfinite(policy.timeout_ns / 1e9):
        raise Phase8BExecutionError("Phase 8B timeout cannot be represented")
