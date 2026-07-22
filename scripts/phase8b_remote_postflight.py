#!/usr/bin/env python3
"""Collect or launch the read-only Phase 8B terminal postflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Final, cast

SCHEMA_VERSION: Final = "phase8b.remote-postflight.v1"
EXPECTED_PHASE8B_RELATIVE: Final = "data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001"
EXPECTED_PHASE7_FILE_COUNT: Final = 27
EXPECTED_PHASE7_TREE_SHA256: Final = (
    "9b92a1f453274995661bd262e607239a86f4992bf4cc2809a311207dceadbecb"
)
EXPECTED_PROJECT_SOURCE_SHA256: Final[dict[str, str]] = {
    "env/envs/molenv.sh": "e9b3e124f53a10e84c43cfc71a56af3ddd56a86f082610593d2b23ed9692ea6f",
    "scripts/mol/gen_3d.py": "d23c7ad9a6e35948949f6485b53caafb0f3f5705148f642e3a4a30fb589a946a",
    "scripts/mol/structure_gen.py": (
        "a50b50b9967ac9e8203b398fe69f3daebf40a144f37dae8e0aa086e613ad1365"
    ),
}
FROZEN_IDENTITY: Final[dict[str, object]] = {
    "inchikey": "QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
    "request_id": "phase8b-qxh-smoke-v001",
    "attempt_id": "attempt-phase8b-qxh-v001",
}
FROZEN_PROTOCOL_SHA256: Final = "266b06e0d49cb6e3067bcfeb6d62f0712852e96768c4205b49fffcb3df52fe92"
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
THREAD_ENVIRONMENT: Final[dict[str, str]] = {
    "BLIS_NUM_THREADS": "4",
    "GOTO_NUM_THREADS": "4",
    "MKL_DYNAMIC": "FALSE",
    "MKL_NUM_THREADS": "4",
    "NUMEXPR_NUM_THREADS": "4",
    "OMP_DYNAMIC": "FALSE",
    "OMP_MAX_ACTIVE_LEVELS": "1",
    "OMP_NESTED": "FALSE",
    "OMP_NUM_THREADS": "4",
    "OMP_THREAD_LIMIT": "4",
    "OMP_WAIT_POLICY": "PASSIVE",
    "OPENBLAS_NUM_THREADS": "4",
    "VECLIB_MAXIMUM_THREADS": "4",
}
RUNNER_SOURCE_PATHS: Final[frozenset[str]] = frozenset(
    {
        "nhc_deprot_ranker/__init__.py",
        "nhc_deprot_ranker/constants.py",
        "nhc_deprot_ranker/data/__init__.py",
        "nhc_deprot_ranker/data/provenance.py",
        "nhc_deprot_ranker/quantum/__init__.py",
        "nhc_deprot_ranker/quantum/linux_guardian.py",
        "nhc_deprot_ranker/quantum/phase8b_authority.py",
        "nhc_deprot_ranker/quantum/phase8b_execution.py",
        "nhc_deprot_ranker/quantum/phase8b_permit.py",
        "nhc_deprot_ranker/quantum/phase8b_runtime.py",
        "nhc_deprot_ranker/quantum/process_supervisor.py",
        "nhc_deprot_ranker/quantum/two_endpoint.py",
        "nhc_deprot_ranker/quantum/worker.py",
        "nhc_deprot_ranker/quantum/worker_bootstrap.py",
    }
)

_MAX_JSON_BYTES: Final = 4 * 1024 * 1024
_MAX_FILE_BYTES: Final = 16 * 1024 * 1024
_MAX_TREE_BYTES: Final = 128 * 1024 * 1024
_MAX_FILES: Final = 1024
_MAX_DIRECTORIES: Final = 512
_SHA_RE: Final = re.compile(r"[0-9a-f]{64}")
_SAFE_ATTEMPT_TEMP_RE: Final = re.compile(
    r"(?:\.worker-|\.tmp-)attempt-phase8b-qxh-v001-[A-Za-z0-9_.-]+"
)
_RECEIPT_OUTCOMES: Final = {
    "clean",
    "permit_consumption_failed",
    "authority_failed",
    "spawn_failed",
    "registration_failed",
    "worker_guard_failed",
    "supervisor_nonzero",
    "cleanup_failed",
    "internal_error",
}
_CLAIM_REQUIRED_OUTCOMES: Final = {
    "clean",
    "worker_guard_failed",
    "supervisor_nonzero",
    "cleanup_failed",
}
_STATIC_FILE_MODE: Final = 0o640
_DYNAMIC_FILE_MODE: Final = 0o600
_CONSUMED_MODE: Final = 0o400


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise RuntimeError(label + " must be a lowercase SHA256")
    return value


def _strict_object(raw: bytes, label: str, *, canonical: bool = True) -> dict[str, object]:
    if not raw or len(raw) > _MAX_JSON_BYTES:
        raise RuntimeError(label + " size is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError(label + " contains a duplicate key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise RuntimeError(label + " contains a non-finite number: " + value)

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except RuntimeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(label + " is not strict JSON") from exc
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise RuntimeError(label + " must be an object")
    result = cast(dict[str, object], value)
    if canonical and raw != _canonical(result):
        raise RuntimeError(label + " is not canonical JSON")
    return result


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise RuntimeError(label + " must be an object")
    return cast(dict[str, object], value)


def _exact(value: dict[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise RuntimeError(label + " fields drifted")


def _safe_relative(raw: object, label: str) -> str:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise RuntimeError(label + " is not a safe path")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or path.as_posix() != raw
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RuntimeError(label + " is not a canonical relative path")
    return raw


def _safe_run_relative(raw: str, phase: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or path.as_posix() != raw
        or ".." in path.parts
        or len(path.parts) != 3
        or path.parts[:2] != ("data", "runs")
        or not path.parts[-1].startswith("nhc_deprot_ranker_" + phase + "_")
    ):
        raise RuntimeError("unsafe " + phase + " run identity")
    return path


def _read_file(
    root: Path,
    relative: str,
    *,
    expected_mode: int | None = None,
    maximum: int = _MAX_FILE_BYTES,
    allow_empty: bool = False,
) -> tuple[bytes, int]:
    name = _safe_relative(relative, "file path")
    path = root.joinpath(*PurePosixPath(name).parts)
    if path.is_symlink():
        raise RuntimeError("file is a symlink: " + name)
    try:
        if path.resolve(strict=True) != path:
            raise RuntimeError("file traverses a symlink: " + name)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError("file cannot be opened safely: " + name) from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or (opened.st_size == 0 and not allow_empty)
            or opened.st_size > maximum
        ):
            raise RuntimeError("file identity or size is unsafe: " + name)
        mode = stat.S_IMODE(opened.st_mode)
        if expected_mode is not None and mode != expected_mode:
            raise RuntimeError("file mode drifted: " + name)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise RuntimeError("file exceeded its read bound: " + name)
        finished = os.fstat(descriptor)
        current = os.stat(path, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_uid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        identity = tuple(getattr(opened, field) for field in fields)
        if (
            tuple(getattr(finished, field) for field in fields) != identity
            or tuple(getattr(current, field) for field in fields) != identity
        ):
            raise RuntimeError("file changed while read: " + name)
        raw = b"".join(chunks)
        if len(raw) != opened.st_size:
            raise RuntimeError("file size changed while read: " + name)
        return raw, mode
    finally:
        os.close(descriptor)


def _file_entry_map(value: object) -> dict[str, dict[str, object]]:
    entries = _object(value, "transport files")
    if not entries or len(entries) > _MAX_FILES:
        raise RuntimeError("transport file count is invalid")
    result: dict[str, dict[str, object]] = {}
    total = 0
    for raw_name, raw_entry in entries.items():
        name = _safe_relative(raw_name, "transport file")
        entry = _object(raw_entry, "transport file entry")
        _exact(entry, {"sha256", "bytes", "mode"}, "transport file entry")
        size = entry["bytes"]
        mode = entry["mode"]
        if (
            type(size) is not int
            or size <= 0
            or size > _MAX_FILE_BYTES
            or not isinstance(mode, str)
            or mode not in {"0600", "0640"}
        ):
            raise RuntimeError("transport file metadata is invalid: " + name)
        _require_sha(entry["sha256"], "transport file hash")
        total += size
        if total > _MAX_TREE_BYTES:
            raise RuntimeError("transport file tree exceeds its bound")
        result[name] = entry
    return result


def _directory_entry_map(value: object) -> dict[str, dict[str, object]]:
    entries = _object(value, "transport directories")
    if not entries or len(entries) > _MAX_DIRECTORIES:
        raise RuntimeError("transport directory count is invalid")
    result: dict[str, dict[str, object]] = {}
    for raw_name, raw_entry in entries.items():
        name = raw_name if raw_name == "." else _safe_relative(raw_name, "transport directory")
        entry = _object(raw_entry, "transport directory entry")
        _exact(entry, {"mode"}, "transport directory entry")
        if entry["mode"] not in {"0700", "0750"}:
            raise RuntimeError("transport directory mode is invalid: " + name)
        result[name] = entry
    return result


def _file_tree_sha(entries: dict[str, dict[str, object]]) -> str:
    digest = hashlib.sha256()
    digest.update(b"phase8b-file-tree-v1\x00")
    for name in sorted(entries):
        entry = entries[name]
        encoded = name.encode("ascii")
        digest.update(len(encoded).to_bytes(2, "big"))
        digest.update(encoded)
        digest.update(int(cast(str, entry["mode"]), 8).to_bytes(2, "big"))
        digest.update(cast(int, entry["bytes"]).to_bytes(8, "big"))
        digest.update(bytes.fromhex(cast(str, entry["sha256"])))
    return digest.hexdigest()


def _directory_tree_sha(entries: dict[str, dict[str, object]]) -> str:
    digest = hashlib.sha256()
    digest.update(b"phase8b-directory-tree-v1\x00")
    for name in sorted(entries):
        encoded = name.encode("ascii")
        digest.update(len(encoded).to_bytes(2, "big"))
        digest.update(encoded)
        digest.update(int(cast(str, entries[name]["mode"]), 8).to_bytes(2, "big"))
    return digest.hexdigest()


def _tree(root: Path) -> tuple[set[str], set[str]]:
    if root.is_symlink() or not root.is_dir() or root.resolve(strict=True) != root:
        raise RuntimeError("run root is missing or unsafe")
    files: set[str] = set()
    directories: set[str] = {"."}
    total = 0
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise RuntimeError("run tree contains a symlink: " + name)
        if info.st_uid != os.geteuid():
            raise RuntimeError("run tree ownership drifted: " + name)
        if stat.S_ISDIR(info.st_mode):
            directories.add(name)
        elif stat.S_ISREG(info.st_mode):
            files.add(name)
            total += info.st_size
        else:
            raise RuntimeError("run tree contains a special file: " + name)
        if (
            len(files) > _MAX_FILES
            or len(directories) > _MAX_DIRECTORIES
            or total > _MAX_TREE_BYTES
        ):
            raise RuntimeError("run tree exceeds its bound")
    return files, directories


def _phase7_tree(root: Path) -> tuple[int, str]:
    if root.is_symlink() or not root.is_dir() or root.resolve(strict=True) != root:
        raise RuntimeError("Phase 7 root is missing or unsafe")
    mapping: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Phase 7 tree contains a symlink")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            raw, _mode = _read_file(root, name, allow_empty=True)
            mapping[name] = _sha(raw)
    canonical = json.dumps(
        mapping, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return len(mapping), _sha(canonical)


def _project_sources(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in sorted(EXPECTED_PROJECT_SOURCE_SHA256):
        raw, _mode = _read_file(root, name)
        result[name] = _sha(raw)
    return result


def _validate_payload_and_request(
    run_root: Path,
    inventory: dict[str, object],
    files: dict[str, dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    payload_raw, _ = _read_file(run_root, "payload_manifest.json", expected_mode=_STATIC_FILE_MODE)
    if _sha(payload_raw) != inventory["payload_manifest_sha256"]:
        raise RuntimeError("payload manifest hash drifted")
    payload = _strict_object(payload_raw, "payload manifest")
    _exact(
        payload,
        {
            "schema_version",
            "bundle_version",
            "identity",
            "resources",
            "source_relative_paths",
            "artifact_sha256",
            "files",
            "payload_tree_sha256",
            "directories",
            "directory_tree_sha256",
            "excluded_from_manifest",
        },
        "payload manifest",
    )
    identity = _object(payload["identity"], "payload identity")
    if (
        payload["schema_version"] != "phase8b.payload_manifest.v2"
        or payload["bundle_version"] != "phase8b-dft-smoke-v001"
        or payload["resources"] != FROZEN_RESOURCES
        or identity.get("inchikey") != FROZEN_IDENTITY["inchikey"]
        or identity.get("request_id") != FROZEN_IDENTITY["request_id"]
        or identity.get("attempt_id") != FROZEN_IDENTITY["attempt_id"]
        or identity.get("protocol_sha256") != FROZEN_PROTOCOL_SHA256
        or identity.get("endpoint_order") != ["cation", "neutral"]
        or payload["excluded_from_manifest"]
        != ["payload_manifest.json", "private/permit.ready.json", "transport_inventory.json"]
    ):
        raise RuntimeError("payload identity drifted")
    source_paths = payload["source_relative_paths"]
    if not isinstance(source_paths, list) or set(source_paths) != RUNNER_SOURCE_PATHS:
        raise RuntimeError("runner source closure drifted")
    payload_files = _file_entry_map(payload["files"])
    expected_payload_files = {
        name: entry
        for name, entry in files.items()
        if name not in {"payload_manifest.json", "private/permit.ready.json"}
    }
    if payload_files != expected_payload_files or payload["payload_tree_sha256"] != _file_tree_sha(
        payload_files
    ):
        raise RuntimeError("payload file contract drifted")
    if (
        payload["directories"] != inventory["directories"]
        or payload["directory_tree_sha256"] != inventory["directory_tree_sha256"]
    ):
        raise RuntimeError("payload directory contract drifted")

    request_raw, _ = _read_file(run_root, "input/request.json", expected_mode=_STATIC_FILE_MODE)
    request_hash = _sha(request_raw)
    if request_hash != identity.get("request_sha256"):
        raise RuntimeError("request hash drifted")
    request = _strict_object(request_raw, "request")
    _exact(
        request,
        {
            "schema_version",
            "request_id",
            "inchikey",
            "execution_authorized",
            "timeout_seconds",
            "runner_source_sha256",
            "protocol",
            "endpoints",
        },
        "request",
    )
    protocol_raw = _canonical(request["protocol"])
    endpoints = _object(request["endpoints"], "request endpoints")
    if (
        request["schema_version"] != "nhc-two-endpoint-request-v1"
        or request["request_id"] != FROZEN_IDENTITY["request_id"]
        or request["inchikey"] != FROZEN_IDENTITY["inchikey"]
        or request["execution_authorized"] is not True
        or request["timeout_seconds"] != 7_200
        or request["runner_source_sha256"] != identity.get("runner_source_sha256")
        or _sha(protocol_raw) != FROZEN_PROTOCOL_SHA256
        or set(endpoints) != {"cation", "neutral"}
    ):
        raise RuntimeError("request identity drifted")
    expected_endpoints = {
        "cation": (1, FROZEN_INPUT_SHA256["cation_xyz"]),
        "neutral": (0, FROZEN_INPUT_SHA256["neutral_xyz"]),
    }
    for name, (charge, xyz_hash) in expected_endpoints.items():
        endpoint = _object(endpoints[name], name + " request")
        if (
            set(endpoint) != {"xyz_path", "xyz_sha256", "charge", "multiplicity"}
            or endpoint["charge"] != charge
            or endpoint["multiplicity"] != 1
            or endpoint["xyz_sha256"] != xyz_hash
        ):
            raise RuntimeError(name + " request drifted")
    return payload, request


def _validate_permit(
    project_root: Path,
    run_root: Path,
    inventory: dict[str, object],
    payload: dict[str, object],
) -> tuple[str, bytes]:
    ready = run_root / "private/permit.ready.json"
    if os.path.lexists(ready):
        raise RuntimeError("ready permit remains present")
    consumed_raw, mode = _read_file(
        run_root,
        "private/permit.consumed.json",
        expected_mode=_CONSUMED_MODE,
        maximum=64 * 1024,
    )
    permit_hash = _sha(consumed_raw)
    if permit_hash != inventory["permit_sha256"] or mode != _CONSUMED_MODE:
        raise RuntimeError("consumed permit hash or mode drifted")
    permit = _strict_object(consumed_raw, "consumed permit")
    _exact(permit, {"schema_version", "authorization", "identity", "resources", "paths"}, "permit")
    authorization = permit["authorization"]
    expected_authorization = {
        "one_shot": True,
        "server_write_authorized": True,
        "quantum_execution_authorized": True,
        "candidate_replacement_authorized": False,
        "second_attempt_authorized": False,
        "resume_authorized": False,
    }
    identity = _object(permit["identity"], "permit identity")
    payload_identity = _object(payload["identity"], "payload identity")
    expected_identity = {
        **FROZEN_IDENTITY,
        "endpoint_order": ["cation", "neutral"],
        "protocol_sha256": FROZEN_PROTOCOL_SHA256,
        "request_sha256": payload_identity["request_sha256"],
        "runner_source_sha256": payload_identity["runner_source_sha256"],
        "payload_manifest_sha256": inventory["payload_manifest_sha256"],
        "input_sha256": FROZEN_INPUT_SHA256,
    }
    paths = _object(permit["paths"], "permit paths")
    expected_paths = {
        "project_root": project_root.as_posix(),
        "run_root": run_root.as_posix(),
        "request_path": (run_root / "input/request.json").as_posix(),
        "output_root": (run_root / "runtime/output").as_posix(),
        "payload_manifest_path": (run_root / "payload_manifest.json").as_posix(),
        "permit_ready_path": (run_root / "private/permit.ready.json").as_posix(),
        "permit_consumed_path": (run_root / "private/permit.consumed.json").as_posix(),
        "run_relative": EXPECTED_PHASE8B_RELATIVE,
        "request_relative": "input/request.json",
        "output_relative": "runtime/output",
        "payload_manifest_relative": "payload_manifest.json",
        "permit_ready_relative": "private/permit.ready.json",
        "permit_consumed_relative": "private/permit.consumed.json",
    }
    if (
        permit["schema_version"] != "nhc-phase8b-private-permit-v1"
        or authorization != expected_authorization
        or identity != expected_identity
        or permit["resources"] != FROZEN_RESOURCES
        or paths != expected_paths
    ):
        raise RuntimeError("consumed permit binding drifted")
    return permit_hash, consumed_raw


def _parse_identity(value: object, label: str) -> dict[str, object]:
    identity = _object(value, label)
    _exact(
        identity,
        {"pid", "ppid", "pgid", "sid", "starttime_ticks", "state", "boot_id", "cpus_allowed"},
        label,
    )
    for name in ("pid", "pgid", "sid", "starttime_ticks"):
        if type(identity[name]) is not int or cast(int, identity[name]) <= 1:
            raise RuntimeError(label + " identity is invalid")
    if type(identity["ppid"]) is not int or identity["ppid"] < 0:
        raise RuntimeError(label + " parent identity is invalid")
    cpus = identity["cpus_allowed"]
    if cpus != [0, 1, 2, 3]:
        raise RuntimeError(label + " affinity drifted")
    if not isinstance(identity["boot_id"], str) or not identity["boot_id"]:
        raise RuntimeError(label + " boot identity is invalid")
    return identity


def _stable_identity_projection(identity: dict[str, object]) -> dict[str, object]:
    """Return process identity fields that cannot change while a PID remains the same."""

    return {
        name: identity[name]
        for name in (
            "pid",
            "ppid",
            "pgid",
            "sid",
            "starttime_ticks",
            "boot_id",
            "cpus_allowed",
        )
    }


def _guardian_result(value: object, label: str) -> dict[str, object] | None:
    if value is None:
        return None
    result = _object(value, label)
    _exact(
        result,
        {
            "outcome",
            "trigger",
            "term_sent",
            "kill_sent",
            "group_cleanup_confirmed",
            "duration_ns",
            "error_message",
        },
        label,
    )
    if (
        result["outcome"]
        not in {
            "clean",
            "deadline",
            "abort",
            "affinity_violation",
            "identity_mismatch",
            "cleanup_failed",
        }
        or type(result["term_sent"]) is not bool
        or type(result["kill_sent"]) is not bool
        or type(result["group_cleanup_confirmed"]) is not bool
        or type(result["duration_ns"]) is not int
        or result["duration_ns"] < 0
    ):
        raise RuntimeError(label + " values drifted")
    return result


def _read_optional_json(run_root: Path, name: str) -> tuple[dict[str, object], bytes] | None:
    path = run_root.joinpath(*PurePosixPath(name).parts)
    if not os.path.lexists(path):
        return None
    raw, _ = _read_file(run_root, name, expected_mode=_DYNAMIC_FILE_MODE)
    return _strict_object(raw, name), raw


def _validate_receipt_chain(
    run_root: Path,
    *,
    permit_sha256: str,
    expected_inventory_sha256: str,
    inventory: dict[str, object],
    payload: dict[str, object],
) -> tuple[
    dict[str, object],
    str,
    str | None,
    str | None,
    str | None,
    dict[str, object] | None,
    dict[str, dict[str, object]],
]:
    receipt_raw, _ = _read_file(
        run_root, "private/guardian_receipt.json", expected_mode=_DYNAMIC_FILE_MODE
    )
    receipt = _strict_object(receipt_raw, "guardian receipt")
    _exact(
        receipt,
        {
            "schema_version",
            "transaction_id",
            "permit_sha256",
            "absolute_deadline_ns",
            "started_monotonic_ns",
            "finished_monotonic_ns",
            "outcome",
            "error_code",
            "authority_validated",
            "acknowledgement_published",
            "worker_registration_sha256",
            "compute_claim_sha256",
            "supervisor_returncode",
            "guardian",
            "supervisor",
            "worker",
            "worker_guardian_result",
            "supervisor_guardian_result",
        },
        "guardian receipt",
    )
    if (
        receipt["schema_version"] != "nhc-phase8b-guardian-receipt-v1"
        or receipt["transaction_id"] != FROZEN_IDENTITY["attempt_id"]
        or receipt["permit_sha256"] != permit_sha256
        or receipt["outcome"] not in _RECEIPT_OUTCOMES
    ):
        raise RuntimeError("guardian receipt identity drifted")
    for name in ("absolute_deadline_ns", "started_monotonic_ns", "finished_monotonic_ns"):
        if type(receipt[name]) is not int or cast(int, receipt[name]) <= 0:
            raise RuntimeError("guardian receipt timing is invalid")
    if (
        cast(int, receipt["started_monotonic_ns"]) > cast(int, receipt["finished_monotonic_ns"])
        or cast(int, receipt["absolute_deadline_ns"]) - cast(int, receipt["started_monotonic_ns"])
        != 7_200_000_000_000
    ):
        raise RuntimeError("guardian receipt deadline drifted")
    if (
        type(receipt["authority_validated"]) is not bool
        or type(receipt["acknowledgement_published"]) is not bool
    ):
        raise RuntimeError("guardian receipt booleans drifted")
    if (
        receipt["supervisor_returncode"] is not None
        and type(receipt["supervisor_returncode"]) is not int
    ):
        raise RuntimeError("guardian receipt return code drifted")
    if receipt["error_code"] is not None and (
        not isinstance(receipt["error_code"], str) or len(receipt["error_code"]) > 96
    ):
        raise RuntimeError("guardian receipt error code drifted")
    if receipt["worker_registration_sha256"] is not None:
        _require_sha(receipt["worker_registration_sha256"], "receipt registration hash")
    if receipt["compute_claim_sha256"] is not None:
        _require_sha(receipt["compute_claim_sha256"], "receipt compute claim hash")
    identities: dict[str, dict[str, object]] = {
        "guardian": _parse_identity(receipt["guardian"], "guardian")
    }
    for role in ("supervisor", "worker"):
        if receipt[role] is not None:
            identities[role] = _parse_identity(receipt[role], role)
    worker_result = _guardian_result(receipt["worker_guardian_result"], "worker guardian result")
    _guardian_result(receipt["supervisor_guardian_result"], "supervisor guardian result")
    if receipt["outcome"] == "clean" and (
        receipt["error_code"] is not None
        or receipt["authority_validated"] is not True
        or receipt["acknowledgement_published"] is not True
        or receipt["supervisor_returncode"] != 0
        or worker_result is None
        or worker_result["outcome"] != "clean"
        or worker_result["group_cleanup_confirmed"] is not True
        or cast(int, receipt["finished_monotonic_ns"]) >= cast(int, receipt["absolute_deadline_ns"])
    ):
        raise RuntimeError("clean guardian receipt is incomplete")

    registration_item = _read_optional_json(run_root, "private/worker_registration.json")
    acknowledgement_item = _read_optional_json(run_root, "private/guardian_acknowledgement.json")
    registration_hash: str | None = None
    acknowledgement_hash: str | None = None
    if registration_item is not None:
        registration, registration_raw = registration_item
        _exact(
            registration,
            {
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
            "worker registration",
        )
        if (
            registration["schema_version"] != "nhc-phase8b-worker-registration-v1"
            or registration["transaction_id"] != FROZEN_IDENTITY["attempt_id"]
            or registration["absolute_deadline_ns"] != receipt["absolute_deadline_ns"]
            or registration["allowed_cpus"] != [0, 1, 2, 3]
            or type(registration["created_monotonic_ns"]) is not int
            or not cast(int, receipt["started_monotonic_ns"])
            <= registration["created_monotonic_ns"]
            < cast(int, receipt["absolute_deadline_ns"])
        ):
            raise RuntimeError("worker registration identity drifted")
        _require_sha(registration["release_token_sha256"], "registration release token")
        registration_hash = _sha(registration_raw)
        for role in ("guardian", "supervisor", "worker"):
            observed = _parse_identity(registration[role], "registered " + role)
            if role in identities and _stable_identity_projection(
                identities[role]
            ) != _stable_identity_projection(observed):
                raise RuntimeError("receipt and registration stable identities disagree")
            identities[role] = observed
        guardian = identities["guardian"]
        supervisor = identities["supervisor"]
        worker = identities["worker"]
        if (
            guardian["pgid"] != guardian["pid"]
            or guardian["sid"] != guardian["pid"]
            or supervisor["ppid"] != guardian["pid"]
            or supervisor["pgid"] != supervisor["pid"]
            or supervisor["sid"] != supervisor["pid"]
            or worker["ppid"] != supervisor["pid"]
            or worker["pgid"] != worker["pid"]
            or worker["sid"] != worker["pid"]
            or len({guardian["pid"], supervisor["pid"], worker["pid"]}) != 3
            or len({guardian["boot_id"], supervisor["boot_id"], worker["boot_id"]}) != 1
        ):
            raise RuntimeError("registered process hierarchy drifted")
    if acknowledgement_item is not None:
        acknowledgement, acknowledgement_raw = acknowledgement_item
        _exact(
            acknowledgement,
            {
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
            "guardian acknowledgement",
        )
        if (
            acknowledgement["schema_version"] != "nhc-phase8b-guardian-ack-v1"
            or acknowledgement["transaction_id"] != FROZEN_IDENTITY["attempt_id"]
            or acknowledgement["absolute_deadline_ns"] != receipt["absolute_deadline_ns"]
            or acknowledgement["registration_sha256"] != registration_hash
            or registration_item is None
            or acknowledgement["release_token_sha256"]
            != registration_item[0]["release_token_sha256"]
            or type(acknowledgement["created_monotonic_ns"]) is not int
            or not cast(int, registration_item[0]["created_monotonic_ns"])
            <= acknowledgement["created_monotonic_ns"]
            < cast(int, receipt["absolute_deadline_ns"])
        ):
            raise RuntimeError("guardian acknowledgement identity drifted")
        for role in ("guardian", "supervisor", "worker"):
            if _parse_identity(acknowledgement[role], "acknowledged " + role) != identities[role]:
                raise RuntimeError("acknowledgement process identity drifted")
        acknowledgement_hash = _sha(acknowledgement_raw)
    if receipt["acknowledgement_published"] is True:
        if (
            registration_hash is None
            or acknowledgement_hash is None
            or receipt["worker_registration_sha256"] != registration_hash
        ):
            raise RuntimeError("published registration chain is incomplete")
    elif acknowledgement_hash is not None or receipt["worker_registration_sha256"] is not None:
        raise RuntimeError("receipt registration state is contradictory")
    claim_item = _read_optional_json(run_root, "private/compute_claim.json")
    claim_hash: str | None = None
    claim_summary: dict[str, object] | None = None
    if claim_item is not None:
        if registration_item is None or acknowledgement_item is None:
            raise RuntimeError("compute claim lacks registration and acknowledgement")
        claim, claim_raw = claim_item
        _validate_compute_claim(
            claim,
            run_root=run_root,
            expected_inventory_sha256=expected_inventory_sha256,
            inventory=inventory,
            payload=payload,
            permit_sha256=permit_sha256,
            registration=registration_item[0],
            registration_sha256=cast(str, registration_hash),
            acknowledgement=acknowledgement_item[0],
            acknowledgement_sha256=cast(str, acknowledgement_hash),
            identities=identities,
        )
        claim_hash = _sha(claim_raw)
        if receipt["compute_claim_sha256"] != claim_hash:
            raise RuntimeError("receipt compute claim hash drifted")
        authority = _object(claim["authority"], "compute claim authority")
        scratch = Path(cast(str, claim["worker_scratch_path"]))
        claim_summary = {
            "schema_version": claim["schema_version"],
            "transaction_id": claim["transaction_id"],
            "absolute_deadline_ns": claim["absolute_deadline_ns"],
            "receipt_absolute_deadline_ns": receipt["absolute_deadline_ns"],
            "allowed_cpus": claim["allowed_cpus"],
            "release_token_sha256": claim["release_token_sha256"],
            "registration_sha256": claim["registration_sha256"],
            "acknowledgement_sha256": claim["acknowledgement_sha256"],
            "compute_claim_sha256": claim_hash,
            "receipt_worker_registration_sha256": receipt["worker_registration_sha256"],
            "receipt_compute_claim_sha256": receipt["compute_claim_sha256"],
            "created_monotonic_ns": claim["created_monotonic_ns"],
            "authority": {
                name: authority[name]
                for name in (
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
                )
            },
            "record_names": {
                "registration": "worker_registration.json",
                "acknowledgement": "guardian_acknowledgement.json",
                "compute_claim": "compute_claim.json",
                "receipt": "guardian_receipt.json",
            },
            "request_relative_path": "input/request.json",
            "output_relative_path": "runtime/output",
            "worker_scratch_name": scratch.name,
        }
    elif (
        receipt["compute_claim_sha256"] is not None
        or receipt["outcome"] in _CLAIM_REQUIRED_OUTCOMES
    ):
        raise RuntimeError("required permanent compute claim is missing")
    return (
        receipt,
        _sha(receipt_raw),
        registration_hash,
        acknowledgement_hash,
        claim_hash,
        claim_summary,
        identities,
    )


def _validate_compute_claim(
    claim: dict[str, object],
    *,
    run_root: Path,
    expected_inventory_sha256: str,
    inventory: dict[str, object],
    payload: dict[str, object],
    permit_sha256: str,
    registration: dict[str, object],
    registration_sha256: str,
    acknowledgement: dict[str, object],
    acknowledgement_sha256: str,
    identities: dict[str, dict[str, object]],
) -> None:
    _exact(
        claim,
        {
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
        "compute claim",
    )
    created = claim["created_monotonic_ns"]
    if (
        claim["schema_version"] != "nhc-phase8b-compute-claim-v1"
        or claim["transaction_id"] != FROZEN_IDENTITY["attempt_id"]
        or claim["absolute_deadline_ns"] != registration["absolute_deadline_ns"]
        or claim["allowed_cpus"] != [0, 1, 2, 3]
        or claim["release_token_sha256"] != registration["release_token_sha256"]
        or claim["registration_sha256"] != registration_sha256
        or claim["acknowledgement_sha256"] != acknowledgement_sha256
        or acknowledgement["registration_sha256"] != registration_sha256
        or type(created) is not int
        or not cast(int, acknowledgement["created_monotonic_ns"])
        <= created
        < cast(int, registration["absolute_deadline_ns"])
    ):
        raise RuntimeError("compute claim registration/ACK chain drifted")
    project_root = run_root.parents[2]
    payload_identity = _object(payload["identity"], "payload identity")
    expected_authority = {
        "transport_inventory_sha256": expected_inventory_sha256,
        "payload_manifest_sha256": inventory["payload_manifest_sha256"],
        "permit_sha256": permit_sha256,
        "request_sha256": payload_identity["request_sha256"],
        "runner_source_sha256": payload_identity["runner_source_sha256"],
        "protocol_sha256": FROZEN_PROTOCOL_SHA256,
        "resources_sha256": _sha(_canonical(FROZEN_RESOURCES)),
        "cation_xyz_sha256": FROZEN_INPUT_SHA256["cation_xyz"],
        "neutral_xyz_sha256": FROZEN_INPUT_SHA256["neutral_xyz"],
        "endpoint_atom_map_sha256": FROZEN_INPUT_SHA256["endpoint_atom_map"],
        "legacy_atom_map_sha256": FROZEN_INPUT_SHA256["legacy_atom_map"],
        "geometry_validation_sha256": (
            "35e99683a32e416752014c6e1ecb8121e2bc06d5407911435e5c1250fd639f90"
        ),
        "electron_count": 120,
        "request_id": FROZEN_IDENTITY["request_id"],
        "inchikey": FROZEN_IDENTITY["inchikey"],
        "attempt_id": FROZEN_IDENTITY["attempt_id"],
        "project_root": project_root.as_posix(),
        "run_root": run_root.as_posix(),
        "request_path": (run_root / "input/request.json").as_posix(),
        "output_root": (run_root / "runtime/output").as_posix(),
    }
    if claim["authority"] != expected_authority:
        raise RuntimeError("compute claim exact authority drifted")
    expected_paths = {
        "registration": (run_root / "private/worker_registration.json").as_posix(),
        "acknowledgement": (run_root / "private/guardian_acknowledgement.json").as_posix(),
        "compute_claim": (run_root / "private/compute_claim.json").as_posix(),
        "receipt": (run_root / "private/guardian_receipt.json").as_posix(),
    }
    if claim["paths"] != expected_paths:
        raise RuntimeError("compute claim coordination paths drifted")
    scratch_raw = claim["worker_scratch_path"]
    if not isinstance(scratch_raw, str):
        raise RuntimeError("compute claim worker scratch path is malformed")
    scratch = Path(scratch_raw)
    if (
        not scratch.is_absolute()
        or Path(os.path.abspath(scratch)) != scratch
        or scratch.parent != run_root / "runtime"
        or _SAFE_ATTEMPT_TEMP_RE.fullmatch(scratch.name) is None
    ):
        raise RuntimeError("compute claim worker scratch path drifted")
    for role in ("guardian", "supervisor", "worker"):
        observed = _parse_identity(claim[role], "compute claim " + role)
        if observed != identities.get(role) or observed != registration[role]:
            raise RuntimeError("compute claim process/starttime identity drifted")


def _proc_stat(pid: int) -> tuple[int, int] | None:
    try:
        raw = Path("/proc") / str(pid) / "stat"
        text = raw.read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    close = text.rfind(")")
    fields = text[close + 2 :].split()
    if close < 0 or len(fields) < 22:
        raise RuntimeError("malformed /proc stat")
    return int(fields[2]), int(fields[19])


def _process_absence(
    identities: dict[str, dict[str, object]], *, finished_monotonic_ns: int
) -> tuple[dict[str, str], dict[str, str], bool]:
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    identity_status: dict[str, str] = {}
    for role, identity in identities.items():
        observed = _proc_stat(cast(int, identity["pid"]))
        if observed is None:
            identity_status[role] = "absent"
        elif identity["boot_id"] != boot_id or observed[1] != identity["starttime_ticks"]:
            identity_status[role] = "pid_reused"
        else:
            raise RuntimeError("registered process is still alive: " + role)

    group_members: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.geteuid():
                continue
            observed = _proc_stat(int(entry.name))
            if observed is not None:
                group_members.setdefault(observed[0], []).append(observed[1])
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
            continue
    ticks = os.sysconf("SC_CLK_TCK")
    finished_ticks = math.ceil(finished_monotonic_ns * ticks / 1_000_000_000)
    group_status: dict[str, str] = {}
    seen_groups: dict[int, str] = {}
    for role, identity in identities.items():
        pgid = cast(int, identity["pgid"])
        previous = seen_groups.get(pgid)
        if previous is not None:
            group_status[role] = previous
            continue
        starts = group_members.get(pgid, [])
        if not starts:
            status = "absent"
        elif identity["boot_id"] != boot_id or all(start > finished_ticks for start in starts):
            status = "reused_after_receipt"
        else:
            raise RuntimeError("registered process group still has an original member")
        seen_groups[pgid] = status
        group_status[role] = status
    reused = (
        "pid_reused" in identity_status.values() or "reused_after_receipt" in group_status.values()
    )
    return identity_status, group_status, reused


def _validate_attempts(value: object, selected: object, label: str) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 2:
        raise RuntimeError(label + " attempt list drifted")
    normalized: list[tuple[object, object, object]] = []
    for raw in value:
        attempt = _object(raw, label + " attempt")
        expected = {"strategy", "converged"}
        if attempt.get("converged") is False:
            expected.add("failure_kind")
        if set(attempt) != expected:
            raise RuntimeError(label + " attempt fields drifted")
        normalized.append(
            (
                attempt.get("strategy"),
                attempt.get("converged"),
                attempt.get("failure_kind"),
            )
        )
    if len(normalized) == 1:
        if normalized[0][1] is not True:
            raise RuntimeError(label + " did not converge")
    elif normalized != [("standard", False, "scf_not_converged"), ("soscf", True, None)]:
        raise RuntimeError(label + " retry sequence drifted")
    if normalized[-1][0] != selected:
        raise RuntimeError(label + " selected strategy drifted")


def _xyz_elements(raw: bytes, label: str) -> list[str]:
    try:
        lines = raw.decode("utf-8").splitlines()
        count = int(lines[0].strip())
    except (UnicodeDecodeError, ValueError, IndexError) as exc:
        raise RuntimeError(label + " XYZ header is invalid") from exc
    if count <= 0 or len(lines) != count + 2:
        raise RuntimeError(label + " XYZ count drifted")
    elements: list[str] = []
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4:
            raise RuntimeError(label + " XYZ row drifted")
        try:
            coordinates = [float(item) for item in fields[1:]]
        except ValueError as exc:
            raise RuntimeError(label + " XYZ coordinate is invalid") from exc
        if not all(math.isfinite(item) and abs(item) <= 10_000.0 for item in coordinates):
            raise RuntimeError(label + " XYZ coordinate is unbounded")
        elements.append(fields[0])
    return elements


def _runtime_summary(value: object, label: str) -> dict[str, object]:
    runtime = _object(value, label + " runtime")
    expected = {
        "compute_threads": 4,
        "thread_environment": THREAD_ENVIRONMENT,
        "pyscf_threads": 4,
        "molecule_max_memory_mb": 12_000,
        "mean_field_max_memory_mb": 12_000,
        "electron_count": 120,
    }
    if runtime != expected:
        raise RuntimeError(label + " runtime resource evidence drifted")
    return runtime


def _endpoint_summary(
    run_root: Path,
    name: str,
    endpoint: object,
    *,
    record_raw: bytes,
) -> dict[str, object]:
    record = _object(endpoint, name + " endpoint")
    expected_fields = {
        "charge",
        "multiplicity",
        "electron_count",
        "input_xyz_path",
        "input_xyz_sha256",
        "retry",
        "optimization",
        "final_scf",
        "optimized_xyz_sha256",
    }
    if set(record) != expected_fields:
        raise RuntimeError(name + " endpoint fields drifted")
    expected_charge = 1 if name == "cation" else 0
    expected_hash = FROZEN_INPUT_SHA256[name + "_xyz"]
    if (
        record["charge"] != expected_charge
        or record["multiplicity"] != 1
        or record["electron_count"] != 120
        or record["input_xyz_path"] != "xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_" + name + ".xyz"
        or record["input_xyz_sha256"] != expected_hash
    ):
        raise RuntimeError(name + " endpoint identity drifted")
    retry = _object(record["retry"], name + " retry")
    if (
        set(retry) != {"soscf_budget", "soscf_consumed", "soscf_stage"}
        or retry["soscf_budget"] != 1
        or type(retry["soscf_consumed"]) is not bool
        or retry["soscf_stage"] not in {None, "optimization", "final_scf"}
        or (retry["soscf_consumed"] is True) != (retry["soscf_stage"] is not None)
    ):
        raise RuntimeError(name + " retry evidence drifted")
    optimization = _object(record["optimization"], name + " optimization")
    final_scf = _object(record["final_scf"], name + " final SCF")
    if set(optimization) != {
        "optimizer",
        "geometry_converged",
        "scf_converged",
        "selected_strategy",
        "last_energy_hartree",
        "attempts",
        "runtime",
        "dispersion",
    }:
        raise RuntimeError(name + " optimization schema drifted")
    if set(final_scf) != {
        "converged",
        "selected_strategy",
        "energy_hartree",
        "attempts",
        "runtime",
        "dispersion",
    }:
        raise RuntimeError(name + " final SCF schema drifted")
    if (
        optimization["optimizer"] != "geomeTRIC"
        or optimization["geometry_converged"] is not True
        or optimization["scf_converged"] is not True
        or final_scf["converged"] is not True
        or optimization["selected_strategy"] not in {"standard", "soscf"}
        or final_scf["selected_strategy"] not in {"standard", "soscf"}
    ):
        raise RuntimeError(name + " convergence evidence drifted")
    if type(optimization["last_energy_hartree"]) not in {int, float} or type(
        final_scf["energy_hartree"]
    ) not in {int, float}:
        raise RuntimeError(name + " energy type drifted")
    optimization_energy = float(cast(float, optimization["last_energy_hartree"]))
    final_energy = float(cast(float, final_scf["energy_hartree"]))
    if not math.isfinite(optimization_energy) or not math.isfinite(final_energy):
        raise RuntimeError(name + " energy is non-finite")
    _validate_attempts(
        optimization["attempts"],
        optimization["selected_strategy"],
        name + " optimization",
    )
    _validate_attempts(final_scf["attempts"], final_scf["selected_strategy"], name + " final SCF")
    expected_stage = (
        "optimization"
        if optimization["selected_strategy"] == "soscf"
        else "final_scf"
        if final_scf["selected_strategy"] == "soscf"
        else None
    )
    if retry["soscf_stage"] != expected_stage:
        raise RuntimeError(name + " SOSCF budget disagrees with attempts")
    runtime = _runtime_summary(optimization["runtime"], name + " optimization")
    if _runtime_summary(final_scf["runtime"], name + " final SCF") != runtime:
        raise RuntimeError(name + " runtime evidence disagrees between stages")

    attempt_root = "runtime/output/attempts/attempt-phase8b-qxh-v001/"
    optimized_name = attempt_root + name + ".optimized.xyz"
    optimized_raw, _ = _read_file(run_root, optimized_name, expected_mode=_DYNAMIC_FILE_MODE)
    initial_name = "input/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_" + name + ".xyz"
    initial_raw, _ = _read_file(run_root, initial_name, expected_mode=_STATIC_FILE_MODE)
    optimized_elements = _xyz_elements(optimized_raw, name + " optimized")
    initial_elements = _xyz_elements(initial_raw, name + " initial")
    if optimized_elements != initial_elements:
        raise RuntimeError(name + " optimized atom order drifted")
    expected_counts = (
        {"C": 7, "N": 6, "O": 4, "H": 5} if name == "cation" else {"C": 7, "N": 6, "O": 4, "H": 4}
    )
    observed_counts = {
        element: initial_elements.count(element) for element in set(initial_elements)
    }
    if observed_counts != expected_counts or initial_elements[3:6] != ["N", "C", "N"]:
        raise RuntimeError(name + " frozen composition or N1/C2/N3 order drifted")
    optimized_hash = _sha(optimized_raw)
    if record["optimized_xyz_sha256"] != optimized_hash:
        raise RuntimeError(name + " optimized XYZ hash drifted")

    opt_d3 = _object(optimization["dispersion"], name + " optimization D3")
    if set(opt_d3) != {
        "tag",
        "energy_hook_calls",
        "gradient_hook_calls",
        "gradient_shape",
        "energy_values_finite",
        "gradient_values_finite",
    }:
        raise RuntimeError(name + " optimization D3 schema drifted")
    atom_count = len(optimized_elements)
    if (
        opt_d3["tag"] != "d3bj"
        or type(opt_d3["energy_hook_calls"]) is not int
        or opt_d3["energy_hook_calls"] <= 0
        or type(opt_d3["gradient_hook_calls"]) is not int
        or opt_d3["gradient_hook_calls"] <= 0
        or opt_d3["gradient_shape"] != [atom_count, 3]
        or opt_d3["energy_values_finite"] is not True
        or opt_d3["gradient_values_finite"] is not True
    ):
        raise RuntimeError(name + " optimization D3 evidence drifted")
    final_d3 = _object(final_scf["dispersion"], name + " final D3")
    if set(final_d3) != {
        "tag",
        "energy_hook_calls",
        "breakdown",
        "audit_calls",
        "audit_energy_hartree",
        "audit_gradient_shape",
        "audit_gradient_finite",
        "audit_absolute_error_hartree",
        "adapter_version",
    }:
        raise RuntimeError(name + " final D3 schema drifted")
    breakdown = _object(final_d3["breakdown"], name + " energy breakdown")
    component_names = (
        "nuclear_hartree",
        "one_electron_hartree",
        "coulomb_hartree",
        "exchange_correlation_hartree",
        "dispersion_hartree",
    )
    expected_breakdown = {
        *component_names,
        "reconstructed_hartree",
        "total_hartree",
        "absolute_error_hartree",
    }
    if set(breakdown) != expected_breakdown:
        raise RuntimeError(name + " energy breakdown schema drifted")
    if (
        any(type(breakdown[field]) not in {int, float} for field in expected_breakdown)
        or type(final_d3["audit_energy_hartree"]) not in {int, float}
        or type(final_d3["audit_absolute_error_hartree"])
        not in {
            int,
            float,
        }
    ):
        raise RuntimeError(name + " D3 numeric types drifted")
    numeric = {field: float(cast(float, breakdown[field])) for field in expected_breakdown}
    audit_energy = float(cast(float, final_d3["audit_energy_hartree"]))
    audit_error = float(cast(float, final_d3["audit_absolute_error_hartree"]))
    if not all(math.isfinite(value) for value in (*numeric.values(), audit_energy, audit_error)):
        raise RuntimeError(name + " D3 evidence is non-finite")
    reconstructed = sum(numeric[field] for field in component_names)
    if (
        final_d3["tag"] != "d3bj"
        or type(final_d3["energy_hook_calls"]) is not int
        or final_d3["energy_hook_calls"] <= 0
        or final_d3["audit_calls"] != 1
        or final_d3["audit_gradient_shape"] != [atom_count, 3]
        or final_d3["audit_gradient_finite"] is not True
        or final_d3["adapter_version"] != "1.5.0"
        or numeric["dispersion_hartree"] == 0.0
        or audit_energy == 0.0
        or abs(numeric["reconstructed_hartree"] - reconstructed) > 1e-15
        or abs(numeric["total_hartree"] - final_energy) > 1e-15
        or abs(numeric["absolute_error_hartree"] - abs(reconstructed - final_energy)) > 1e-15
        or abs(audit_error - abs(audit_energy - numeric["dispersion_hartree"])) > 1e-15
        or numeric["absolute_error_hartree"] > 1e-12
        or audit_error > 1e-12
    ):
        raise RuntimeError(name + " final D3 arithmetic drifted")
    del record_raw  # its canonical bytes were independently compared by the caller
    return {
        "charge": expected_charge,
        "multiplicity": 1,
        "electron_count": 120,
        "atom_count": atom_count,
        "optimized_xyz_sha256": optimized_hash,
        "geometry_converged": True,
        "optimization_scf_converged": True,
        "final_scf_converged": True,
        "optimization_strategy": optimization["selected_strategy"],
        "final_scf_strategy": final_scf["selected_strategy"],
        "soscf_budget": 1,
        "soscf_consumed": retry["soscf_consumed"],
        "soscf_stage": retry["soscf_stage"],
        "optimization_energy_hartree": optimization_energy,
        "final_energy_hartree": final_energy,
        "runtime": runtime,
        "d3": {
            "tag": "d3bj",
            "optimization_energy_hook_calls": opt_d3["energy_hook_calls"],
            "optimization_gradient_hook_calls": opt_d3["gradient_hook_calls"],
            "optimization_gradient_shape": [atom_count, 3],
            "final_energy_hook_calls": final_d3["energy_hook_calls"],
            "dispersion_hartree": numeric["dispersion_hartree"],
            "breakdown_absolute_error_hartree": numeric["absolute_error_hartree"],
            "audit_calls": 1,
            "audit_energy_hartree": audit_energy,
            "audit_gradient_shape": [atom_count, 3],
            "audit_absolute_error_hartree": audit_error,
            "adapter_version": "1.5.0",
        },
    }


def _supervision_summary(value: object) -> dict[str, object]:
    supervision = _object(value, "supervision")
    expected_fields = {
        "outcome",
        "public_returncode",
        "child_returncode",
        "duration_seconds",
        "pid",
        "pgid",
        "stdout_total_bytes",
        "stdout_captured_bytes",
        "stdout_captured_sha256",
        "stdout_truncated",
        "stderr_total_bytes",
        "stderr_captured_bytes",
        "stderr_captured_sha256",
        "stderr_truncated",
        "timed_out",
        "term_sent",
        "kill_sent",
        "orphan_descendants_detected",
        "process_started",
        "group_cleanup_confirmed",
        "direct_child_reaped",
        "error_message",
    }
    if set(supervision) != expected_fields:
        raise RuntimeError("supervision fields drifted")
    duration = float(cast(float, supervision["duration_seconds"]))
    if not math.isfinite(duration) or not 0.0 <= duration <= 7_200.0:
        raise RuntimeError("successful supervision duration drifted")
    expected = {
        "outcome": "clean",
        "public_returncode": 0,
        "child_returncode": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timed_out": False,
        "term_sent": False,
        "kill_sent": False,
        "orphan_descendants_detected": False,
        "process_started": True,
        "group_cleanup_confirmed": True,
        "direct_child_reaped": True,
        "error_message": None,
    }
    if any(supervision[name] != expected_value for name, expected_value in expected.items()):
        raise RuntimeError("successful supervision evidence drifted")
    for stream in ("stdout", "stderr"):
        total = supervision[stream + "_total_bytes"]
        captured = supervision[stream + "_captured_bytes"]
        if (
            type(total) is not int
            or type(captured) is not int
            or not 0 <= captured <= total <= 65_536
        ):
            raise RuntimeError(stream + " capture evidence drifted")
        _require_sha(supervision[stream + "_captured_sha256"], stream + " capture hash")
    if (
        type(supervision["pid"]) is not int
        or supervision["pid"] <= 1
        or supervision["pgid"] != supervision["pid"]
    ):
        raise RuntimeError("supervision process identity drifted")
    return {
        "outcome": "clean",
        "public_returncode": 0,
        "child_returncode": 0,
        "duration_seconds": duration,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timed_out": False,
        "term_sent": False,
        "kill_sent": False,
        "orphan_descendants_detected": False,
        "process_started": True,
        "group_cleanup_confirmed": True,
        "direct_child_reaped": True,
    }


def _validate_success(
    run_root: Path,
    *,
    inventory_sha: str,
    permit_sha: str,
    payload: dict[str, object],
    request: dict[str, object],
    receipt: dict[str, object],
    receipt_sha: str,
    registration_sha: str | None,
    compute_claim_sha: str | None,
) -> tuple[dict[str, object], dict[str, str | None]]:
    output = "runtime/output/"
    names = {
        "_SUPERVISOR_SUCCESS",
        "supervisor_success.json",
        "_SUCCESS",
        "success.json",
        "attempts",
    }
    actual_top = {path.name for path in (run_root / "runtime/output").iterdir()}
    if actual_top != names:
        raise RuntimeError("successful output top-level set drifted")
    provisional_raw, _ = _read_file(
        run_root, output + "supervisor_success.json", expected_mode=_DYNAMIC_FILE_MODE
    )
    provisional = _strict_object(provisional_raw, "supervisor success")
    provisional_marker_raw, _ = _read_file(
        run_root, output + "_SUPERVISOR_SUCCESS", expected_mode=_DYNAMIC_FILE_MODE
    )
    provisional_marker = _strict_object(provisional_marker_raw, "supervisor marker")
    if provisional_marker != {
        "schema_version": "nhc-two-endpoint-supervisor-success-v1",
        "supervisor_success_sha256": _sha(provisional_raw),
    }:
        raise RuntimeError("supervisor marker binding drifted")
    success_raw, _ = _read_file(run_root, output + "success.json", expected_mode=_DYNAMIC_FILE_MODE)
    success = _strict_object(success_raw, "final success")
    marker_raw, _ = _read_file(run_root, output + "_SUCCESS", expected_mode=_DYNAMIC_FILE_MODE)
    marker = _strict_object(marker_raw, "final marker")
    if marker != {
        "schema_version": "nhc-phase8b-final-success-v1",
        "success_sha256": _sha(success_raw),
    }:
        raise RuntimeError("final marker binding drifted")
    payload_identity = _object(payload["identity"], "payload identity")
    expected_success_fields = {
        "schema_version",
        "status",
        "request_id",
        "inchikey",
        "attempt_id",
        "request_sha256",
        "runner_source_sha256",
        "payload_manifest_sha256",
        "transport_inventory_sha256",
        "permit_sha256",
        "resources_sha256",
        "input_sha256",
        "provisional",
        "guardian",
        "result",
    }
    if set(success) != expected_success_fields:
        raise RuntimeError("final success fields drifted")
    provisional_binding = _object(success["provisional"], "final provisional binding")
    guardian_binding = _object(success["guardian"], "final guardian binding")
    if compute_claim_sha is None:
        raise RuntimeError("successful run lacks permanent compute claim")
    if (
        success["schema_version"] != "nhc-phase8b-final-success-v1"
        or success["status"] != "success"
        or success["request_id"] != FROZEN_IDENTITY["request_id"]
        or success["inchikey"] != FROZEN_IDENTITY["inchikey"]
        or success["attempt_id"] != FROZEN_IDENTITY["attempt_id"]
        or success["request_sha256"] != payload_identity["request_sha256"]
        or success["runner_source_sha256"] != payload_identity["runner_source_sha256"]
        or success["payload_manifest_sha256"]
        != _sha(_read_file(run_root, "payload_manifest.json", expected_mode=_STATIC_FILE_MODE)[0])
        or success["transport_inventory_sha256"] != inventory_sha
        or success["permit_sha256"] != permit_sha
        or success["resources_sha256"] != _sha(_canonical(FROZEN_RESOURCES))
        or success["input_sha256"]
        != {
            "cation": FROZEN_INPUT_SHA256["cation_xyz"],
            "neutral": FROZEN_INPUT_SHA256["neutral_xyz"],
            "endpoint_atom_map": FROZEN_INPUT_SHA256["endpoint_atom_map"],
            "legacy_atom_map": FROZEN_INPUT_SHA256["legacy_atom_map"],
            "geometry_validation": (
                "35e99683a32e416752014c6e1ecb8121e2bc06d5407911435e5c1250fd639f90"
            ),
        }
        or provisional_binding.get("success_sha256") != _sha(provisional_raw)
        or provisional_binding.get("marker_sha256") != _sha(provisional_marker_raw)
        or set(provisional_binding)
        != {"success_sha256", "marker_sha256", "result_relative_path", "result_sha256"}
        or guardian_binding
        != {
            "receipt_sha256": receipt_sha,
            "worker_registration_sha256": registration_sha,
            "compute_claim_sha256": compute_claim_sha,
            "outcome": "clean",
            "supervisor_returncode": 0,
            "worker_group_cleanup_confirmed": True,
        }
    ):
        raise RuntimeError("final success hash closure drifted")

    expected_provisional_fields = {
        "schema_version",
        "status",
        "attempt_id",
        "request_id",
        "inchikey",
        "request_sha256",
        "protocol_sha256",
        "runner_source_sha256",
        "input_sha256",
        "output_sha256",
        "result_relative_path",
        "supervision",
    }
    if set(provisional) != expected_provisional_fields:
        raise RuntimeError("provisional success fields drifted")
    attempt_prefix = "attempts/attempt-phase8b-qxh-v001/"
    expected_attempt_files = {
        attempt_prefix + name
        for name in {
            "cation.json",
            "cation.optimized.xyz",
            "neutral.json",
            "neutral.optimized.xyz",
            "result.json",
            "_ATTEMPT_SUCCESS",
        }
    }
    output_hashes = _object(provisional["output_sha256"], "provisional output hashes")
    if (
        provisional["schema_version"] != "nhc-two-endpoint-supervisor-success-v1"
        or provisional["status"] != "success"
        or provisional["attempt_id"] != FROZEN_IDENTITY["attempt_id"]
        or provisional["request_id"] != FROZEN_IDENTITY["request_id"]
        or provisional["inchikey"] != FROZEN_IDENTITY["inchikey"]
        or provisional["request_sha256"] != payload_identity["request_sha256"]
        or provisional["protocol_sha256"] != FROZEN_PROTOCOL_SHA256
        or provisional["runner_source_sha256"] != payload_identity["runner_source_sha256"]
        or provisional["input_sha256"]
        != {
            "cation": FROZEN_INPUT_SHA256["cation_xyz"],
            "neutral": FROZEN_INPUT_SHA256["neutral_xyz"],
        }
        or provisional["result_relative_path"] != attempt_prefix + "result.json"
        or set(output_hashes) != expected_attempt_files
    ):
        raise RuntimeError("provisional success identity drifted")
    result_relative = attempt_prefix + "result.json"
    if (
        provisional_binding["result_relative_path"] != result_relative
        or provisional_binding["result_sha256"] != output_hashes[result_relative]
    ):
        raise RuntimeError("final provisional result binding drifted")
    for name, expected_hash in output_hashes.items():
        raw, mode = _read_file(run_root, output + name, expected_mode=_DYNAMIC_FILE_MODE)
        if mode != _DYNAMIC_FILE_MODE or _sha(raw) != expected_hash:
            raise RuntimeError("attempt output hash drifted: " + name)
    supervision = _supervision_summary(provisional["supervision"])
    result_name = output + attempt_prefix + "result.json"
    result_raw, _ = _read_file(run_root, result_name, expected_mode=_DYNAMIC_FILE_MODE)
    result = _strict_object(result_raw, "result.json")
    expected_result_fields = {
        "schema_version",
        "status",
        "attempt_id",
        "request_id",
        "inchikey",
        "protocol_sha256",
        "protocol",
        "endpoints",
        "electronic_difference_kcal",
        "dft_deprot_electronic_kcal",
        "lower_is_better",
        "hessian_computed",
        "frequency_status",
        "n_imaginary",
        "extra_single_points_computed",
        "radical_computed",
        "molden_written",
        "label_quality",
    }
    if set(result) != expected_result_fields:
        raise RuntimeError("result fields drifted")
    endpoints = _object(result["endpoints"], "result endpoints")
    summaries: dict[str, object] = {}
    for name in ("cation", "neutral"):
        record_name = output + attempt_prefix + name + ".json"
        record_raw, _ = _read_file(run_root, record_name, expected_mode=_DYNAMIC_FILE_MODE)
        record = _strict_object(record_raw, name + ".json")
        if endpoints.get(name) != record:
            raise RuntimeError(name + " endpoint record differs from result")
        summaries[name] = _endpoint_summary(run_root, name, record, record_raw=record_raw)
    cation_energy = cast(dict[str, object], summaries["cation"])["final_energy_hartree"]
    neutral_energy = cast(dict[str, object], summaries["neutral"])["final_energy_hartree"]
    difference = float(cast(float, result["electronic_difference_kcal"]))
    label = float(cast(float, result["dft_deprot_electronic_kcal"]))
    expected_difference = (cast(float, neutral_energy) - cast(float, cation_energy)) * 627.509474
    if (
        result["schema_version"] != "nhc-two-endpoint-result-v2"
        or result["status"] != "success"
        or result["attempt_id"] != FROZEN_IDENTITY["attempt_id"]
        or result["request_id"] != FROZEN_IDENTITY["request_id"]
        or result["inchikey"] != FROZEN_IDENTITY["inchikey"]
        or result["protocol_sha256"] != FROZEN_PROTOCOL_SHA256
        or result["protocol"] != request["protocol"]
        or result["lower_is_better"] is not True
        or not math.isclose(difference, expected_difference, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(label, expected_difference - 6.28, rel_tol=0.0, abs_tol=1e-12)
        or result["hessian_computed"] is not False
        or result["frequency_status"] != "not_computed"
        or result["n_imaginary"] is not None
        or result["extra_single_points_computed"] is not False
        or result["radical_computed"] is not False
        or result["molden_written"] is not False
        or result["label_quality"] != "electronic_energy_only"
    ):
        raise RuntimeError("result scientific acceptance drifted")
    result_binding = _object(success["result"], "final result binding")
    if result_binding != {
        "cation_energy_hartree": cation_energy,
        "neutral_energy_hartree": neutral_energy,
        "electronic_difference_kcal": difference,
        "dft_deprot_electronic_kcal": label,
    }:
        raise RuntimeError("final and attempt result energies disagree")
    attempt_marker_raw, _ = _read_file(
        run_root, output + attempt_prefix + "_ATTEMPT_SUCCESS", expected_mode=_DYNAMIC_FILE_MODE
    )
    attempt_marker = _strict_object(attempt_marker_raw, "attempt marker")
    if (
        set(attempt_marker)
        != {
            "schema_version",
            "status",
            "attempt_id",
            "request_id",
            "inchikey",
            "request_sha256",
            "protocol_sha256",
            "runner_source_sha256",
            "input_sha256",
            "result_sha256",
        }
        or attempt_marker.get("schema_version") != "nhc-two-endpoint-attempt-v2"
        or attempt_marker.get("status") != "success"
        or attempt_marker.get("attempt_id") != FROZEN_IDENTITY["attempt_id"]
        or attempt_marker.get("request_id") != FROZEN_IDENTITY["request_id"]
        or attempt_marker.get("inchikey") != FROZEN_IDENTITY["inchikey"]
        or attempt_marker.get("request_sha256") != payload_identity["request_sha256"]
        or attempt_marker.get("protocol_sha256") != FROZEN_PROTOCOL_SHA256
        or attempt_marker.get("runner_source_sha256") != payload_identity["runner_source_sha256"]
        or attempt_marker.get("input_sha256")
        != {
            "cation": FROZEN_INPUT_SHA256["cation_xyz"],
            "neutral": FROZEN_INPUT_SHA256["neutral_xyz"],
        }
        or attempt_marker.get("result_sha256") != _sha(result_raw)
    ):
        raise RuntimeError("attempt marker result binding drifted")
    result_summary = {
        "cation": summaries["cation"],
        "neutral": summaries["neutral"],
        "electronic_difference_kcal": difference,
        "dft_deprot_electronic_kcal": label,
        "lower_is_better": True,
        "hessian_computed": False,
        "frequency_status": "not_computed",
        "extra_single_points_computed": False,
        "radical_computed": False,
        "molden_written": False,
        "label_quality": "electronic_energy_only",
        "supervision": supervision,
    }
    hashes: dict[str, str | None] = {
        "final_success_sha256": _sha(success_raw),
        "final_marker_sha256": _sha(marker_raw),
        "provisional_success_sha256": _sha(provisional_raw),
        "provisional_marker_sha256": _sha(provisional_marker_raw),
        "result_sha256": _sha(result_raw),
        "failure_sha256": None,
    }
    if receipt["outcome"] != "clean":
        raise RuntimeError("success disagrees with guardian receipt")
    return result_summary, hashes


def _validate_failure(
    run_root: Path, files: set[str], receipt: dict[str, object]
) -> tuple[dict[str, object], dict[str, str | None]]:
    if "runtime/output/_SUCCESS" in files or "runtime/output/success.json" in files:
        raise RuntimeError("failed run published final acceptance")
    if receipt["outcome"] == "clean":
        raise RuntimeError("failed run has a clean guardian receipt")
    failure_name = "runtime/output/attempts/attempt-phase8b-qxh-v001/failure.json"
    failure_hash: str | None = None
    stage: str | None = None
    error_type: str | None = None
    if failure_name in files:
        raw, _ = _read_file(run_root, failure_name, expected_mode=_DYNAMIC_FILE_MODE)
        failure = _strict_object(raw, "failure.json")
        if (
            failure.get("schema_version") != "nhc-two-endpoint-failure-v1"
            or failure.get("status") != "failed"
            or failure.get("attempt_id") != FROZEN_IDENTITY["attempt_id"]
            or failure.get("request_id") != FROZEN_IDENTITY["request_id"]
            or failure.get("inchikey") != FROZEN_IDENTITY["inchikey"]
        ):
            raise RuntimeError("failure envelope identity drifted")
        stage = cast(str, failure.get("stage"))
        error_type = cast(str, failure.get("error_type"))
        if (
            not isinstance(stage, str)
            or not stage
            or not isinstance(error_type, str)
            or not error_type
        ):
            raise RuntimeError("failure classification is invalid")
        failure_hash = _sha(raw)
    hashes: dict[str, str | None] = {
        "final_success_sha256": None,
        "final_marker_sha256": None,
        "provisional_success_sha256": None,
        "provisional_marker_sha256": None,
        "result_sha256": None,
        "failure_sha256": failure_hash,
    }
    for name, key in (
        ("runtime/output/supervisor_success.json", "provisional_success_sha256"),
        ("runtime/output/_SUPERVISOR_SUCCESS", "provisional_marker_sha256"),
        (
            "runtime/output/attempts/attempt-phase8b-qxh-v001/result.json",
            "result_sha256",
        ),
    ):
        if name in files:
            raw, _ = _read_file(run_root, name, expected_mode=_DYNAMIC_FILE_MODE)
            hashes[key] = _sha(raw)
    failure_summary = {
        "receipt_outcome": receipt["outcome"],
        "error_code": receipt["error_code"],
        "attempt_failure_stage": stage,
        "attempt_failure_error_type": error_type,
    }
    return failure_summary, hashes


def _validate_dynamic_tree(
    run_root: Path,
    files: set[str],
    directories: set[str],
    static_files: set[str],
    *,
    success: bool,
) -> None:
    dynamic_files = files - static_files
    allowed_exact = {
        "private/permit.consumed.json",
        "private/guardian.log",
        "private/supervisor.stdout.log",
        "private/supervisor.stderr.log",
        "private/worker_registration.json",
        "private/guardian_acknowledgement.json",
        "private/compute_claim.json",
        "private/guardian_receipt.json",
        "runtime/output/_SUCCESS",
        "runtime/output/success.json",
        "runtime/output/_SUPERVISOR_SUCCESS",
        "runtime/output/supervisor_success.json",
    }
    attempt_prefix = "runtime/output/attempts/attempt-phase8b-qxh-v001/"
    attempt_names = {
        attempt_prefix + name
        for name in {
            "cation.json",
            "cation.optimized.xyz",
            "neutral.json",
            "neutral.optimized.xyz",
            "result.json",
            "_ATTEMPT_SUCCESS",
            "failure.json",
        }
    }

    def allowed_scratch(name: str) -> bool:
        parts = PurePosixPath(name).parts
        if len(parts) < 2 or parts[0] != "runtime" or not _SAFE_ATTEMPT_TEMP_RE.fullmatch(parts[1]):
            return False
        if any("attempt-" in part and "attempt-phase8b-qxh-v001" not in part for part in parts):
            return False
        allowed_leaf = {
            "attempts",
            "attempt-phase8b-qxh-v001",
            "cation.json",
            "cation.optimized.xyz",
            "neutral.json",
            "neutral.optimized.xyz",
            "result.json",
            "_ATTEMPT_SUCCESS",
            "failure.json",
        }
        return all(
            part in allowed_leaf or _SAFE_ATTEMPT_TEMP_RE.fullmatch(part) is not None
            for part in parts[2:]
        )

    unexpected = {
        name
        for name in dynamic_files
        if name not in allowed_exact and name not in attempt_names and not allowed_scratch(name)
    }
    if unexpected:
        raise RuntimeError("dynamic tree contains an unexpected file")
    if success and any(allowed_scratch(name) for name in dynamic_files):
        raise RuntimeError("successful run retained worker scratch")
    for name in dynamic_files:
        mode = stat.S_IMODE(run_root.joinpath(*PurePosixPath(name).parts).stat().st_mode)
        if name == "private/permit.consumed.json":
            if mode != _CONSUMED_MODE:
                raise RuntimeError("consumed permit mode drifted")
        elif mode != _DYNAMIC_FILE_MODE:
            raise RuntimeError("dynamic file mode drifted: " + name)
    for name in directories:
        if "attempt-" in name and "attempt-phase8b-qxh-v001" not in name:
            raise RuntimeError("second attempt directory detected")


def _forbidden_summary(files: set[str], static_files: set[str]) -> dict[str, bool]:
    patterns: dict[str, tuple[str, ...]] = {
        "hessian": ("hess",),
        "frequency": ("freq",),
        "zpe": ("zpe",),
        "thermal": ("thermal", "thermochem"),
        "radical": ("radical",),
        "molden": ("molden",),
        "no_d3": ("no-d3", "no_d3", "nod3"),
        "extra_single_point": ("extra-single", "extra_single", "single-point", "single_point"),
        "scheduler": ("slurm", "sbatch", "qsub", "pbs", "scheduler", "submit"),
        "second_attempt": ("attempt-phase8b-qxh-v002", "attempt-phase8b-qxh-v003"),
    }
    dynamic = [name.lower() for name in files - static_files]
    found = {
        label: any(token in name for name in dynamic for token in tokens)
        for label, tokens in patterns.items()
    }
    if any(found.values()):
        raise RuntimeError("forbidden dynamic artifact detected")
    return found


def inspect_server(
    phase7_relative: str,
    phase8b_relative: str,
    expected_inventory_sha256: str,
) -> dict[str, object]:
    """Inspect one terminal tree without writes, signals, imports, or execution."""

    expected_inventory_hash = _require_sha(expected_inventory_sha256, "expected inventory hash")
    project_root = Path.cwd()
    if (
        project_root.is_symlink()
        or not project_root.is_dir()
        or project_root.resolve(strict=True) != project_root
    ):
        raise RuntimeError("project root is unsafe")
    phase7 = project_root.joinpath(*_safe_run_relative(phase7_relative, "phase7").parts)
    phase8b_safe = _safe_run_relative(phase8b_relative, "phase8b")
    if phase8b_safe.as_posix() != EXPECTED_PHASE8B_RELATIVE:
        raise RuntimeError("Phase 8B run identity drifted")
    run_root = project_root.joinpath(*phase8b_safe.parts)

    phase7_before = _phase7_tree(phase7)
    sources_before = _project_sources(project_root)
    files, directories = _tree(run_root)
    inventory_raw, inventory_mode = _read_file(
        run_root, "transport_inventory.json", expected_mode=_STATIC_FILE_MODE
    )
    if inventory_mode != _STATIC_FILE_MODE or _sha(inventory_raw) != expected_inventory_hash:
        raise RuntimeError("transport inventory hash or mode drifted")
    inventory = _strict_object(inventory_raw, "transport inventory")
    _exact(
        inventory,
        {
            "schema_version",
            "bundle_version",
            "payload_manifest_sha256",
            "permit_sha256",
            "files",
            "transport_tree_sha256",
            "directories",
            "directory_tree_sha256",
            "excluded_from_inventory",
        },
        "transport inventory",
    )
    transport_files = _file_entry_map(inventory["files"])
    transport_directories = _directory_entry_map(inventory["directories"])
    ready_name = "private/permit.ready.json"
    if (
        inventory["schema_version"] != "phase8b.transport_inventory.v2"
        or inventory["bundle_version"] != "phase8b-dft-smoke-v001"
        or inventory["excluded_from_inventory"] != ["transport_inventory.json"]
        or ready_name not in transport_files
        or transport_files[ready_name]["mode"] != "0600"
        or inventory["transport_tree_sha256"] != _file_tree_sha(transport_files)
        or inventory["directory_tree_sha256"] != _directory_tree_sha(transport_directories)
    ):
        raise RuntimeError("transport inventory contract drifted")
    for name, entry in transport_files.items():
        if name == ready_name:
            continue
        raw, mode = _read_file(run_root, name, expected_mode=int(cast(str, entry["mode"]), 8))
        if (
            _sha(raw) != entry["sha256"]
            or len(raw) != entry["bytes"]
            or mode != int(cast(str, entry["mode"]), 8)
        ):
            raise RuntimeError("static payload drifted: " + name)
    for name, entry in transport_directories.items():
        path = run_root if name == "." else run_root.joinpath(*PurePosixPath(name).parts)
        if (
            path.is_symlink()
            or not path.is_dir()
            or stat.S_IMODE(path.stat().st_mode) != int(cast(str, entry["mode"]), 8)
        ):
            raise RuntimeError("registered directory drifted: " + name)
    payload, request = _validate_payload_and_request(run_root, inventory, transport_files)
    permit_sha, _permit_raw = _validate_permit(project_root, run_root, inventory, payload)
    if permit_sha != transport_files[ready_name]["sha256"]:
        raise RuntimeError("consumed permit differs from deployed ready permit")
    (
        receipt,
        receipt_sha,
        registration_sha,
        acknowledgement_sha,
        compute_claim_sha,
        compute_claim_summary,
        identities,
    ) = _validate_receipt_chain(
        run_root,
        permit_sha256=permit_sha,
        expected_inventory_sha256=expected_inventory_hash,
        inventory=inventory,
        payload=payload,
    )
    identity_status, group_status, reuse_observed = _process_absence(
        identities,
        finished_monotonic_ns=cast(int, receipt["finished_monotonic_ns"]),
    )
    success = receipt["outcome"] == "clean"
    static_files = (set(transport_files) - {ready_name}) | {"transport_inventory.json"}
    _validate_dynamic_tree(
        run_root,
        files,
        directories,
        static_files,
        success=success,
    )
    forbidden = _forbidden_summary(files, static_files)
    if success:
        result, runtime_hashes = _validate_success(
            run_root,
            inventory_sha=expected_inventory_hash,
            permit_sha=permit_sha,
            payload=payload,
            request=request,
            receipt=receipt,
            receipt_sha=receipt_sha,
            registration_sha=registration_sha,
            compute_claim_sha=compute_claim_sha,
        )
        failure: dict[str, object] | None = None
        terminal_outcome = "success"
    else:
        failure, runtime_hashes = _validate_failure(run_root, files, receipt)
        result = None
        terminal_outcome = "failure"
    phase7_after = _phase7_tree(phase7)
    sources_after = _project_sources(project_root)
    checks = {
        "permit_ready_absent": not os.path.lexists(run_root / ready_name),
        "permit_consumed_matches": permit_sha == inventory["permit_sha256"],
        "transport_inventory_matches": _sha(inventory_raw) == expected_inventory_hash,
        "static_payload_matches": True,
        "registered_directories_match": True,
        "phase7_tree_matches": phase7_before
        == (EXPECTED_PHASE7_FILE_COUNT, EXPECTED_PHASE7_TREE_SHA256),
        "phase7_unchanged": phase7_before == phase7_after,
        "project_sources_match": sources_before == EXPECTED_PROJECT_SOURCE_SHA256,
        "project_sources_unchanged": sources_before == sources_after,
        "receipt_valid": True,
        "registration_chain_valid": True,
        "compute_claim_valid": True,
        "registered_identities_absent": True,
        "registered_process_groups_absent": True,
        "single_attempt_only": True,
        "dynamic_tree_allowed": True,
        "forbidden_artifacts_absent": not any(forbidden.values()),
        "terminal_state_valid": True,
    }
    if not all(checks.values()):
        raise RuntimeError("one or more terminal postflight checks failed")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "terminal_outcome": terminal_outcome,
        "checks": checks,
        "identity": FROZEN_IDENTITY,
        "resources": FROZEN_RESOURCES,
        "transport": {
            "inventory_sha256": expected_inventory_hash,
            "payload_manifest_sha256": inventory["payload_manifest_sha256"],
            "permit_sha256": permit_sha,
            "request_sha256": _object(payload["identity"], "payload identity")["request_sha256"],
            "runner_source_sha256": _object(payload["identity"], "payload identity")[
                "runner_source_sha256"
            ],
            "protocol_sha256": FROZEN_PROTOCOL_SHA256,
            "resources_sha256": _sha(_canonical(FROZEN_RESOURCES)),
            "transport_tree_sha256": inventory["transport_tree_sha256"],
            "directory_tree_sha256": inventory["directory_tree_sha256"],
            "static_file_count": len(transport_files) + 1,
        },
        "permit": {
            "ready_present": False,
            "consumed_sha256": permit_sha,
            "consumed_mode": "0400",
        },
        "phase7": {"file_count": phase7_before[0], "tree_sha256": phase7_before[1]},
        "project_source_sha256": sources_before,
        "process_cleanup": {
            "receipt_outcome": receipt["outcome"],
            "registered_identity_count": len(identities),
            "identity_status": identity_status,
            "group_status": group_status,
            "pid_reuse_observed": reuse_observed,
            "all_registered_identities_absent": True,
            "all_registered_groups_absent": True,
        },
        "runtime": {
            "guardian_receipt_sha256": receipt_sha,
            "worker_registration_sha256": registration_sha,
            "guardian_acknowledgement_sha256": acknowledgement_sha,
            "compute_claim_sha256": compute_claim_sha,
            **runtime_hashes,
        },
        "compute_claim": compute_claim_summary,
        "result": result,
        "failure": failure,
        "forbidden": forbidden,
        "safety": {
            "read_only": True,
            "remote_file_written": False,
            "remote_file_deleted": False,
            "process_signalled": False,
            "chemistry_imported": False,
            "quantum_execution_started": False,
            "logs_used_as_acceptance_evidence": False,
        },
    }


def _remote_main(arguments: list[str]) -> int:
    if len(arguments) != 3:
        raise SystemExit(
            "usage: --inspect-server PHASE7_RELATIVE PHASE8B_RELATIVE INVENTORY_SHA256"
        )
    payload = inspect_server(arguments[0], arguments[1], arguments[2])
    sys.stdout.buffer.write(_canonical(payload))
    sys.stdout.buffer.flush()
    return 0


def _local_main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--expected-transport-inventory-sha256", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--portable", action="store_true")
    parsed = parser.parse_args(arguments)
    from nhc_deprot_ranker.preparation.phase8b_postflight import (
        portable_phase8b_postflight,
        run_phase8b_postflight,
    )

    payload = run_phase8b_postflight(
        config_path=parsed.config,
        inspector_path=Path(__file__).resolve(),
        expected_transport_inventory_sha256=parsed.expected_transport_inventory_sha256,
        timeout_seconds=parsed.timeout_seconds,
    )
    if parsed.portable:
        payload = portable_phase8b_postflight(
            payload,
            expected_transport_inventory_sha256=parsed.expected_transport_inventory_sha256,
        )
    sys.stdout.buffer.write(_canonical(payload))
    sys.stdout.buffer.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] == "--inspect-server":
        return _remote_main(arguments[1:])
    return _local_main(arguments)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        message = "phase8b read-only postflight failed: " + type(exc).__name__ + ": " + str(exc)
        sys.stderr.write(message[:4096] + "\n")
        raise SystemExit(1) from None
