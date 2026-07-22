"""One-shot local launcher for the frozen Phase 8B guardian.

The launcher validates the already deployed bundle identity locally, then
commits an ignored, immutable invocation record before opening exactly one SSH
connection.  The record is never removed or reused, even when SSH fails.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import selectors
import shlex
import signal
import stat
import subprocess
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, cast

import yaml

from nhc_deprot_ranker.preparation.phase8b_deploy import _build_plan, _read_local_file
from nhc_deprot_ranker.preparation.phase8b_remote import Phase8BRemoteConfig
from nhc_deprot_ranker.quantum.phase8b_permit import (
    FROZEN_ATTEMPT_ID,
    FROZEN_INCHIKEY,
    FROZEN_REQUEST_ID,
    FROZEN_RESOURCES,
)

LAUNCH_INVOCATION_SCHEMA_VERSION: Final = "phase8b.launch-invocation.v1"
LAUNCH_OUTCOME_SCHEMA_VERSION: Final = "phase8b.launch-outcome.v1"

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
_PRIVATE_DIRECTORY: Final = _REPOSITORY_ROOT / "results/phase8b_private_v001"
_INVOCATION_PATH: Final = _PRIVATE_DIRECTORY / "launch.invocation.json"
_OUTCOME_PATH: Final = _PRIVATE_DIRECTORY / "launch.outcome.json"
_RUNTIME_RELATIVE: Final = "src/nhc_deprot_ranker/quantum/phase8b_runtime.py"
_PRIVATE_DIRECTORY_MODE: Final = 0o700
_PRIVATE_FILE_MODE: Final = 0o600
_MAX_CONFIG_BYTES: Final = 64 * 1024
_MAX_RECORD_BYTES: Final = 256 * 1024
_MAX_STREAM_BYTES: Final = 64 * 1024
_IO_CHUNK_BYTES: Final = 16 * 1024
_PRODUCTION_AUTHORIZATION_CONSUMED: Final = True


class Phase8BLaunchError(RuntimeError):
    """The unique launch was unsafe, already committed, or unsuccessful."""


class _CompletedProcessLike(Protocol):
    returncode: int
    stdout: bytes
    stderr: bytes


RunCommand = Callable[..., _CompletedProcessLike]


@dataclass(frozen=True, slots=True)
class _Completed:
    returncode: int
    stdout: bytes
    stderr: bytes


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_sha256(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise Phase8BLaunchError(f"{label} must be a lowercase SHA256")
    return value


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase8BLaunchError(f"{label} contains a duplicate key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise Phase8BLaunchError(f"{label} contains a non-finite number: {value}")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except Phase8BLaunchError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise Phase8BLaunchError(f"{label} is not strict JSON") from exc
    if not isinstance(payload, dict):
        raise Phase8BLaunchError(f"{label} must be one JSON object")
    return cast(dict[str, object], payload)


def _stable_identity(observed: os.stat_result) -> tuple[int, ...]:
    return (
        observed.st_dev,
        observed.st_ino,
        observed.st_mode,
        observed.st_uid,
        observed.st_nlink,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
    )


def _read_private_config(path: Path) -> tuple[Phase8BRemoteConfig, bytes]:
    absolute = Path(os.path.abspath(path))
    if absolute.parent.resolve(strict=True) != absolute.parent:
        raise Phase8BLaunchError("private launch config parent is unsafe")
    descriptor: int | None = None
    try:
        descriptor = os.open(absolute, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != _PRIVATE_FILE_MODE
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or opened.st_size <= 0
            or opened.st_size > _MAX_CONFIG_BYTES
        ):
            raise Phase8BLaunchError("private launch config identity or mode drifted")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(_IO_CHUNK_BYTES, remaining))
            if not chunk:
                raise Phase8BLaunchError("private launch config changed while being read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise Phase8BLaunchError("private launch config grew while being read")
        finished = os.fstat(descriptor)
        current = os.stat(absolute, follow_symlinks=False)
        if _stable_identity(finished) != _stable_identity(opened) or _stable_identity(
            current
        ) != _stable_identity(opened):
            raise Phase8BLaunchError("private launch config changed while being read")
        raw = b"".join(chunks)
    except Phase8BLaunchError:
        raise
    except OSError as exc:
        raise Phase8BLaunchError("private launch config cannot be read safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        decoded = yaml.safe_load(raw.decode("utf-8"))
        config = Phase8BRemoteConfig.model_validate(decoded)
    except Exception as exc:
        raise Phase8BLaunchError("private launch config is invalid") from exc
    config.require_directed_write()
    return config, raw


def _ensure_private_directory(path: Path, *, create: bool) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise Phase8BLaunchError("private launch directory path is unsafe")
    if create and not os.path.lexists(path):
        parent = path.parent
        if parent.resolve(strict=True) != parent:
            raise Phase8BLaunchError("private launch directory parent is unsafe")
        try:
            os.mkdir(path, _PRIVATE_DIRECTORY_MODE)
            parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise Phase8BLaunchError("private launch directory cannot be created") from exc
    try:
        observed = path.lstat()
    except OSError as exc:
        raise Phase8BLaunchError("private launch directory is unavailable") from exc
    if (
        not stat.S_ISDIR(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != _PRIVATE_DIRECTORY_MODE
        or observed.st_uid != os.geteuid()
        or path.resolve(strict=True) != path
    ):
        raise Phase8BLaunchError("private launch directory identity or mode drifted")


def _write_exclusive(path: Path, raw: bytes, *, label: str) -> str:
    if not raw or len(raw) > _MAX_RECORD_BYTES:
        raise Phase8BLaunchError(f"{label} size is invalid")
    _ensure_private_directory(path.parent, create=False)
    directory_fd = os.open(
        path.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    file_fd: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
        try:
            file_fd = os.open(path.name, flags, _PRIVATE_FILE_MODE, dir_fd=directory_fd)
        except FileExistsError as exc:
            raise Phase8BLaunchError(f"{label} already exists; launch cannot be retried") from exc
        view = memoryview(raw)
        offset = 0
        while offset < len(view):
            written = os.write(file_fd, view[offset:])
            if written <= 0:
                raise Phase8BLaunchError(f"{label} write made no progress")
            offset += written
        os.fchmod(file_fd, _PRIVATE_FILE_MODE)
        os.fsync(file_fd)
        opened = os.fstat(file_fd)
        current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != _PRIVATE_FILE_MODE
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or opened.st_size != len(raw)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise Phase8BLaunchError(f"{label} filesystem identity drifted")
        os.fsync(directory_fd)
    except Phase8BLaunchError:
        raise
    except OSError as exc:
        raise Phase8BLaunchError(f"{label} cannot be committed safely") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)
    return _sha256_bytes(raw)


def _remote_launch_script(thread_environment: Mapping[str, str]) -> str:
    exports = "\n".join(
        f"export {name}={shlex.quote(value)}" for name, value in sorted(thread_environment.items())
    )
    return f"""set -euo pipefail
project_root=$1
environment_relative=$2
run_root=$3
transport_inventory_sha256=$4
test "$environment_relative" = "env/envs/molenv.sh"
test -d "$project_root"
test ! -L "$project_root"
test -d "$run_root"
test ! -L "$run_root"
runtime_path="$run_root/{_RUNTIME_RELATIVE}"
test -f "$runtime_path"
test ! -L "$runtime_path"
command -v setsid >/dev/null 2>&1
command -v taskset >/dev/null 2>&1
cd "$project_root"
set +u
source "$environment_relative" >/dev/null 2>&1
set -u
cd "$project_root"
export PYTHONDONTWRITEBYTECODE=1
{exports}
exec setsid -f taskset -c 0-3 python -I -B "$runtime_path" guardian \
  --run-root "$run_root" \
  --transport-inventory-sha256 "$transport_inventory_sha256" \
  </dev/null >/dev/null 2>&1
"""


def phase8b_launch_command(
    config: Phase8BRemoteConfig,
    *,
    expected_transport_inventory_sha256: str,
    thread_environment: Mapping[str, str],
) -> tuple[tuple[str, ...], str, str]:
    """Return the exact SSH argv plus hashes of its remote command and script."""

    digest = _require_sha256(
        expected_transport_inventory_sha256,
        label="expected transport inventory SHA256",
    )
    script = _remote_launch_script(thread_environment)
    remote_command = shlex.join(
        (
            "exec",
            "bash",
            "-c",
            script,
            "phase8b-launch",
            config.remote.project_root,
            config.remote.environment_relative,
            config.remote.phase8b_root,
            digest,
        )
    )
    command = (
        "ssh",
        *config.ssh_options(),
        config.connection.ssh_alias,
        remote_command,
    )
    return (
        command,
        _sha256_bytes(remote_command.encode("utf-8")),
        _sha256_bytes(script.encode("utf-8")),
    )


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    with suppress(OSError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        with suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2.0)


def _bounded_run(command: tuple[str, ...], *, timeout: float) -> _Completed:
    """Run the sole SSH call with detached stdin and hard output/time bounds."""

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise Phase8BLaunchError("Phase 8B launch SSH could not start") from exc
    if process.stdout is None or process.stderr is None:
        _terminate(process)
        raise Phase8BLaunchError("Phase 8B launch SSH pipes are unavailable")
    selector = selectors.DefaultSelector()
    streams = (process.stdout, process.stderr)
    stdout = bytearray()
    stderr = bytearray()
    deadline = time.monotonic() + timeout
    try:
        for stream, label in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, label)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise Phase8BLaunchError("Phase 8B launch SSH timed out")
            for key, _mask in selector.select(min(remaining, 0.25)):
                try:
                    chunk = os.read(key.fd, _IO_CHUNK_BYTES)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target = stdout if key.data == "stdout" else stderr
                if len(target) + len(chunk) > _MAX_STREAM_BYTES:
                    raise Phase8BLaunchError(f"Phase 8B launch SSH {key.data} exceeded its bound")
                target.extend(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            raise Phase8BLaunchError("Phase 8B launch SSH timed out")
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise Phase8BLaunchError("Phase 8B launch SSH timed out") from exc
    except BaseException:
        _terminate(process)
        raise
    finally:
        selector.close()
        for stream in streams:
            stream.close()
    return _Completed(returncode=returncode, stdout=bytes(stdout), stderr=bytes(stderr))


def _launch_phase8b_smoke(
    *,
    config_path: Path,
    bundle_dir: Path,
    expected_transport_inventory_sha256: str,
    invocation_path: Path,
    outcome_path: Path,
    runner_source_sha256: str,
    require_production_identity: bool,
    thread_environment: Mapping[str, str],
    timeout_seconds: float,
    create_private_directory: bool,
    clock_ns: Callable[[], int] = time.time_ns,
    run_command: RunCommand | None = None,
) -> dict[str, object]:
    """Private injectable seam; production fixes every authority-bearing input."""

    from nhc_deprot_ranker.quantum import two_endpoint as runner

    if runner.EXECUTION_AUTHORIZED is not True:
        raise Phase8BLaunchError("Phase 8B source execution gate is closed")
    if _PRODUCTION_AUTHORIZATION_CONSUMED:
        raise Phase8BLaunchError("the unique Phase 8B launch authorization has been consumed")
    if run_command is None and (
        require_production_identity is not True
        or invocation_path != _INVOCATION_PATH
        or outcome_path != _OUTCOME_PATH
        or create_private_directory is not True
    ):
        raise Phase8BLaunchError("only the fixed production route may execute launch SSH")
    if not math.isfinite(timeout_seconds) or not 0.0 < timeout_seconds <= 120.0:
        raise ValueError("launch timeout must be in (0, 120]")
    inventory_sha256 = _require_sha256(
        expected_transport_inventory_sha256,
        label="expected transport inventory SHA256",
    )
    source_sha256 = _require_sha256(runner_source_sha256, label="runner source SHA256")
    config, config_raw = _read_private_config(config_path)
    plan = _build_plan(
        config=config,
        bundle_dir=bundle_dir,
        expected_transport_inventory_sha256=inventory_sha256,
    )
    inventory_raw = _read_local_file(
        Path(os.path.abspath(bundle_dir)) / "transport_inventory.json",
        expected_mode=0o640,
        label="launch transport inventory",
    )
    inventory = _strict_json_object(inventory_raw, label="launch transport inventory")
    if _sha256_bytes(inventory_raw) != inventory_sha256 or inventory_raw != _canonical_json_bytes(
        inventory
    ):
        raise Phase8BLaunchError("launch transport inventory identity drifted")
    payload_raw = _read_local_file(
        Path(os.path.abspath(bundle_dir)) / "payload_manifest.json",
        expected_mode=0o640,
        label="launch payload manifest",
    )
    payload = _strict_json_object(payload_raw, label="launch payload manifest")
    if _sha256_bytes(payload_raw) != inventory.get(
        "payload_manifest_sha256"
    ) or payload_raw != _canonical_json_bytes(payload):
        raise Phase8BLaunchError("launch payload manifest identity drifted")
    identity = payload.get("identity")
    if not isinstance(identity, dict):
        raise Phase8BLaunchError("launch payload identity is unavailable")
    if identity.get("runner_source_sha256") != source_sha256:
        raise Phase8BLaunchError("local source and deployed bundle source disagree")
    if require_production_identity and (
        set(identity)
        != {
            "inchikey",
            "request_id",
            "attempt_id",
            "request_sha256",
            "runner_source_sha256",
            "protocol_sha256",
            "endpoint_order",
        }
        or identity.get("inchikey") != FROZEN_INCHIKEY
        or identity.get("request_id") != FROZEN_REQUEST_ID
        or identity.get("attempt_id") != FROZEN_ATTEMPT_ID
        or identity.get("endpoint_order") != ["cation", "neutral"]
        or payload.get("resources") != FROZEN_RESOURCES
    ):
        raise Phase8BLaunchError("launch payload production identity drifted")
    request_sha256 = _require_sha256(identity.get("request_sha256"), label="request SHA256")
    payload_manifest_sha256 = _require_sha256(
        inventory.get("payload_manifest_sha256"), label="payload manifest SHA256"
    )
    permit_sha256 = _require_sha256(inventory.get("permit_sha256"), label="permit SHA256")
    command, remote_command_sha256, remote_script_sha256 = phase8b_launch_command(
        config,
        expected_transport_inventory_sha256=inventory_sha256,
        thread_environment=thread_environment,
    )
    invocation = Path(os.path.abspath(invocation_path))
    outcome = Path(os.path.abspath(outcome_path))
    if (
        invocation.parent != outcome.parent
        or invocation.name != "launch.invocation.json"
        or outcome.name != "launch.outcome.json"
    ):
        raise Phase8BLaunchError("launch record paths drifted")
    _ensure_private_directory(invocation.parent, create=create_private_directory)
    if os.path.lexists(outcome):
        raise Phase8BLaunchError("launch outcome already exists; launch cannot be retried")
    expected = plan.expected_evidence
    invocation_payload: dict[str, object] = {
        "schema_version": LAUNCH_INVOCATION_SCHEMA_VERSION,
        "status": "ssh_invocation_committed",
        "created_unix_ns": clock_ns(),
        "identity": {
            "inchikey": FROZEN_INCHIKEY,
            "request_id": FROZEN_REQUEST_ID,
            "attempt_id": FROZEN_ATTEMPT_ID,
        },
        "config_sha256": _sha256_bytes(config_raw),
        "bundle": {
            "transport_inventory_sha256": inventory_sha256,
            "transport_tree_sha256": expected["transport_tree_sha256"],
            "directory_tree_sha256": expected["directory_tree_sha256"],
            "payload_manifest_sha256": payload_manifest_sha256,
            "permit_sha256": permit_sha256,
            "request_sha256": request_sha256,
            "runner_source_sha256": source_sha256,
        },
        "remote": {
            "project_root": config.remote.project_root,
            "run_root": config.remote.phase8b_root,
            "environment_relative": config.remote.environment_relative,
        },
        "ssh_argv": list(command),
        "ssh_argv_sha256": _sha256_bytes(_canonical_json_bytes(list(command))),
        "remote_command_sha256": remote_command_sha256,
        "remote_script_sha256": remote_script_sha256,
        "timeout_seconds": timeout_seconds,
        "remote_guardian_stdio": {
            "stdin": "/dev/null",
            "stdout": "/dev/null",
            "stderr": "/dev/null",
        },
        "retry_authorized": False,
    }
    invocation_raw = _canonical_json_bytes(invocation_payload)
    invocation_sha256 = _write_exclusive(
        invocation,
        invocation_raw,
        label="Phase 8B launch invocation record",
    )
    if os.path.lexists(outcome):
        raise Phase8BLaunchError("launch outcome appeared after invocation commit")
    command_runner = cast(RunCommand, _bounded_run) if run_command is None else run_command
    try:
        completed = command_runner(command, timeout=timeout_seconds)
    except BaseException as exc:
        outcome_payload = {
            "schema_version": LAUNCH_OUTCOME_SCHEMA_VERSION,
            "status": "ssh_call_failed",
            "invocation_sha256": invocation_sha256,
            "error_type": type(exc).__name__,
            "retry_authorized": False,
        }
        _write_exclusive(
            outcome,
            _canonical_json_bytes(outcome_payload),
            label="Phase 8B launch outcome record",
        )
        if isinstance(exc, Phase8BLaunchError):
            raise
        raise Phase8BLaunchError("Phase 8B launch SSH call failed") from exc
    outcome_status = (
        "ssh_returned_zero"
        if completed.returncode == 0 and completed.stdout == b"" and completed.stderr == b""
        else "ssh_call_failed"
    )
    outcome_payload = {
        "schema_version": LAUNCH_OUTCOME_SCHEMA_VERSION,
        "status": outcome_status,
        "invocation_sha256": invocation_sha256,
        "returncode": completed.returncode,
        "stdout_bytes": len(completed.stdout),
        "stdout_sha256": _sha256_bytes(completed.stdout),
        "stderr_bytes": len(completed.stderr),
        "stderr_sha256": _sha256_bytes(completed.stderr),
        "retry_authorized": False,
    }
    outcome_sha256 = _write_exclusive(
        outcome,
        _canonical_json_bytes(outcome_payload),
        label="Phase 8B launch outcome record",
    )
    if outcome_status != "ssh_returned_zero":
        raise Phase8BLaunchError("Phase 8B launch SSH did not return one clean acceptance")
    return {
        "schema_version": LAUNCH_OUTCOME_SCHEMA_VERSION,
        "status": outcome_status,
        "inchikey": FROZEN_INCHIKEY,
        "request_id": FROZEN_REQUEST_ID,
        "attempt_id": FROZEN_ATTEMPT_ID,
        "transport_inventory_sha256": inventory_sha256,
        "runner_source_sha256": source_sha256,
        "invocation_sha256": invocation_sha256,
        "outcome_sha256": outcome_sha256,
        "retry_authorized": False,
    }


def launch_phase8b_smoke(
    *,
    config_path: Path,
    bundle_dir: Path,
    expected_transport_inventory_sha256: str,
    timeout_seconds: float = 60.0,
) -> dict[str, object]:
    """Commit and send the sole production launch invocation."""

    from nhc_deprot_ranker.quantum import two_endpoint as runner

    return _launch_phase8b_smoke(
        config_path=config_path,
        bundle_dir=bundle_dir,
        expected_transport_inventory_sha256=expected_transport_inventory_sha256,
        invocation_path=_INVOCATION_PATH,
        outcome_path=_OUTCOME_PATH,
        runner_source_sha256=runner.current_runner_source_sha256(),
        require_production_identity=True,
        thread_environment=runner.THREAD_ENVIRONMENT,
        timeout_seconds=timeout_seconds,
        create_private_directory=True,
    )


__all__ = [
    "LAUNCH_INVOCATION_SCHEMA_VERSION",
    "LAUNCH_OUTCOME_SCHEMA_VERSION",
    "Phase8BLaunchError",
    "launch_phase8b_smoke",
    "phase8b_launch_command",
]
