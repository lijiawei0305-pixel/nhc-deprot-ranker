"""One-shot private authorization for the frozen Phase 8B smoke.

This module is deliberately standard-library-only and does not import the
runner or any chemistry package.  It validates one exact, path-bound permit and
consumes it before a caller may spawn a worker.  Creating the consumed file is
the irreversible linearization point; this module never restores a ready
permit.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, cast

PERMIT_SCHEMA_VERSION: Final = "nhc-phase8b-private-permit-v1"

FROZEN_INCHIKEY: Final = "QXHIEGFUWOLQIJ-UHFFFAOYSA-N"
FROZEN_REQUEST_ID: Final = "phase8b-qxh-smoke-v001"
FROZEN_ATTEMPT_ID: Final = "attempt-phase8b-qxh-v001"
FROZEN_PROTOCOL_SHA256: Final = "266b06e0d49cb6e3067bcfeb6d62f0712852e96768c4205b49fffcb3df52fe92"

FROZEN_RUN_RELATIVE: Final = "data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001"
FROZEN_REQUEST_RELATIVE: Final = "input/request.json"
FROZEN_OUTPUT_RELATIVE: Final = "runtime/output"
FROZEN_PAYLOAD_MANIFEST_RELATIVE: Final = "payload_manifest.json"
FROZEN_READY_RELATIVE: Final = "private/permit.ready.json"
FROZEN_CONSUMED_RELATIVE: Final = "private/permit.consumed.json"

FROZEN_INPUT_SHA256: Final[dict[str, str]] = {
    "cation_xyz": "097f08ab7c3f265efa8ee36c3fd45d72776c9bdcbd3de503baf8fe91561c12aa",
    "neutral_xyz": "e41e87daca3c7a74383364a427d277df5cf8a0aa70bff015c4cf432455f26bd0",
    "endpoint_atom_map": "0cb13e918f2fa88348affb2385d37e01a75d73376118d18aa4c7647ef4982152",
    "legacy_atom_map": "7766fad207561b79ac8e7278b70eb07c37dcf31d4114b76ad9a9383b235681f8",
}

FROZEN_RESOURCES: Final[dict[str, object]] = {
    "worker_count": 1,
    "computational_threads": 4,
    "cpu_affinity": "0-3",
    "pyscf_max_memory_mb": 12_000,
    "hard_wall_timeout_seconds": 7_200,
    "terminate_grace_seconds": 10,
    "stdout_capture_limit_bytes": 65_536,
    "stderr_capture_limit_bytes": 65_536,
}

_MAX_PERMIT_BYTES: Final = 64 * 1024
_SHA256_LENGTH: Final = 64
_PUBLIC_PAYLOAD_MODE: Final = 0o640
_PRIVATE_DIRECTORY_MODE: Final = 0o700
_READY_MODE: Final = 0o600
_CONSUMED_MODE: Final = 0o400


class Phase8BPermitError(RuntimeError):
    """The private Phase 8B permit is invalid or cannot be consumed safely."""


class Phase8BPermitValidationError(Phase8BPermitError):
    """The permit bytes, bindings, or filesystem identity are invalid."""


class Phase8BPermitConsumedError(Phase8BPermitError):
    """The one-shot permit is already consumed or its state is ambiguous."""


@dataclass(frozen=True)
class Phase8BPermit:
    """A fully validated exact authorization, before or after consumption."""

    request_sha256: str
    runner_source_sha256: str
    payload_manifest_sha256: str
    project_root: Path
    run_root: Path
    request_path: Path
    output_root: Path
    ready_path: Path
    consumed_path: Path
    raw_bytes: bytes
    permit_sha256: str


@dataclass(frozen=True)
class ConsumedPhase8BPermit:
    """Proof that the ready permit crossed the irreversible linearization point."""

    permit: Phase8BPermit
    consumed_path: Path
    consumed_sha256: str


@dataclass(frozen=True)
class _PermitLayout:
    project_root: Path
    run_root: Path
    request_path: Path
    output_root: Path
    ready_path: Path
    consumed_path: Path


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_sha256(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise Phase8BPermitValidationError(f"{label} must be a lowercase SHA256")
    return value


def _require_exact_keys(value: dict[str, object], expected: set[str], *, label: str) -> None:
    if set(value) != expected:
        raise Phase8BPermitValidationError(f"{label} fields drifted")


def _require_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise Phase8BPermitValidationError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _strict_json_object(raw: bytes) -> dict[str, object]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase8BPermitValidationError("permit must be UTF-8") from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase8BPermitValidationError(f"permit contains duplicate key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise Phase8BPermitValidationError(f"permit contains non-finite number: {value}")

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except Phase8BPermitValidationError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise Phase8BPermitValidationError("permit is not strict JSON") from exc
    return _require_object(decoded, label="permit")


def _normalized_absolute_path(value: object, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise Phase8BPermitValidationError(f"{label} must be an absolute POSIX path")
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or path == PurePosixPath("/")
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise Phase8BPermitValidationError(f"{label} must be a normalized specific path")
    return path


def _project_paths(project_root: PurePosixPath) -> dict[str, str]:
    run_root = project_root / FROZEN_RUN_RELATIVE
    return {
        "project_root": project_root.as_posix(),
        "run_root": run_root.as_posix(),
        "request_path": (run_root / FROZEN_REQUEST_RELATIVE).as_posix(),
        "output_root": (run_root / FROZEN_OUTPUT_RELATIVE).as_posix(),
        "payload_manifest_path": (run_root / FROZEN_PAYLOAD_MANIFEST_RELATIVE).as_posix(),
        "permit_ready_path": (run_root / FROZEN_READY_RELATIVE).as_posix(),
        "permit_consumed_path": (run_root / FROZEN_CONSUMED_RELATIVE).as_posix(),
        "run_relative": FROZEN_RUN_RELATIVE,
        "request_relative": FROZEN_REQUEST_RELATIVE,
        "output_relative": FROZEN_OUTPUT_RELATIVE,
        "payload_manifest_relative": FROZEN_PAYLOAD_MANIFEST_RELATIVE,
        "permit_ready_relative": FROZEN_READY_RELATIVE,
        "permit_consumed_relative": FROZEN_CONSUMED_RELATIVE,
    }


def render_phase8b_permit(
    *,
    project_root: str,
    request_sha256: str,
    runner_source_sha256: str,
    payload_manifest_sha256: str,
) -> bytes:
    """Render deterministic private permit bytes for the one frozen smoke."""

    root = _normalized_absolute_path(project_root, label="project_root")
    request_hash = _require_sha256(request_sha256, label="request_sha256")
    source_hash = _require_sha256(runner_source_sha256, label="runner_source_sha256")
    payload_hash = _require_sha256(payload_manifest_sha256, label="payload_manifest_sha256")
    permit = {
        "schema_version": PERMIT_SCHEMA_VERSION,
        "authorization": {
            "one_shot": True,
            "server_write_authorized": True,
            "quantum_execution_authorized": True,
            "candidate_replacement_authorized": False,
            "second_attempt_authorized": False,
            "resume_authorized": False,
        },
        "identity": {
            "inchikey": FROZEN_INCHIKEY,
            "request_id": FROZEN_REQUEST_ID,
            "attempt_id": FROZEN_ATTEMPT_ID,
            "endpoint_order": ["cation", "neutral"],
            "protocol_sha256": FROZEN_PROTOCOL_SHA256,
            "request_sha256": request_hash,
            "runner_source_sha256": source_hash,
            "payload_manifest_sha256": payload_hash,
            "input_sha256": FROZEN_INPUT_SHA256,
        },
        "resources": FROZEN_RESOURCES,
        "paths": _project_paths(root),
    }
    return _canonical_json_bytes(permit)


def _validate_payload(
    payload: dict[str, object],
    *,
    raw: bytes,
    expected_permit_sha256: str,
    expected_request_sha256: str,
    expected_runner_source_sha256: str,
    expected_payload_manifest_sha256: str,
) -> tuple[dict[str, str], dict[str, object]]:
    if raw != _canonical_json_bytes(payload):
        raise Phase8BPermitValidationError("permit bytes are not canonical JSON")
    _require_exact_keys(
        payload,
        {"schema_version", "authorization", "identity", "resources", "paths"},
        label="permit",
    )
    if payload["schema_version"] != PERMIT_SCHEMA_VERSION:
        raise Phase8BPermitValidationError("permit schema_version drifted")

    authorization = _require_object(payload["authorization"], label="authorization")
    expected_authorization: dict[str, object] = {
        "one_shot": True,
        "server_write_authorized": True,
        "quantum_execution_authorized": True,
        "candidate_replacement_authorized": False,
        "second_attempt_authorized": False,
        "resume_authorized": False,
    }
    if authorization != expected_authorization:
        raise Phase8BPermitValidationError("permit authorization drifted")

    identity = _require_object(payload["identity"], label="identity")
    _require_exact_keys(
        identity,
        {
            "inchikey",
            "request_id",
            "attempt_id",
            "endpoint_order",
            "protocol_sha256",
            "request_sha256",
            "runner_source_sha256",
            "payload_manifest_sha256",
            "input_sha256",
        },
        label="identity",
    )
    expected_identity: dict[str, object] = {
        "inchikey": FROZEN_INCHIKEY,
        "request_id": FROZEN_REQUEST_ID,
        "attempt_id": FROZEN_ATTEMPT_ID,
        "endpoint_order": ["cation", "neutral"],
        "protocol_sha256": FROZEN_PROTOCOL_SHA256,
        "request_sha256": _require_sha256(expected_request_sha256, label="expected_request_sha256"),
        "runner_source_sha256": _require_sha256(
            expected_runner_source_sha256, label="expected_runner_source_sha256"
        ),
        "payload_manifest_sha256": _require_sha256(
            expected_payload_manifest_sha256,
            label="expected_payload_manifest_sha256",
        ),
        "input_sha256": FROZEN_INPUT_SHA256,
    }
    if identity != expected_identity:
        raise Phase8BPermitValidationError("permit identity drifted")
    if payload["resources"] != FROZEN_RESOURCES:
        raise Phase8BPermitValidationError("permit resources drifted")

    paths = _require_object(payload["paths"], label="paths")
    _require_exact_keys(paths, set(_project_paths(PurePosixPath("/project"))), label="paths")
    root = _normalized_absolute_path(paths["project_root"], label="paths.project_root")
    expected_paths = _project_paths(root)
    if paths != expected_paths:
        raise Phase8BPermitValidationError("permit path bindings drifted")

    expected_permit_hash = _require_sha256(expected_permit_sha256, label="expected_permit_sha256")
    if _sha256_bytes(raw) != expected_permit_hash:
        raise Phase8BPermitValidationError("permit SHA256 does not match transport inventory")
    return cast(dict[str, str], paths), identity


def _validate_owned_regular_stat(
    file_stat: os.stat_result, *, label: str, expected_mode: int
) -> None:
    if not stat.S_ISREG(file_stat.st_mode):
        raise Phase8BPermitValidationError(f"{label} is not a regular file")
    if file_stat.st_uid != os.geteuid():
        raise Phase8BPermitValidationError(f"{label} is not owned by the current user")
    if stat.S_IMODE(file_stat.st_mode) != expected_mode:
        raise Phase8BPermitValidationError(f"{label} mode must be {expected_mode:04o}")
    if file_stat.st_nlink != 1:
        raise Phase8BPermitValidationError(f"{label} must have exactly one hard link")


def _validate_owned_directory(path: Path, *, label: str, expected_mode: int) -> None:
    if path.is_symlink():
        raise Phase8BPermitValidationError(f"{label} must not be a symlink")
    try:
        directory_stat = path.stat()
    except OSError as exc:
        raise Phase8BPermitValidationError(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise Phase8BPermitValidationError(f"{label} is not a directory")
    if directory_stat.st_uid != os.geteuid():
        raise Phase8BPermitValidationError(f"{label} is not owned by the current user")
    if stat.S_IMODE(directory_stat.st_mode) != expected_mode:
        raise Phase8BPermitValidationError(f"{label} mode must be {expected_mode:04o}")


def _read_fd(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(8192, _MAX_PERMIT_BYTES + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_PERMIT_BYTES:
            raise Phase8BPermitValidationError("permit exceeds the maximum byte size")
    if total == 0:
        raise Phase8BPermitValidationError("permit is empty")
    return b"".join(chunks)


def _read_bound_file(path: Path, *, expected_sha256: str, label: str) -> None:
    if path.is_symlink():
        raise Phase8BPermitValidationError(f"{label} must not be a symlink")
    try:
        if path.resolve(strict=True) != path:
            raise Phase8BPermitValidationError(f"{label} traverses a symlink")
        file_stat = path.stat()
        raw = path.read_bytes()
    except Phase8BPermitValidationError:
        raise
    except OSError as exc:
        raise Phase8BPermitValidationError(f"{label} is unavailable") from exc
    _validate_owned_regular_stat(file_stat, label=label, expected_mode=_PUBLIC_PAYLOAD_MODE)
    if _sha256_bytes(raw) != expected_sha256:
        raise Phase8BPermitValidationError(f"{label} SHA256 drifted")


def _validate_actual_layout(
    *,
    paths: dict[str, str],
    permit_path: Path,
    consumed: bool,
    require_output_absent: bool,
    expected_request_sha256: str,
    expected_payload_manifest_sha256: str,
) -> _PermitLayout:
    path_key = "permit_consumed_path" if consumed else "permit_ready_path"
    embedded_permit = Path(paths[path_key])
    if permit_path != embedded_permit:
        state = "consumed" if consumed else "ready"
        raise Phase8BPermitValidationError(f"permit was copied to a different {state} path")
    project_root = Path(paths["project_root"])
    run_root = Path(paths["run_root"])
    private_root = permit_path.parent
    if not project_root.is_absolute() or project_root.resolve(strict=True) != project_root:
        raise Phase8BPermitValidationError("project root is not an exact real path")
    if run_root.resolve(strict=True) != run_root:
        raise Phase8BPermitValidationError("run root is not an exact real path")
    _validate_owned_directory(run_root, label="run root", expected_mode=_PRIVATE_DIRECTORY_MODE)
    _validate_owned_directory(
        private_root,
        label="permit directory",
        expected_mode=_PRIVATE_DIRECTORY_MODE,
    )
    if private_root != run_root / "private":
        raise Phase8BPermitValidationError("permit directory escaped the fixed run root")

    request_path = Path(paths["request_path"])
    payload_manifest_path = Path(paths["payload_manifest_path"])
    _read_bound_file(
        request_path,
        expected_sha256=expected_request_sha256,
        label="request",
    )
    _read_bound_file(
        payload_manifest_path,
        expected_sha256=expected_payload_manifest_sha256,
        label="payload manifest",
    )
    output_root = Path(paths["output_root"])
    output_exists = os.path.lexists(output_root)
    if require_output_absent and output_exists:
        raise Phase8BPermitValidationError("fixed output root already exists; resume is prohibited")
    if output_root.parent.is_symlink() or not output_root.parent.is_dir():
        raise Phase8BPermitValidationError("fixed output parent must be a real directory")
    if output_root.parent.resolve(strict=True) != output_root.parent:
        raise Phase8BPermitValidationError("fixed output parent is not an exact real path")
    if output_exists:
        if output_root.is_symlink() or not output_root.is_dir():
            raise Phase8BPermitValidationError("fixed output root must be a real directory")
        if output_root.resolve(strict=True) != output_root:
            raise Phase8BPermitValidationError("fixed output root is not an exact real path")

    return _PermitLayout(
        project_root=project_root,
        run_root=run_root,
        request_path=request_path,
        output_root=output_root,
        ready_path=Path(paths["permit_ready_path"]),
        consumed_path=Path(paths["permit_consumed_path"]),
    )


def consume_phase8b_permit(
    ready_path: Path,
    *,
    expected_permit_sha256: str,
    expected_request_sha256: str,
    expected_runner_source_sha256: str,
    expected_payload_manifest_sha256: str,
) -> ConsumedPhase8BPermit:
    """Validate and irreversibly consume the exact permit before worker spawn.

    The successful ``O_EXCL`` creation of ``permit.consumed.json`` is the
    linearization point.  Any exception after that point deliberately leaves a
    consumed or ambiguous state, and no code here can restore the ready file.
    """

    if not ready_path.is_absolute() or ready_path.name != Path(FROZEN_READY_RELATIVE).name:
        raise Phase8BPermitValidationError("ready_path must be the exact absolute permit path")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise Phase8BPermitValidationError("platform lacks required no-follow directory flags")

    private_root = ready_path.parent
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        directory_fd = os.open(private_root, directory_flags)
    except OSError as exc:
        raise Phase8BPermitValidationError("permit directory cannot be opened safely") from exc

    ready_name = Path(FROZEN_READY_RELATIVE).name
    consumed_name = Path(FROZEN_CONSUMED_RELATIVE).name
    ready_fd: int | None = None
    try:
        try:
            os.stat(consumed_name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise Phase8BPermitConsumedError("Phase 8B permit is already consumed")

        try:
            ready_fd = os.open(
                ready_name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
        except FileNotFoundError as exc:
            try:
                os.stat(consumed_name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                raise Phase8BPermitValidationError(
                    "ready permit disappeared before validation"
                ) from exc
            raise Phase8BPermitConsumedError("Phase 8B permit lost the consume race") from exc
        except OSError as exc:
            raise Phase8BPermitValidationError("ready permit cannot be opened safely") from exc
        opened_stat = os.fstat(ready_fd)
        _validate_owned_regular_stat(opened_stat, label="ready permit", expected_mode=_READY_MODE)
        raw = _read_fd(ready_fd)

        payload = _strict_json_object(raw)
        paths, identity = _validate_payload(
            payload,
            raw=raw,
            expected_permit_sha256=expected_permit_sha256,
            expected_request_sha256=expected_request_sha256,
            expected_runner_source_sha256=expected_runner_source_sha256,
            expected_payload_manifest_sha256=expected_payload_manifest_sha256,
        )
        partial = _validate_actual_layout(
            paths=paths,
            permit_path=ready_path,
            consumed=False,
            require_output_absent=True,
            expected_request_sha256=expected_request_sha256,
            expected_payload_manifest_sha256=expected_payload_manifest_sha256,
        )
        try:
            current_stat = os.stat(ready_name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            try:
                os.stat(consumed_name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                raise Phase8BPermitValidationError(
                    "ready permit disappeared during validation"
                ) from exc
            raise Phase8BPermitConsumedError("Phase 8B permit lost the consume race") from exc
        if (current_stat.st_dev, current_stat.st_ino) != (opened_stat.st_dev, opened_stat.st_ino):
            raise Phase8BPermitValidationError("ready permit changed during validation")

        try:
            consumed_fd = os.open(
                consumed_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                _READY_MODE,
                dir_fd=directory_fd,
            )
        except FileExistsError as exc:
            raise Phase8BPermitConsumedError("Phase 8B permit lost the consume race") from exc
        except OSError as exc:
            raise Phase8BPermitError("consumed permit could not be created safely") from exc

        try:
            view = memoryview(raw)
            written = 0
            while written < len(view):
                count = os.write(consumed_fd, view[written:])
                if count <= 0:
                    raise Phase8BPermitError("consumed permit write made no progress")
                written += count
            os.fchmod(consumed_fd, _CONSUMED_MODE)
            os.fsync(consumed_fd)
        finally:
            os.close(consumed_fd)
        os.fsync(directory_fd)

        # No failure after the O_EXCL point may restore ready.  If unlink/fsync
        # fails, the coexistence of ready and consumed remains fail-closed.
        os.unlink(ready_name, dir_fd=directory_fd)
        os.fsync(directory_fd)
        try:
            os.stat(ready_name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise Phase8BPermitError("ready permit still exists after consumption")
        consumed_stat = os.stat(consumed_name, dir_fd=directory_fd, follow_symlinks=False)
        _validate_owned_regular_stat(
            consumed_stat,
            label="consumed permit",
            expected_mode=_CONSUMED_MODE,
        )
        consumed_path = partial.consumed_path
        consumed_read_fd = os.open(
            consumed_name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        try:
            consumed_raw = _read_fd(consumed_read_fd)
        finally:
            os.close(consumed_read_fd)
        if consumed_raw != raw:
            raise Phase8BPermitError("consumed permit bytes changed after fsync")

        permit_hash = _sha256_bytes(raw)
        permit = Phase8BPermit(
            request_sha256=expected_request_sha256,
            runner_source_sha256=cast(str, identity["runner_source_sha256"]),
            payload_manifest_sha256=expected_payload_manifest_sha256,
            project_root=partial.project_root,
            run_root=partial.run_root,
            request_path=partial.request_path,
            output_root=partial.output_root,
            ready_path=partial.ready_path,
            consumed_path=consumed_path,
            raw_bytes=raw,
            permit_sha256=permit_hash,
        )
        return ConsumedPhase8BPermit(
            permit=permit,
            consumed_path=consumed_path,
            consumed_sha256=permit_hash,
        )
    finally:
        if ready_fd is not None:
            os.close(ready_fd)
        os.close(directory_fd)


def load_consumed_phase8b_permit(
    consumed_path: Path,
    *,
    expected_permit_sha256: str,
    expected_request_sha256: str,
    expected_runner_source_sha256: str,
    expected_payload_manifest_sha256: str,
) -> ConsumedPhase8BPermit:
    """Read and revalidate an irreversibly consumed exact permit.

    This function is intentionally repeatable and read-only.  It neither
    recreates a ready permit nor requires the output root to remain absent:
    the caller may have created that directory after the one-shot consume
    linearization point.
    """

    if not consumed_path.is_absolute() or consumed_path.name != Path(FROZEN_CONSUMED_RELATIVE).name:
        raise Phase8BPermitValidationError("consumed_path must be the exact absolute permit path")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise Phase8BPermitValidationError("platform lacks required no-follow directory flags")

    private_root = consumed_path.parent
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        directory_fd = os.open(private_root, directory_flags)
    except OSError as exc:
        raise Phase8BPermitValidationError("permit directory cannot be opened safely") from exc

    ready_name = Path(FROZEN_READY_RELATIVE).name
    consumed_name = Path(FROZEN_CONSUMED_RELATIVE).name
    consumed_fd: int | None = None
    try:
        try:
            os.stat(ready_name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise Phase8BPermitValidationError("ready permit must be absent after consumption")

        try:
            consumed_fd = os.open(
                consumed_name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
        except OSError as exc:
            raise Phase8BPermitValidationError("consumed permit cannot be opened safely") from exc
        opened_stat = os.fstat(consumed_fd)
        _validate_owned_regular_stat(
            opened_stat,
            label="consumed permit",
            expected_mode=_CONSUMED_MODE,
        )
        raw = _read_fd(consumed_fd)

        payload = _strict_json_object(raw)
        paths, identity = _validate_payload(
            payload,
            raw=raw,
            expected_permit_sha256=expected_permit_sha256,
            expected_request_sha256=expected_request_sha256,
            expected_runner_source_sha256=expected_runner_source_sha256,
            expected_payload_manifest_sha256=expected_payload_manifest_sha256,
        )
        layout = _validate_actual_layout(
            paths=paths,
            permit_path=consumed_path,
            consumed=True,
            require_output_absent=False,
            expected_request_sha256=expected_request_sha256,
            expected_payload_manifest_sha256=expected_payload_manifest_sha256,
        )

        current_stat = os.stat(consumed_name, dir_fd=directory_fd, follow_symlinks=False)
        _validate_owned_regular_stat(
            current_stat,
            label="consumed permit",
            expected_mode=_CONSUMED_MODE,
        )
        if (current_stat.st_dev, current_stat.st_ino) != (
            opened_stat.st_dev,
            opened_stat.st_ino,
        ):
            raise Phase8BPermitValidationError("consumed permit changed during validation")
        try:
            os.stat(ready_name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise Phase8BPermitValidationError("ready permit reappeared during consumed validation")

        permit_hash = _sha256_bytes(raw)
        permit = Phase8BPermit(
            request_sha256=expected_request_sha256,
            runner_source_sha256=cast(str, identity["runner_source_sha256"]),
            payload_manifest_sha256=expected_payload_manifest_sha256,
            project_root=layout.project_root,
            run_root=layout.run_root,
            request_path=layout.request_path,
            output_root=layout.output_root,
            ready_path=layout.ready_path,
            consumed_path=layout.consumed_path,
            raw_bytes=raw,
            permit_sha256=permit_hash,
        )
        return ConsumedPhase8BPermit(
            permit=permit,
            consumed_path=layout.consumed_path,
            consumed_sha256=permit_hash,
        )
    finally:
        if consumed_fd is not None:
            os.close(consumed_fd)
        os.close(directory_fd)
