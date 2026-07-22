"""Single-shot, directed deployment of one immutable Phase 8B bundle.

This module has no chemistry imports and no execution entry point.  It sends
one already validated transport tree to a standard-library-only receiver over
one SSH process.  The receiver may only create the fixed, absent run root and
the exact inventory members; it never overwrites, deletes, retries, or cleans
up a partial deployment.
"""

from __future__ import annotations

import hashlib
import json
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
from pathlib import Path, PurePosixPath
from typing import Final, Protocol, cast

from nhc_deprot_ranker.preparation import phase8b_bundle
from nhc_deprot_ranker.preparation.phase8b_remote import (
    PHASE8B_RUN_RELATIVE,
    Phase8BRemoteConfig,
    load_phase8b_remote_config,
)

DEPLOY_STREAM_SCHEMA_VERSION: Final = "phase8b.directed-deploy-stream.v1"
DEPLOY_EVIDENCE_SCHEMA_VERSION: Final = "phase8b.directed-deployment-evidence.v1"

_MAGIC: Final = b"NHC_PHASE8B_DIRECTED_DEPLOY_V1\n"
_TRANSPORT_INVENTORY_NAME: Final = "transport_inventory.json"
_PERMIT_NAME: Final = "private/permit.ready.json"
_MAX_HEADER_BYTES: Final = 2 * 1024 * 1024
_MAX_TRANSFER_BYTES: Final = 64 * 1024 * 1024
_MAX_FILE_BYTES: Final = 16 * 1024 * 1024
_MAX_FILES: Final = 512
_MAX_DIRECTORIES: Final = 256
_MAX_STDOUT_BYTES: Final = 2 * 1024 * 1024
_MAX_STDERR_BYTES: Final = 64 * 1024
_IO_CHUNK_BYTES: Final = 64 * 1024
_PUBLIC_MODE: Final = 0o640
_PRIVATE_MODE: Final = 0o600
_ROOT_MODE: Final = 0o700


class Phase8BDeployError(RuntimeError):
    """The directed deployment could not prove or preserve its closed scope."""


class _CompletedProcessLike(Protocol):
    returncode: int
    stdout: bytes
    stderr: bytes


RunCommand = Callable[..., _CompletedProcessLike]


@dataclass(frozen=True, slots=True)
class _DeploymentPlan:
    bundle_root: Path
    header: dict[str, object]
    stream: bytes
    expected_evidence: dict[str, object]


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
        raise Phase8BDeployError(f"{label} must be a lowercase SHA256")
    return value


def _safe_relative(value: object, *, label: str, allow_root: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise Phase8BDeployError(f"{label} is not a safe relative path")
    if allow_root and value == ".":
        return value
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise Phase8BDeployError(f"{label} is not a canonical relative path")
    return value


def _strict_json_object(raw: bytes, *, label: str, maximum: int) -> dict[str, object]:
    if not raw or len(raw) > maximum:
        raise Phase8BDeployError(f"{label} byte size is invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase8BDeployError(f"{label} is not UTF-8") from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase8BDeployError(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise Phase8BDeployError(f"{label} contains non-finite number: {value}")

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except Phase8BDeployError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise Phase8BDeployError(f"{label} is not strict JSON") from exc
    if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
        raise Phase8BDeployError(f"{label} must be one JSON object")
    return cast(dict[str, object], decoded)


def _read_local_file(path: Path, *, expected_mode: int, label: str) -> bytes:
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise Phase8BDeployError(f"{label} is unavailable") from exc
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_nlink != 1
        or stat.S_IMODE(file_stat.st_mode) != expected_mode
    ):
        raise Phase8BDeployError(f"{label} filesystem identity drifted")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Phase8BDeployError(f"{label} could not be read") from exc
    if len(raw) > _MAX_FILE_BYTES:
        raise Phase8BDeployError(f"{label} exceeds the per-file transfer bound")
    return raw


def _parse_file_entries(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict) or not value or len(value) > _MAX_FILES:
        raise Phase8BDeployError("transport file inventory is invalid")
    entries: dict[str, dict[str, object]] = {}
    for raw_name, raw_entry in value.items():
        name = _safe_relative(raw_name, label="transport file path")
        if not isinstance(raw_entry, dict) or set(raw_entry) != {"sha256", "bytes", "mode"}:
            raise Phase8BDeployError(f"transport file entry fields drifted: {name}")
        digest = _require_sha256(raw_entry.get("sha256"), label=f"transport SHA256 {name}")
        byte_count = raw_entry.get("bytes")
        raw_mode = raw_entry.get("mode")
        if type(byte_count) is not int or not 0 <= byte_count <= _MAX_FILE_BYTES:
            raise Phase8BDeployError(f"transport byte count is invalid: {name}")
        if raw_mode not in {"0600", "0640"}:
            raise Phase8BDeployError(f"transport file mode is invalid: {name}")
        entries[name] = {"sha256": digest, "bytes": byte_count, "mode": raw_mode}
    return dict(sorted(entries.items()))


def _parse_directory_entries(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict) or not value or len(value) > _MAX_DIRECTORIES:
        raise Phase8BDeployError("transport directory inventory is invalid")
    entries: dict[str, dict[str, object]] = {}
    for raw_name, raw_entry in value.items():
        name = _safe_relative(raw_name, label="transport directory path", allow_root=True)
        if not isinstance(raw_entry, dict) or set(raw_entry) != {"mode"}:
            raise Phase8BDeployError(f"transport directory entry fields drifted: {name}")
        raw_mode = raw_entry.get("mode")
        if raw_mode not in {"0700", "0750"}:
            raise Phase8BDeployError(f"transport directory mode is invalid: {name}")
        entries[name] = {"mode": raw_mode}
    if entries.get(".") != {"mode": "0700"}:
        raise Phase8BDeployError("transport root mode drifted")
    return dict(sorted(entries.items()))


def _validate_permit_route(
    raw: bytes,
    *,
    config: Phase8BRemoteConfig,
    expected_permit_sha256: object,
) -> None:
    if _sha256_bytes(raw) != _require_sha256(
        expected_permit_sha256, label="transport permit SHA256"
    ):
        raise Phase8BDeployError("private permit differs from the transport inventory")
    permit = _strict_json_object(raw, label="private permit", maximum=64 * 1024)
    if raw != _canonical_json_bytes(permit):
        raise Phase8BDeployError("private permit is not canonical JSON")
    paths = permit.get("paths")
    if not isinstance(paths, dict):
        raise Phase8BDeployError("private permit paths are unavailable")
    expected_run_root = config.remote.phase8b_root
    expected_paths = {
        "project_root": config.remote.project_root,
        "run_root": expected_run_root,
        "request_path": f"{expected_run_root}/input/request.json",
        "output_root": f"{expected_run_root}/runtime/output",
        "payload_manifest_path": f"{expected_run_root}/payload_manifest.json",
        "permit_ready_path": f"{expected_run_root}/private/permit.ready.json",
        "permit_consumed_path": f"{expected_run_root}/private/permit.consumed.json",
        "run_relative": PHASE8B_RUN_RELATIVE,
        "request_relative": "input/request.json",
        "output_relative": "runtime/output",
        "payload_manifest_relative": "payload_manifest.json",
        "permit_ready_relative": "private/permit.ready.json",
        "permit_consumed_relative": "private/permit.consumed.json",
    }
    if paths != expected_paths:
        raise Phase8BDeployError("private permit is bound to a different remote route")


def _expected_evidence(
    *,
    run_root: str,
    inventory_sha256: str,
    transport_tree_sha256: str,
    directory_tree_sha256: str,
    files: Mapping[str, dict[str, object]],
    directories: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": DEPLOY_EVIDENCE_SCHEMA_VERSION,
        "status": "deployed_and_revalidated",
        "run_root": run_root,
        "transport_inventory_sha256": inventory_sha256,
        "transport_tree_sha256": transport_tree_sha256,
        "directory_tree_sha256": directory_tree_sha256,
        "file_count": len(files),
        "directory_count": len(directories),
        "files": dict(files),
        "directories": dict(directories),
        "safety": {
            "root_created": True,
            "exclusive_create_only": True,
            "nofollow_required": True,
            "overwrite_attempted": False,
            "delete_attempted": False,
            "cleanup_attempted": False,
            "chemistry_imported": False,
            "quantum_execution_started": False,
        },
    }


def _build_plan(
    *,
    config: Phase8BRemoteConfig,
    bundle_dir: Path,
    expected_transport_inventory_sha256: str,
) -> _DeploymentPlan:
    inventory_sha256 = _require_sha256(
        expected_transport_inventory_sha256,
        label="expected transport inventory SHA256",
    )
    absolute = Path(os.path.abspath(bundle_dir))
    if absolute.is_symlink() or not absolute.is_dir() or absolute.resolve(strict=True) != absolute:
        raise Phase8BDeployError("local bundle root must be an exact real directory")
    try:
        phase8b_bundle._validate_bundle_tree(  # pyright: ignore[reportPrivateUsage]
            absolute,
            expected_inventory_sha256=inventory_sha256,
        )
    except (OSError, phase8b_bundle.Phase8BBundleError) as exc:
        raise Phase8BDeployError("local immutable Phase 8B bundle validation failed") from exc

    inventory_raw = _read_local_file(
        absolute / _TRANSPORT_INVENTORY_NAME,
        expected_mode=_PUBLIC_MODE,
        label="transport inventory",
    )
    if _sha256_bytes(inventory_raw) != inventory_sha256:
        raise Phase8BDeployError("transport inventory SHA256 drifted")
    inventory = _strict_json_object(
        inventory_raw,
        label="transport inventory",
        maximum=_MAX_HEADER_BYTES,
    )
    if inventory_raw != _canonical_json_bytes(inventory):
        raise Phase8BDeployError("transport inventory is not canonical JSON")
    if set(inventory) != {
        "schema_version",
        "bundle_version",
        "payload_manifest_sha256",
        "permit_sha256",
        "files",
        "transport_tree_sha256",
        "directories",
        "directory_tree_sha256",
        "excluded_from_inventory",
    }:
        raise Phase8BDeployError("transport inventory fields drifted")
    if (
        inventory.get("schema_version") != phase8b_bundle.TRANSPORT_INVENTORY_SCHEMA_VERSION
        or inventory.get("bundle_version") != phase8b_bundle.BUNDLE_VERSION
        or inventory.get("excluded_from_inventory") != [_TRANSPORT_INVENTORY_NAME]
    ):
        raise Phase8BDeployError("transport inventory identity drifted")
    transport_tree_sha256 = _require_sha256(
        inventory.get("transport_tree_sha256"), label="transport tree SHA256"
    )
    directory_tree_sha256 = _require_sha256(
        inventory.get("directory_tree_sha256"), label="directory tree SHA256"
    )
    files = _parse_file_entries(inventory.get("files"))
    directories = _parse_directory_entries(inventory.get("directories"))

    bodies: dict[str, bytes] = {}
    for name, entry in files.items():
        mode = int(cast(str, entry["mode"]), 8)
        raw = _read_local_file(
            absolute / Path(name), expected_mode=mode, label=f"bundle file {name}"
        )
        if len(raw) != entry["bytes"] or _sha256_bytes(raw) != entry["sha256"]:
            raise Phase8BDeployError(f"bundle file identity drifted after validation: {name}")
        bodies[name] = raw
    permit_raw = bodies.get(_PERMIT_NAME)
    if permit_raw is None:
        raise Phase8BDeployError("transport inventory omitted the private permit")
    _validate_permit_route(
        permit_raw,
        config=config,
        expected_permit_sha256=inventory.get("permit_sha256"),
    )

    inventory_spec = {
        "sha256": inventory_sha256,
        "bytes": len(inventory_raw),
        "mode": "0640",
    }
    all_files = dict(files)
    if _TRANSPORT_INVENTORY_NAME in all_files:
        raise Phase8BDeployError("transport inventory contains itself")
    all_files[_TRANSPORT_INVENTORY_NAME] = inventory_spec
    all_files = dict(sorted(all_files.items()))
    bodies[_TRANSPORT_INVENTORY_NAME] = inventory_raw

    header: dict[str, object] = {
        "schema_version": DEPLOY_STREAM_SCHEMA_VERSION,
        "run_root": config.remote.phase8b_root,
        "transport_inventory_sha256": inventory_sha256,
        "transport_tree_sha256": transport_tree_sha256,
        "directory_tree_sha256": directory_tree_sha256,
        "files": all_files,
        "directories": directories,
    }
    header_raw = _canonical_json_bytes(header)
    if len(header_raw) > _MAX_HEADER_BYTES:
        raise Phase8BDeployError("directed deployment header exceeds its bound")
    stream_parts = [_MAGIC, len(header_raw).to_bytes(8, "big"), header_raw]
    stream_parts.extend(bodies[name] for name in sorted(all_files))
    stream = b"".join(stream_parts)
    if len(stream) > _MAX_TRANSFER_BYTES:
        raise Phase8BDeployError("directed deployment stdin exceeds its bound")
    evidence = _expected_evidence(
        run_root=config.remote.phase8b_root,
        inventory_sha256=inventory_sha256,
        transport_tree_sha256=transport_tree_sha256,
        directory_tree_sha256=directory_tree_sha256,
        files=all_files,
        directories=directories,
    )
    return _DeploymentPlan(
        bundle_root=absolute,
        header=header,
        stream=stream,
        expected_evidence=evidence,
    )


_REMOTE_RECEIVER_SOURCE: Final = r"""import hashlib
import json
import os
import stat
import sys

MAGIC = b"NHC_PHASE8B_DIRECTED_DEPLOY_V1\n"
STREAM_SCHEMA = "phase8b.directed-deploy-stream.v1"
EVIDENCE_SCHEMA = "phase8b.directed-deployment-evidence.v1"
INVENTORY_SCHEMA = "phase8b.transport_inventory.v2"
BUNDLE_VERSION = "phase8b-dft-smoke-v001"
RUN_RELATIVE = "data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001"
INVENTORY_NAME = "transport_inventory.json"
MAX_HEADER = 2 * 1024 * 1024
MAX_TRANSFER = 64 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_FILES = 512
MAX_DIRS = 256
CHUNK = 64 * 1024

def canonical(value):
    text = json.dumps(
        value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False
    )
    return (text + "\n").encode("utf-8")

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def require_sha(value, label):
    invalid = (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    )
    if invalid:
        raise RuntimeError(label + " must be a lowercase SHA256")
    return value

def strict_object(raw, label):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(label + " is not UTF-8") from exc
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RuntimeError(label + " contains a duplicate key")
            result[key] = value
        return result
    def nonfinite(value):
        raise RuntimeError(label + " contains a non-finite number: " + value)
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)
    except RuntimeError:
        raise
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(label + " is not strict JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(label + " must be an object")
    return value

def safe_relative(value, label, allow_root=False):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise RuntimeError(label + " is unsafe")
    if allow_root and value == ".":
        return value
    parts = value.split("/")
    invalid = (
        value.startswith("/")
        or any(part in ("", ".", "..") for part in parts)
        or "/".join(parts) != value
    )
    if invalid:
        raise RuntimeError(label + " is unsafe")
    return value

def read_exact(stream, count):
    chunks = []
    remaining = count
    while remaining:
        chunk = stream.read(min(CHUNK, remaining))
        if not chunk:
            raise RuntimeError("deployment stream ended early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

def parse_files(value):
    if not isinstance(value, dict) or not value or len(value) > MAX_FILES:
        raise RuntimeError("deployment file contract is invalid")
    result = {}
    for raw_name, raw_entry in value.items():
        name = safe_relative(raw_name, "file path")
        if not isinstance(raw_entry, dict) or set(raw_entry) != {"sha256", "bytes", "mode"}:
            raise RuntimeError("file entry fields drifted: " + name)
        digest = require_sha(raw_entry.get("sha256"), "file SHA256")
        size = raw_entry.get("bytes")
        mode = raw_entry.get("mode")
        if type(size) is not int or size < 0 or size > MAX_FILE or mode not in ("0600", "0640"):
            raise RuntimeError("file entry value drifted: " + name)
        result[name] = {"sha256": digest, "bytes": size, "mode": mode}
    return dict(sorted(result.items()))

def parse_dirs(value):
    if not isinstance(value, dict) or not value or len(value) > MAX_DIRS:
        raise RuntimeError("deployment directory contract is invalid")
    result = {}
    for raw_name, raw_entry in value.items():
        name = safe_relative(raw_name, "directory path", True)
        if not isinstance(raw_entry, dict) or set(raw_entry) != {"mode"}:
            raise RuntimeError("directory entry fields drifted: " + name)
        mode = raw_entry.get("mode")
        if mode not in ("0700", "0750"):
            raise RuntimeError("directory mode drifted: " + name)
        result[name] = {"mode": mode}
    result = dict(sorted(result.items()))
    if result.get(".") != {"mode": "0700"}:
        raise RuntimeError("deployment root mode drifted")
    return result

def file_tree_sha(files):
    digest = hashlib.sha256()
    digest.update(b"phase8b-file-tree-v1\x00")
    for name in sorted(files):
        encoded = name.encode("ascii")
        entry = files[name]
        digest.update(len(encoded).to_bytes(2, "big"))
        digest.update(encoded)
        digest.update(int(entry["mode"], 8).to_bytes(2, "big"))
        digest.update(entry["bytes"].to_bytes(8, "big"))
        digest.update(bytes.fromhex(entry["sha256"]))
    return digest.hexdigest()

def directory_tree_sha(directories):
    digest = hashlib.sha256()
    digest.update(b"phase8b-directory-tree-v1\x00")
    for name in sorted(directories):
        encoded = name.encode("ascii")
        digest.update(len(encoded).to_bytes(2, "big"))
        digest.update(encoded)
        digest.update(int(directories[name]["mode"], 8).to_bytes(2, "big"))
    return digest.hexdigest()

def open_dir(parent_fd, name):
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)

def open_relative_dir(root_fd, relative):
    descriptor = os.dup(root_fd)
    try:
        if relative and relative != ".":
            for part in relative.split("/"):
                next_descriptor = open_dir(descriptor, part)
                os.close(descriptor)
                descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise

def fsync_relative_dir(root_fd, relative):
    descriptor = open_relative_dir(root_fd, relative)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

def create_file(root_fd, name, entry, stream):
    parent, _, leaf = name.rpartition("/")
    parent_fd = open_relative_dir(root_fd, parent or ".")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(leaf, flags, int(entry["mode"], 8), dir_fd=parent_fd)
        os.fchmod(descriptor, int(entry["mode"], 8))
        digest = hashlib.sha256()
        remaining = entry["bytes"]
        while remaining:
            raw = read_exact(stream, min(CHUNK, remaining))
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise RuntimeError("short deployment write")
                view = view[written:]
            digest.update(raw)
            remaining -= len(raw)
        os.fsync(descriptor)
        actual = os.fstat(descriptor)
        if not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1:
            raise RuntimeError("created file identity drifted: " + name)
        metadata_drifted = (
            stat.S_IMODE(actual.st_mode) != int(entry["mode"], 8)
            or actual.st_size != entry["bytes"]
        )
        if metadata_drifted:
            raise RuntimeError("created file metadata drifted: " + name)
        if digest.hexdigest() != entry["sha256"]:
            raise RuntimeError("created file SHA256 drifted: " + name)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.fsync(parent_fd)
        os.close(parent_fd)

def reread_file(root_fd, name, entry):
    parent, _, leaf = name.rpartition("/")
    parent_fd = open_relative_dir(root_fd, parent or ".")
    descriptor = -1
    try:
        descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        actual = os.fstat(descriptor)
        if not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1:
            raise RuntimeError("deployed file identity drifted: " + name)
        metadata_drifted = (
            stat.S_IMODE(actual.st_mode) != int(entry["mode"], 8)
            or actual.st_size != entry["bytes"]
        )
        if metadata_drifted:
            raise RuntimeError("deployed file metadata drifted: " + name)
        digest = hashlib.sha256()
        total = 0
        while True:
            raw = os.read(descriptor, CHUNK)
            if not raw:
                break
            total += len(raw)
            if total > entry["bytes"]:
                raise RuntimeError("deployed file exceeded its bound: " + name)
            digest.update(raw)
        if total != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
            raise RuntimeError("deployed file content drifted: " + name)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)

def scan_tree(directory_fd, prefix=""):
    files = set()
    directories = {prefix or "."}
    with os.scandir(directory_fd) as iterator:
        entries = sorted(list(iterator), key=lambda entry: entry.name)
    for entry in entries:
        name = entry.name if not prefix else prefix + "/" + entry.name
        info = entry.stat(follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise RuntimeError("deployed tree contains a symlink: " + name)
        if stat.S_ISDIR(info.st_mode):
            child_fd = open_dir(directory_fd, entry.name)
            try:
                child_files, child_dirs = scan_tree(child_fd, name)
            finally:
                os.close(child_fd)
            files.update(child_files)
            directories.update(child_dirs)
        elif stat.S_ISREG(info.st_mode):
            files.add(name)
        else:
            raise RuntimeError("deployed tree contains a special file: " + name)
    return files, directories

def validate_inventory(root_fd, inventory_sha, expected_files, directories, tree_sha, dir_sha):
    inventory_entry = expected_files[INVENTORY_NAME]
    reread_file(root_fd, INVENTORY_NAME, inventory_entry)
    descriptor = os.open(INVENTORY_NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
    try:
        raw = b""
        while True:
            chunk = os.read(descriptor, CHUNK)
            if not chunk:
                break
            raw += chunk
            if len(raw) > MAX_HEADER:
                raise RuntimeError("transport inventory exceeded its bound")
    finally:
        os.close(descriptor)
    if sha(raw) != inventory_sha:
        raise RuntimeError("transport inventory SHA256 drifted after deployment")
    inventory = strict_object(raw, "transport inventory")
    if raw != canonical(inventory):
        raise RuntimeError("transport inventory is not canonical JSON")
    expected_fields = {
        "schema_version",
        "bundle_version",
        "payload_manifest_sha256",
        "permit_sha256",
        "files",
        "transport_tree_sha256",
        "directories",
        "directory_tree_sha256",
        "excluded_from_inventory",
    }
    if set(inventory) != expected_fields:
        raise RuntimeError("transport inventory fields drifted")
    identity_drifted = (
        inventory.get("schema_version") != INVENTORY_SCHEMA
        or inventory.get("bundle_version") != BUNDLE_VERSION
        or inventory.get("excluded_from_inventory") != [INVENTORY_NAME]
    )
    if identity_drifted:
        raise RuntimeError("transport inventory identity drifted")
    inventory_files = parse_files(inventory.get("files"))
    expected_inventory_files = {
        name: entry
        for name, entry in expected_files.items()
        if name != INVENTORY_NAME
    }
    if inventory_files != expected_inventory_files:
        raise RuntimeError("transport inventory file contract drifted")
    if parse_dirs(inventory.get("directories")) != directories:
        raise RuntimeError("transport inventory directory contract drifted")
    if (
        inventory.get("transport_tree_sha256") != tree_sha
        or file_tree_sha(inventory_files) != tree_sha
    ):
        raise RuntimeError("transport file tree SHA256 drifted")
    if (
        inventory.get("directory_tree_sha256") != dir_sha
        or directory_tree_sha(directories) != dir_sha
    ):
        raise RuntimeError("transport directory tree SHA256 drifted")

def receive():
    if len(sys.argv) != 3:
        raise RuntimeError("receiver arguments drifted")
    run_root = sys.argv[1]
    expected_inventory_sha = require_sha(sys.argv[2], "expected inventory SHA256")
    suffix = "/" + RUN_RELATIVE
    unsafe_root = (
        not run_root.startswith("/")
        or run_root == "/"
        or os.path.normpath(run_root) != run_root
        or not run_root.endswith(suffix)
    )
    if unsafe_root:
        raise RuntimeError("remote run root is unsafe")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise RuntimeError("required nofollow directory APIs are unavailable")
    stream = sys.stdin.buffer
    if read_exact(stream, len(MAGIC)) != MAGIC:
        raise RuntimeError("deployment stream magic drifted")
    header_size = int.from_bytes(read_exact(stream, 8), "big")
    if header_size <= 0 or header_size > MAX_HEADER:
        raise RuntimeError("deployment header size is invalid")
    header_raw = read_exact(stream, header_size)
    header = strict_object(header_raw, "deployment header")
    if header_raw != canonical(header):
        raise RuntimeError("deployment header is not canonical JSON")
    expected_header_fields = {
        "schema_version",
        "run_root",
        "transport_inventory_sha256",
        "transport_tree_sha256",
        "directory_tree_sha256",
        "files",
        "directories",
    }
    if set(header) != expected_header_fields:
        raise RuntimeError("deployment header fields drifted")
    header_identity_drifted = (
        header.get("schema_version") != STREAM_SCHEMA
        or header.get("run_root") != run_root
        or header.get("transport_inventory_sha256") != expected_inventory_sha
    )
    if header_identity_drifted:
        raise RuntimeError("deployment header identity drifted")
    tree_sha = require_sha(header.get("transport_tree_sha256"), "transport tree SHA256")
    dir_sha = require_sha(header.get("directory_tree_sha256"), "directory tree SHA256")
    files = parse_files(header.get("files"))
    directories = parse_dirs(header.get("directories"))
    if INVENTORY_NAME not in files or files[INVENTORY_NAME]["sha256"] != expected_inventory_sha:
        raise RuntimeError("deployment omitted its exact transport inventory")
    total = len(MAGIC) + 8 + header_size + sum(entry["bytes"] for entry in files.values())
    if total > MAX_TRANSFER:
        raise RuntimeError("deployment stream exceeds its bound")

    parent = os.path.dirname(run_root)
    leaf = os.path.basename(run_root)
    if os.path.realpath(parent) != parent or not os.path.isdir(parent) or os.path.islink(parent):
        raise RuntimeError("remote run parent is unsafe")
    if os.path.lexists(run_root):
        raise FileExistsError("the fixed Phase 8B run root already exists")
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = -1
    try:
        os.mkdir(leaf, int(directories["."]["mode"], 8), dir_fd=parent_fd)
        root_fd = open_dir(parent_fd, leaf)
        os.fchmod(root_fd, int(directories["."]["mode"], 8))
        os.fsync(root_fd)
        os.fsync(parent_fd)
        deployment_directories = sorted(
            (name for name in directories if name != "."),
            key=lambda item: (len(item.split("/")), item),
        )
        for name in deployment_directories:
            parent_name, _, child = name.rpartition("/")
            directory_parent_fd = open_relative_dir(root_fd, parent_name or ".")
            created_fd = -1
            try:
                os.mkdir(child, int(directories[name]["mode"], 8), dir_fd=directory_parent_fd)
                created_fd = open_dir(directory_parent_fd, child)
                os.fchmod(created_fd, int(directories[name]["mode"], 8))
                os.fsync(created_fd)
                os.fsync(directory_parent_fd)
            finally:
                if created_fd >= 0:
                    os.close(created_fd)
                os.close(directory_parent_fd)
        for name in sorted(files):
            create_file(root_fd, name, files[name], stream)
        if stream.read(1) != b"":
            raise RuntimeError("deployment stream contains trailing bytes")
        for name in sorted(files):
            reread_file(root_fd, name, files[name])
        actual_files, actual_directories = scan_tree(root_fd)
        if actual_files != set(files) or actual_directories != set(directories):
            raise RuntimeError("deployed tree contains extra or missing entries")
        for name, entry in directories.items():
            descriptor = open_relative_dir(root_fd, name)
            try:
                info = os.fstat(descriptor)
                mode_drifted = stat.S_IMODE(info.st_mode) != int(entry["mode"], 8)
                if not stat.S_ISDIR(info.st_mode) or mode_drifted:
                    raise RuntimeError("deployed directory mode drifted: " + name)
            finally:
                os.close(descriptor)
        validate_inventory(root_fd, expected_inventory_sha, files, directories, tree_sha, dir_sha)
        fsync_order = sorted(
            directories,
            key=lambda item: (len(item.split("/")), item),
            reverse=True,
        )
        for name in fsync_order:
            fsync_relative_dir(root_fd, name)
        os.fsync(parent_fd)
    finally:
        if root_fd >= 0:
            os.close(root_fd)
        os.close(parent_fd)

    evidence = {
        "schema_version": EVIDENCE_SCHEMA,
        "status": "deployed_and_revalidated",
        "run_root": run_root,
        "transport_inventory_sha256": expected_inventory_sha,
        "transport_tree_sha256": tree_sha,
        "directory_tree_sha256": dir_sha,
        "file_count": len(files),
        "directory_count": len(directories),
        "files": files,
        "directories": directories,
        "safety": {
            "root_created": True,
            "exclusive_create_only": True,
            "nofollow_required": True,
            "overwrite_attempted": False,
            "delete_attempted": False,
            "cleanup_attempted": False,
            "chemistry_imported": False,
            "quantum_execution_started": False,
        },
    }
    sys.stdout.buffer.write(canonical(evidence))
    sys.stdout.buffer.flush()

try:
    receive()
except Exception as exc:
    message = "phase8b directed receiver failed: " + type(exc).__name__ + ": " + str(exc)
    sys.stderr.write(message[:4096] + "\n")
    raise SystemExit(1)
"""


def phase8b_deploy_command(
    config: Phase8BRemoteConfig,
    *,
    expected_transport_inventory_sha256: str,
) -> tuple[str, ...]:
    """Return the one fixed SSH argv used by the directed receiver."""

    digest = _require_sha256(
        expected_transport_inventory_sha256,
        label="expected transport inventory SHA256",
    )
    remote_command = " ".join(
        (
            "exec",
            "python3",
            "-I",
            "-B",
            "-c",
            shlex.quote(_REMOTE_RECEIVER_SOURCE),
            shlex.quote(config.remote.phase8b_root),
            digest,
        )
    )
    return (
        "ssh",
        *config.ssh_options(),
        config.connection.ssh_alias,
        remote_command,
    )


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        with suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2.0)


def _bounded_run(
    command: tuple[str, ...],
    *,
    input: bytes,
    timeout: float,
) -> _Completed:
    """Run SSH with hard stdin/stdout/stderr and elapsed-time bounds."""

    if len(input) > _MAX_TRANSFER_BYTES:
        raise Phase8BDeployError("directed deployment stdin exceeds its bound")
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise Phase8BDeployError("Phase 8B SSH deployment could not start") from exc
    if process.stdin is None or process.stdout is None or process.stderr is None:
        _terminate(process)
        raise Phase8BDeployError("Phase 8B SSH pipes are unavailable")

    selector = selectors.DefaultSelector()
    streams = (process.stdin, process.stdout, process.stderr)
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
    selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    offset = 0
    stdout = bytearray()
    stderr = bytearray()
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise Phase8BDeployError("Phase 8B SSH deployment timed out")
            events = selector.select(min(remaining, 0.25))
            for key, _mask in events:
                file_object = key.fileobj
                descriptor = key.fd
                label = cast(str, key.data)
                if label == "stdin":
                    if offset >= len(input):
                        selector.unregister(file_object)
                        process.stdin.close()
                        continue
                    try:
                        written = os.write(descriptor, input[offset : offset + _IO_CHUNK_BYTES])
                    except BrokenPipeError:
                        selector.unregister(file_object)
                        process.stdin.close()
                    else:
                        offset += written
                    continue
                try:
                    chunk = os.read(descriptor, _IO_CHUNK_BYTES)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(file_object)
                    if label == "stdout":
                        process.stdout.close()
                    else:
                        process.stderr.close()
                    continue
                target = stdout if label == "stdout" else stderr
                limit = _MAX_STDOUT_BYTES if label == "stdout" else _MAX_STDERR_BYTES
                if len(target) + len(chunk) > limit:
                    raise Phase8BDeployError(f"Phase 8B SSH {label} exceeded its bound")
                target.extend(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            raise Phase8BDeployError("Phase 8B SSH deployment timed out")
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise Phase8BDeployError("Phase 8B SSH deployment timed out") from exc
        if returncode == 0 and offset != len(input):
            raise Phase8BDeployError(
                "Phase 8B SSH closed stdin before the complete directed stream"
            )
    except BaseException:
        _terminate(process)
        raise
    finally:
        selector.close()
        for stream in streams:
            if not stream.closed:
                stream.close()
    return _Completed(returncode=returncode, stdout=bytes(stdout), stderr=bytes(stderr))


def _validate_remote_evidence(
    raw: bytes,
    *,
    expected: dict[str, object],
) -> dict[str, object]:
    evidence = _strict_json_object(
        raw,
        label="remote deployment evidence",
        maximum=_MAX_STDOUT_BYTES,
    )
    if raw != _canonical_json_bytes(evidence):
        raise Phase8BDeployError("remote deployment evidence is not canonical JSON")
    if evidence != expected:
        raise Phase8BDeployError("remote deployment evidence differs from the directed plan")
    return evidence


def deploy_phase8b_bundle(
    *,
    config_path: Path,
    bundle_dir: Path,
    expected_transport_inventory_sha256: str,
    timeout_seconds: float = 300.0,
    run_command: RunCommand | None = None,
) -> dict[str, object]:
    """Create and revalidate the exact absent remote tree in one SSH call."""

    if timeout_seconds <= 0.0 or timeout_seconds > 600.0:
        raise ValueError("deployment timeout must be in (0, 600]")
    config = load_phase8b_remote_config(config_path)
    config.require_directed_write()
    plan = _build_plan(
        config=config,
        bundle_dir=bundle_dir,
        expected_transport_inventory_sha256=expected_transport_inventory_sha256,
    )
    command = phase8b_deploy_command(
        config,
        expected_transport_inventory_sha256=expected_transport_inventory_sha256,
    )
    command_runner = cast(RunCommand, _bounded_run) if run_command is None else run_command
    try:
        completed = command_runner(command, input=plan.stream, timeout=timeout_seconds)
    except Phase8BDeployError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise Phase8BDeployError("Phase 8B SSH deployment could not run") from exc
    if len(completed.stdout) > _MAX_STDOUT_BYTES:
        raise Phase8BDeployError("Phase 8B SSH stdout exceeded its bound")
    if len(completed.stderr) > _MAX_STDERR_BYTES:
        raise Phase8BDeployError("Phase 8B SSH stderr exceeded its bound")
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:1024]
        suffix = f": {detail}" if detail else ""
        raise Phase8BDeployError(
            f"Phase 8B directed deployment exited nonzero: {completed.returncode}{suffix}"
        )
    if completed.stderr:
        raise Phase8BDeployError("Phase 8B directed deployment produced unexpected stderr")
    return _validate_remote_evidence(completed.stdout, expected=plan.expected_evidence)


__all__ = [
    "DEPLOY_EVIDENCE_SCHEMA_VERSION",
    "DEPLOY_STREAM_SCHEMA_VERSION",
    "Phase8BDeployError",
    "deploy_phase8b_bundle",
    "phase8b_deploy_command",
]
