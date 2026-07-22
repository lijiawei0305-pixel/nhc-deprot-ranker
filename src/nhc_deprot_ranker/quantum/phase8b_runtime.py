"""Production integration for the one frozen Phase 8B guardian transaction.

This file is the only server entry point.  It is deliberately standard-library
only until the pre-import worker handshake releases ``worker.py``; importing it
never imports PySCF, geomeTRIC, or a dispersion backend.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

# ``python -I /absolute/path/phase8b_runtime.py`` intentionally has no project
# path on sys.path.  The exact, source-hashed entry file adds only its own
# deployed ``src`` root before importing other hash-closed project modules.
if __package__ in {None, ""}:  # pragma: no cover - exercised by server argv tests
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum.linux_guardian import (
    read_process_identity,
    require_affinity,
)
from nhc_deprot_ranker.quantum.phase8b_authority import (
    ExactPhase8BAuthority,
    Phase8BBundleIdentity,
    Phase8BRequestLike,
    validate_exact_phase8b_authority,
    validate_phase8b_transport_bundle,
)
from nhc_deprot_ranker.quantum.phase8b_execution import (
    FROZEN_ALLOWED_CPUS,
    FROZEN_TRANSACTION_ID,
    ComputeClaimAuthority,
    ConsumedPermitEvidence,
    FinalAcceptanceContext,
    GuardianLaunchContext,
    PublishedFinalAcceptance,
    SupervisorLaunchError,
    SupervisorProcess,
    TransactionPaths,
    run_guardian_transaction,
    spawn_supervisor_command,
    supervisor_register_and_release,
)
from nhc_deprot_ranker.quantum.phase8b_permit import (
    FROZEN_ATTEMPT_ID,
    FROZEN_CONSUMED_RELATIVE,
    FROZEN_READY_RELATIVE,
    ConsumedPhase8BPermit,
    consume_phase8b_permit,
    load_consumed_phase8b_permit,
)

FINAL_SUCCESS_SCHEMA_VERSION: Final = "nhc-phase8b-final-success-v1"
RUNTIME_RECEIPT_SCHEMA_VERSION: Final = "nhc-phase8b-runtime-receipt-v1"
_PRIVATE_MODE: Final = 0o600
_MAX_JSON_BYTES: Final = 2 * 1024 * 1024
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")


class Phase8BRuntimeError(RuntimeError):
    """The exact production transaction failed closed."""


@dataclass(slots=True)
class _AuthoritySession:
    consumed: ConsumedPhase8BPermit
    bundle: Phase8BBundleIdentity
    request: runner.TwoEndpointRequest | None = None
    exact: ExactPhase8BAuthority | None = None


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _close_fd(descriptor: int) -> None:
    with suppress(OSError):
        os.close(descriptor)


def _open_exact_directory(path: Path, *, label: str) -> int:
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise Phase8BRuntimeError(f"{label} parent path is unsafe")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor: int | None = None
    try:
        descriptor = os.open("/", flags)
        for component in path.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            try:
                observed = os.fstat(next_descriptor)
            except OSError:
                _close_fd(next_descriptor)
                raise
            if not stat.S_ISDIR(observed.st_mode):
                _close_fd(next_descriptor)
                raise Phase8BRuntimeError(f"{label} parent path is unsafe")
            _close_fd(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Phase8BRuntimeError:
        if descriptor is not None:
            _close_fd(descriptor)
        raise
    except OSError as exc:
        if descriptor is not None:
            _close_fd(descriptor)
        raise Phase8BRuntimeError(f"{label} parent cannot be opened safely") from exc


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise Phase8BRuntimeError(f"{label} must be a lowercase SHA256")
    return value


def _sha256_argument(value: str) -> str:
    try:
        return _require_sha256(value, label="command-line value")
    except Phase8BRuntimeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, object]:
    if not raw or len(raw) > _MAX_JSON_BYTES:
        raise Phase8BRuntimeError(f"{label} byte size is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase8BRuntimeError(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise Phase8BRuntimeError(f"{label} contains non-finite number: {value}")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except Phase8BRuntimeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise Phase8BRuntimeError(f"{label} is not strict JSON") from exc
    if not isinstance(payload, dict):
        raise Phase8BRuntimeError(f"{label} must be an object")
    return cast(dict[str, object], payload)


def _transaction_paths(run_root: Path) -> TransactionPaths:
    private = run_root / "private"
    return TransactionPaths(
        registration=(private / "worker_registration.json").resolve(),
        acknowledgement=(private / "guardian_acknowledgement.json").resolve(),
        compute_claim=(private / "compute_claim.json").resolve(),
        receipt=(private / "guardian_receipt.json").resolve(),
    )


def _validate_bundle_hashes(bundle: Phase8BBundleIdentity) -> None:
    for label, value in (
        ("transport inventory SHA256", bundle.transport_inventory_sha256),
        ("payload manifest SHA256", bundle.payload_manifest_sha256),
        ("permit SHA256", bundle.permit_sha256),
        ("request SHA256", bundle.request_sha256),
        ("runner source SHA256", bundle.runner_source_sha256),
    ):
        _require_sha256(value, label=label)


def _permit_arguments(bundle: Phase8BBundleIdentity) -> dict[str, str]:
    _validate_bundle_hashes(bundle)
    return {
        "expected_permit_sha256": bundle.permit_sha256,
        "expected_request_sha256": bundle.request_sha256,
        "expected_runner_source_sha256": bundle.runner_source_sha256,
        "expected_payload_manifest_sha256": bundle.payload_manifest_sha256,
    }


def _load_exact_session(
    session: _AuthoritySession, *, require_output_absent: bool
) -> ExactPhase8BAuthority:
    request = runner.load_two_endpoint_request(session.consumed.permit.request_path)
    if request.runner_source_sha256 != runner.current_runner_source_sha256():
        raise Phase8BRuntimeError("deployed runner source closure drifted")
    if (
        session.bundle.request_sha256 != session.consumed.permit.request_sha256
        or session.bundle.runner_source_sha256 != session.consumed.permit.runner_source_sha256
        or session.bundle.payload_manifest_sha256 != session.consumed.permit.payload_manifest_sha256
        or session.bundle.permit_sha256 != session.consumed.permit.permit_sha256
    ):
        raise Phase8BRuntimeError("transport, permit, request, and source hash layers disagree")
    runner._validate_frozen_120_electron_pair(  # pyright: ignore[reportPrivateUsage]
        request.cation, request.neutral
    )
    exact = validate_exact_phase8b_authority(
        cast(Phase8BRequestLike, request),
        session.consumed,
        output_root=session.consumed.permit.output_root,
        attempt_id=FROZEN_ATTEMPT_ID,
        expected_source_relative_paths=runner._RUNNER_SOURCE_RELATIVE_PATHS,  # pyright: ignore[reportPrivateUsage]
        require_output_absent=require_output_absent,
    )
    session.request = request
    session.exact = exact
    return exact


def _authorization_argv(
    session: _AuthoritySession,
    absolute_deadline_ns: int,
    release_token: str,
) -> tuple[str, ...]:
    permit = session.consumed.permit
    return (
        "--consumed-permit-path",
        str(permit.consumed_path),
        "--expected-permit-sha256",
        session.bundle.permit_sha256,
        "--expected-request-sha256",
        session.bundle.request_sha256,
        "--expected-runner-source-sha256",
        session.bundle.runner_source_sha256,
        "--expected-payload-manifest-sha256",
        session.bundle.payload_manifest_sha256,
        "--expected-transport-inventory-sha256",
        session.bundle.transport_inventory_sha256,
        "--compute-claim-path",
        str(_transaction_paths(permit.run_root).compute_claim),
        "--authorized-output-root",
        str(permit.output_root),
        "--absolute-deadline-ns",
        str(absolute_deadline_ns),
        "--release-token",
        release_token,
    )


def _run_supervisor(
    *,
    run_root: Path,
    bundle: Phase8BBundleIdentity,
    absolute_deadline_ns: int,
    release_token: str,
    guardian_pid: int,
) -> int:
    runner._ensure_execution_authorized()  # pyright: ignore[reportPrivateUsage]
    _validate_bundle_hashes(bundle)
    consumed = load_consumed_phase8b_permit(
        (run_root / FROZEN_CONSUMED_RELATIVE).resolve(),
        **_permit_arguments(bundle),
    )
    session = _AuthoritySession(consumed=consumed, bundle=bundle)
    exact = _load_exact_session(session, require_output_absent=True)
    request = session.request
    if request is None:
        raise Phase8BRuntimeError("supervisor request validation produced no request")
    guardian = read_process_identity(guardian_pid)
    paths = _transaction_paths(run_root)
    claim_authority = ComputeClaimAuthority(
        transport_inventory_sha256=bundle.transport_inventory_sha256,
        payload_manifest_sha256=exact.payload_manifest_sha256,
        permit_sha256=exact.permit_sha256,
        request_sha256=exact.request_sha256,
        runner_source_sha256=exact.runner_source_sha256,
        protocol_sha256=request.protocol_sha256,
        resources_sha256=exact.resources_sha256,
        cation_xyz_sha256=request.cation.xyz_sha256,
        neutral_xyz_sha256=request.neutral.xyz_sha256,
        endpoint_atom_map_sha256=exact.endpoint_atom_map_sha256,
        legacy_atom_map_sha256=exact.legacy_atom_map_sha256,
        geometry_validation_sha256=exact.geometry_validation_sha256,
        electron_count=exact.electron_count,
        request_id=exact.request_id,
        inchikey=exact.inchikey,
        attempt_id=exact.attempt_id,
        project_root=Path(exact.project_root),
        run_root=Path(exact.run_root),
        request_path=Path(exact.request_path),
        output_root=Path(exact.output_root),
    )
    read_fd, write_fd = os.pipe()
    os.set_inheritable(read_fd, True)
    os.set_inheritable(write_fd, False)

    def register_and_release(worker_pid: int, worker_pgid: int, worker_scratch_path: Path) -> None:
        if worker_pid != worker_pgid:
            raise Phase8BRuntimeError("worker PID and PGID differ before registration")
        supervisor_register_and_release(
            paths=paths,
            transaction_id=FROZEN_TRANSACTION_ID,
            absolute_deadline_ns=absolute_deadline_ns,
            allowed_cpus=FROZEN_ALLOWED_CPUS,
            release_token=release_token,
            guardian=guardian,
            worker_pid=worker_pid,
            worker_scratch_path=worker_scratch_path,
            claim_authority=claim_authority,
            release_write_fd=write_fd,
        )

    launch = runner.Phase8BWorkerLaunch(
        start_read_fd=read_fd,
        release_write_fd=write_fd,
        release_token=release_token,
        absolute_deadline_ns=absolute_deadline_ns,
        compute_claim_path=paths.compute_claim,
        on_process_started=register_and_release,
        authorization_argv=_authorization_argv(session, absolute_deadline_ns, release_token),
    )
    try:
        runner.run_phase8b_supervisor(
            request,
            consumed.permit.output_root,
            authority=exact,
            worker_launch=launch,
        )
    except runner.TwoEndpointRunError as exc:
        return int(exc.exit_code)
    return 0


def _read_exact_file(path: Path, *, expected_mode: int, label: str) -> bytes:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise Phase8BRuntimeError(f"{label} path is unsafe")
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = _open_exact_directory(path.parent, label=label)
        directory_stat = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise Phase8BRuntimeError(f"{label} parent is not a directory")
        file_fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        opened = os.fstat(file_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != expected_mode
            or opened.st_size <= 0
            or opened.st_size > _MAX_JSON_BYTES
        ):
            raise Phase8BRuntimeError(f"{label} filesystem identity drifted")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                raise Phase8BRuntimeError(f"{label} changed size while being read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_fd, 1):
            raise Phase8BRuntimeError(f"{label} grew while being read")
        finished = os.fstat(file_fd)
        current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        opened_identity = tuple(getattr(opened, field) for field in stable_fields)
        if (
            tuple(getattr(finished, field) for field in stable_fields) != opened_identity
            or tuple(getattr(current, field) for field in stable_fields) != opened_identity
        ):
            raise Phase8BRuntimeError(f"{label} changed while being read")
        return b"".join(chunks)
    except Phase8BRuntimeError:
        raise
    except OSError as exc:
        raise Phase8BRuntimeError(f"{label} cannot be read safely") from exc
    finally:
        if file_fd is not None:
            _close_fd(file_fd)
        if directory_fd is not None:
            _close_fd(directory_fd)


def _validate_supervisor_success_binding(success_raw: bytes, marker_raw: bytes) -> str:
    marker = _strict_json_object(marker_raw, label="supervisor success marker")
    if marker_raw != _canonical_json_bytes(marker):
        raise Phase8BRuntimeError("supervisor success marker is not canonical JSON")
    if set(marker) != {"schema_version", "supervisor_success_sha256"}:
        raise Phase8BRuntimeError("supervisor success marker fields drifted")
    if marker["schema_version"] != runner.SUPERVISOR_SUCCESS_SCHEMA_VERSION:
        raise Phase8BRuntimeError("supervisor success marker schema drifted")
    expected = _require_sha256(
        marker["supervisor_success_sha256"],
        label="supervisor success marker hash",
    )
    observed = _sha256_bytes(success_raw)
    if observed != expected:
        raise Phase8BRuntimeError("supervisor success marker hash mismatch")
    return observed


def _exclusive_write(path: Path, raw: bytes, *, mode: int) -> str:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        mode,
    )
    try:
        view = memoryview(raw)
        offset = 0
        while offset < len(view):
            count = os.write(descriptor, view[offset:])
            if count <= 0:
                raise Phase8BRuntimeError("final acceptance write made no progress")
            offset += count
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return _sha256_bytes(raw)


def _open_private_log(path: Path, *, label: str) -> int:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            _PRIVATE_MODE,
        )
    except OSError as exc:
        raise SupervisorLaunchError(f"{label} could not be created") from exc
    try:
        os.fchmod(descriptor, _PRIVATE_MODE)
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
            or stat.S_IMODE(observed.st_mode) != _PRIVATE_MODE
        ):
            raise SupervisorLaunchError(f"{label} filesystem identity drifted")
    except Exception:
        _close_fd(descriptor)
        raise
    return descriptor


def _open_supervisor_logs(run_root: Path) -> tuple[int, int]:
    stdout_fd: int | None = None
    try:
        stdout_fd = _open_private_log(
            run_root / "private/supervisor.stdout.log",
            label="supervisor stdout log",
        )
        stderr_fd = _open_private_log(
            run_root / "private/supervisor.stderr.log",
            label="supervisor stderr log",
        )
    except Exception:
        if stdout_fd is not None:
            _close_fd(stdout_fd)
        raise
    return stdout_fd, stderr_fd


def _redirect_guardian_log(run_root: Path) -> None:
    descriptor = _open_private_log(
        run_root / "private/guardian.log",
        label="guardian log",
    )
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(descriptor, sys.stdout.fileno())
        os.dup2(descriptor, sys.stderr.fileno())
    except Exception as exc:
        raise SupervisorLaunchError("guardian log redirection failed") from exc
    finally:
        _close_fd(descriptor)


def _publish_final_acceptance(
    context: FinalAcceptanceContext,
    *,
    session: _AuthoritySession,
) -> PublishedFinalAcceptance:
    exact = session.exact
    request = session.request
    if (
        exact is None
        or request is None
        or context.consumed_authority is not session
        or context.validated_authority != exact
        or context.transaction_id != FROZEN_ATTEMPT_ID
        or context.permit_sha256 != session.bundle.permit_sha256
    ):
        raise Phase8BRuntimeError("final acceptance context disagrees with exact authority")
    consumed = load_consumed_phase8b_permit(
        session.consumed.permit.consumed_path,
        **_permit_arguments(session.bundle),
    )
    if consumed.consumed_sha256 != context.permit_sha256:
        raise Phase8BRuntimeError("consumed permit drifted before final acceptance")
    output_root = consumed.permit.output_root
    expected_top = {"attempts", "supervisor_success.json", "_SUPERVISOR_SUCCESS"}
    if output_root.is_symlink() or {path.name for path in output_root.iterdir()} != expected_top:
        raise Phase8BRuntimeError("provisional output file set drifted")
    initial_supervisor_success_raw = _read_exact_file(
        output_root / "supervisor_success.json",
        expected_mode=_PRIVATE_MODE,
        label="supervisor success",
    )
    initial_supervisor_marker_raw = _read_exact_file(
        output_root / "_SUPERVISOR_SUCCESS",
        expected_mode=_PRIVATE_MODE,
        label="supervisor success marker",
    )
    _validate_supervisor_success_binding(
        initial_supervisor_success_raw,
        initial_supervisor_marker_raw,
    )
    provisional = runner._resume_if_valid(  # pyright: ignore[reportPrivateUsage]
        request=request,
        output_root=output_root,
        require_supervision=True,
        marker_name="_SUPERVISOR_SUCCESS",
        success_name="supervisor_success.json",
        success_schema_version=runner.SUPERVISOR_SUCCESS_SCHEMA_VERSION,
        marker_hash_key="supervisor_success_sha256",
    )
    supervisor_success_raw = _read_exact_file(
        output_root / "supervisor_success.json",
        expected_mode=_PRIVATE_MODE,
        label="supervisor success",
    )
    supervisor_marker_raw = _read_exact_file(
        output_root / "_SUPERVISOR_SUCCESS",
        expected_mode=_PRIVATE_MODE,
        label="supervisor success marker",
    )
    supervisor_success_sha256 = _validate_supervisor_success_binding(
        supervisor_success_raw,
        supervisor_marker_raw,
    )
    if (
        supervisor_success_raw != initial_supervisor_success_raw
        or supervisor_marker_raw != initial_supervisor_marker_raw
    ):
        raise Phase8BRuntimeError("provisional success snapshot changed during revalidation")
    if provisional is None or provisional.attempt_id != FROZEN_ATTEMPT_ID:
        raise Phase8BRuntimeError("provisional output could not be revalidated")
    receipt_raw = _read_exact_file(
        _transaction_paths(consumed.permit.run_root).receipt,
        expected_mode=_PRIVATE_MODE,
        label="guardian receipt",
    )
    registration_raw = _read_exact_file(
        _transaction_paths(consumed.permit.run_root).registration,
        expected_mode=_PRIVATE_MODE,
        label="worker registration",
    )
    compute_claim_raw = _read_exact_file(
        _transaction_paths(consumed.permit.run_root).compute_claim,
        expected_mode=_PRIVATE_MODE,
        label="compute claim",
    )
    if (
        _sha256_bytes(receipt_raw) != context.guardian_receipt_sha256
        or _sha256_bytes(registration_raw) != context.worker_registration_sha256
        or _sha256_bytes(compute_claim_raw) != context.compute_claim_sha256
        or context.guardian_receipt.compute_claim_sha256 != context.compute_claim_sha256
    ):
        raise Phase8BRuntimeError("guardian receipt, registration, or compute claim hash drifted")
    success_payload = {
        "schema_version": FINAL_SUCCESS_SCHEMA_VERSION,
        "status": "success",
        "request_id": exact.request_id,
        "inchikey": exact.inchikey,
        "attempt_id": exact.attempt_id,
        "request_sha256": exact.request_sha256,
        "runner_source_sha256": exact.runner_source_sha256,
        "payload_manifest_sha256": exact.payload_manifest_sha256,
        "transport_inventory_sha256": session.bundle.transport_inventory_sha256,
        "permit_sha256": exact.permit_sha256,
        "resources_sha256": exact.resources_sha256,
        "input_sha256": {
            "cation": request.cation.xyz_sha256,
            "neutral": request.neutral.xyz_sha256,
            "endpoint_atom_map": exact.endpoint_atom_map_sha256,
            "legacy_atom_map": exact.legacy_atom_map_sha256,
            "geometry_validation": exact.geometry_validation_sha256,
        },
        "provisional": {
            "success_sha256": supervisor_success_sha256,
            "marker_sha256": _sha256_bytes(supervisor_marker_raw),
            "result_relative_path": provisional.result_relative_path,
            "result_sha256": provisional.result_sha256,
        },
        "guardian": {
            "receipt_sha256": context.guardian_receipt_sha256,
            "worker_registration_sha256": context.worker_registration_sha256,
            "compute_claim_sha256": context.compute_claim_sha256,
            "outcome": context.guardian_receipt.outcome,
            "supervisor_returncode": context.guardian_receipt.supervisor_returncode,
            "worker_group_cleanup_confirmed": (
                context.guardian_receipt.worker_guardian_result is not None
                and context.guardian_receipt.worker_guardian_result.group_cleanup_confirmed
            ),
        },
        "result": {
            "cation_energy_hartree": provisional.cation_energy_hartree,
            "neutral_energy_hartree": provisional.neutral_energy_hartree,
            "electronic_difference_kcal": provisional.electronic_difference_kcal,
            "dft_deprot_electronic_kcal": provisional.dft_deprot_electronic_kcal,
        },
    }
    success_raw = _canonical_json_bytes(success_payload)
    success_path = output_root / "success.json"
    marker_path = output_root / "_SUCCESS"
    success_sha256 = _exclusive_write(success_path, success_raw, mode=_PRIVATE_MODE)
    marker_raw = _canonical_json_bytes(
        {
            "schema_version": FINAL_SUCCESS_SCHEMA_VERSION,
            "success_sha256": success_sha256,
        }
    )
    marker_sha256 = _exclusive_write(marker_path, marker_raw, mode=_PRIVATE_MODE)
    return PublishedFinalAcceptance(
        success_json_sha256=success_sha256,
        success_marker_sha256=marker_sha256,
    )


def _run_guardian(
    *,
    run_root: Path,
    transport_inventory_sha256: str,
) -> int:
    runner._ensure_execution_authorized()  # pyright: ignore[reportPrivateUsage]
    _require_sha256(transport_inventory_sha256, label="transport inventory SHA256")
    if os.getpid() != os.getsid(0) or os.getpid() != os.getpgrp():
        raise Phase8BRuntimeError("guardian must be the detached session/process-group leader")
    getaffinity = getattr(os, "sched_getaffinity", None)
    if getaffinity is None:
        raise Phase8BRuntimeError("Linux sched_getaffinity is unavailable")
    require_affinity(frozenset(getaffinity(0)), FROZEN_ALLOWED_CPUS, exact=True)
    bundle = validate_phase8b_transport_bundle(
        run_root,
        expected_transport_inventory_sha256=transport_inventory_sha256,
        expected_source_relative_paths=runner._RUNNER_SOURCE_RELATIVE_PATHS,  # pyright: ignore[reportPrivateUsage]
    )
    ready_path = (run_root / FROZEN_READY_RELATIVE).resolve()
    consumed_path = (run_root / FROZEN_CONSUMED_RELATIVE).resolve()
    paths = _transaction_paths(run_root)
    release_token = secrets.token_hex(32)
    session_holder: dict[str, _AuthoritySession] = {}

    def consume() -> ConsumedPermitEvidence:
        consumed = consume_phase8b_permit(ready_path, **_permit_arguments(bundle))
        session = _AuthoritySession(consumed=consumed, bundle=bundle)
        session_holder["session"] = session
        return ConsumedPermitEvidence(permit_sha256=consumed.consumed_sha256, authority=session)

    def recover() -> ConsumedPermitEvidence | None:
        if not os.path.lexists(consumed_path):
            return None
        consumed = load_consumed_phase8b_permit(consumed_path, **_permit_arguments(bundle))
        session = _AuthoritySession(consumed=consumed, bundle=bundle)
        session_holder["session"] = session
        return ConsumedPermitEvidence(permit_sha256=consumed.consumed_sha256, authority=session)

    def validate_session(value: object) -> ExactPhase8BAuthority:
        if not isinstance(value, _AuthoritySession) or value is not session_holder.get("session"):
            raise Phase8BRuntimeError("guardian received an unknown consumed authority")
        return _load_exact_session(value, require_output_absent=True)

    runtime_path = Path(__file__).resolve(strict=True)
    source_root = runtime_path.parents[2]

    def spawn(context: GuardianLaunchContext) -> SupervisorProcess:
        argv = (
            sys.executable,
            "-I",
            "-B",
            str(runtime_path),
            "supervisor",
            "--run-root",
            str(run_root),
            "--transport-inventory-sha256",
            bundle.transport_inventory_sha256,
            "--expected-permit-sha256",
            bundle.permit_sha256,
            "--expected-request-sha256",
            bundle.request_sha256,
            "--expected-runner-source-sha256",
            bundle.runner_source_sha256,
            "--expected-payload-manifest-sha256",
            bundle.payload_manifest_sha256,
            "--absolute-deadline-ns",
            str(context.absolute_deadline_ns),
            "--release-token",
            context.release_token,
            "--guardian-pid",
            str(context.guardian.pid),
        )
        # Reaching this callback proves that the one-shot permit was consumed
        # and exact authority was validated.  Every dynamic log creation is
        # therefore receipt-backed, including partial-open failures.
        _redirect_guardian_log(run_root)
        supervisor_stdout, supervisor_stderr = _open_supervisor_logs(run_root)
        try:
            return spawn_supervisor_command(
                context,
                argv,
                cwd=source_root,
                env=os.environ,
                stdout=supervisor_stdout,
                stderr=supervisor_stderr,
            )
        except SupervisorLaunchError:
            raise
        except Exception as exc:
            raise SupervisorLaunchError("supervisor spawn failed") from exc
        finally:
            _close_fd(supervisor_stdout)
            _close_fd(supervisor_stderr)

    def publish(context: FinalAcceptanceContext) -> PublishedFinalAcceptance:
        session = session_holder.get("session")
        if session is None:
            raise Phase8BRuntimeError("final acceptance lost its authority session")
        return _publish_final_acceptance(context, session=session)

    result = run_guardian_transaction(
        transaction_id=FROZEN_TRANSACTION_ID,
        paths=paths,
        release_token=release_token,
        consume_permit=consume,
        recover_consumed_permit=recover,
        validate_consumed_authority=validate_session,
        spawn_supervisor=spawn,
        publish_final_acceptance=publish,
    )
    runtime_receipt = {
        "schema_version": RUNTIME_RECEIPT_SCHEMA_VERSION,
        "outcome": result.receipt.outcome,
        "transport_inventory_sha256": bundle.transport_inventory_sha256,
        "guardian_receipt_sha256": result.receipt_sha256,
        "final_acceptance": (
            None
            if result.final_acceptance is None
            else {
                "success_json_sha256": result.final_acceptance.success_json_sha256,
                "success_marker_sha256": result.final_acceptance.success_marker_sha256,
            }
        ),
    }
    print(json.dumps(runtime_receipt, sort_keys=True, allow_nan=False), flush=True)
    return 0 if result.final_acceptance is not None else 1


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="nhc-phase8b-runtime")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("guardian", "supervisor"):
        subparser = subparsers.add_parser(mode)
        subparser.add_argument("--run-root", required=True, type=Path)
        subparser.add_argument(
            "--transport-inventory-sha256",
            required=True,
            type=_sha256_argument,
        )
    supervisor = subparsers.choices["supervisor"]
    supervisor.add_argument("--absolute-deadline-ns", required=True, type=int)
    supervisor.add_argument("--release-token", required=True, type=_sha256_argument)
    supervisor.add_argument("--guardian-pid", required=True, type=int)
    supervisor.add_argument("--expected-permit-sha256", required=True, type=_sha256_argument)
    supervisor.add_argument("--expected-request-sha256", required=True, type=_sha256_argument)
    supervisor.add_argument(
        "--expected-runner-source-sha256",
        required=True,
        type=_sha256_argument,
    )
    supervisor.add_argument(
        "--expected-payload-manifest-sha256",
        required=True,
        type=_sha256_argument,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    run_root = arguments.run_root
    if (
        not run_root.is_absolute()
        or run_root.is_symlink()
        or run_root.resolve(strict=True) != run_root
    ):
        raise Phase8BRuntimeError("run root must be an exact absolute directory")
    if arguments.mode == "guardian":
        return _run_guardian(
            run_root=run_root,
            transport_inventory_sha256=arguments.transport_inventory_sha256,
        )
    # The guardian alone verifies the untouched transport tree.  After its
    # irreversible permit rename, the supervisor can validate only the
    # consumed permit and the manifest-bound payload closure.
    bundle = Phase8BBundleIdentity(
        transport_inventory_sha256=arguments.transport_inventory_sha256,
        payload_manifest_sha256=arguments.expected_payload_manifest_sha256,
        permit_sha256=arguments.expected_permit_sha256,
        request_sha256=arguments.expected_request_sha256,
        runner_source_sha256=arguments.expected_runner_source_sha256,
    )
    return _run_supervisor(
        run_root=run_root,
        bundle=bundle,
        absolute_deadline_ns=arguments.absolute_deadline_ns,
        release_token=arguments.release_token,
        guardian_pid=arguments.guardian_pid,
    )


if __name__ == "__main__":  # pragma: no cover - exercised through fixed server argv
    raise SystemExit(main())
