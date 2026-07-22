"""Deterministic, immutable execution-bundle builder for the Phase 8B smoke.

The public builder remains fail-closed while the reviewed runner source gate is
false.  The private pure seam exists only so synthetic tests can exercise the
hash layering without enabling a worker or importing a chemistry dependency.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Literal, Protocol, cast

from nhc_deprot_ranker.quantum.phase8b_permit import (
    FROZEN_ATTEMPT_ID,
    FROZEN_INCHIKEY,
    FROZEN_PROTOCOL_SHA256,
    FROZEN_REQUEST_ID,
    FROZEN_RESOURCES,
    render_phase8b_permit,
)

BUNDLE_SCHEMA_VERSION: Final = "phase8b.bundle.v2"
PAYLOAD_MANIFEST_SCHEMA_VERSION: Final = "phase8b.payload_manifest.v2"
TRANSPORT_INVENTORY_SCHEMA_VERSION: Final = "phase8b.transport_inventory.v2"
REQUEST_SCHEMA_VERSION: Final = "nhc-two-endpoint-request-v1"
BUNDLE_VERSION: Final = "phase8b-dft-smoke-v001"

PHASE7_INVENTORY_SHA256: Final = "f0e04f5adb32b7688cbe30ddc68b63263d78dfe7411955cfd0131847946dac3b"
PHASE7_SUCCESS_SHA256: Final = "a8fd8584eeafa249c903e1829d3522aaf8f13ecc4f3251c9e994a72498844362"
PHASE8A_EVIDENCE_SHA256: Final = "ba1c74dc919424a439a25f84e6d8b4e2f5a68d8af092aa049484546d8b1787a3"

_REMOTE_INVENTORY_NAME: Final = "remote_inventory.json"
_PHASE7_SUCCESS_NAME: Final = "_GEOMETRY_SMOKE_SUCCESS"
_PAYLOAD_MANIFEST_NAME: Final = "payload_manifest.json"
_PERMIT_NAME: Final = "private/permit.ready.json"
_TRANSPORT_INVENTORY_NAME: Final = "transport_inventory.json"
_REQUEST_NAME: Final = "input/request.json"
_FILE_MODE: Final = 0o640
_PERMIT_MODE: Final = 0o600
_BUNDLE_MODE: Final = 0o700
_DIRECTORY_MODE: Final = 0o750
_PRIVATE_DIRECTORY_MODE: Final = 0o700
_MAX_JSON_BYTES: Final = 2 * 1024 * 1024
_PRODUCTION_AUTHORIZATION_CONSUMED: Final = True


class Phase8BBundleError(RuntimeError):
    """A frozen input, source, path, hash layer, or output invariant failed."""


class Phase8BBundleNotAuthorizedError(Phase8BBundleError):
    """The reviewed source-level execution gate remains closed."""


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """One exact Phase 7/8A byte copied into the payload."""

    source: Literal["phase7", "phase8a"]
    source_relative: str
    destination_relative: str
    expected_sha256: str


FROZEN_ARTIFACTS: Final[tuple[ArtifactSpec, ...]] = (
    ArtifactSpec(
        "phase7",
        "m2/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_cation.xyz",
        "input/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_cation.xyz",
        "097f08ab7c3f265efa8ee36c3fd45d72776c9bdcbd3de503baf8fe91561c12aa",
    ),
    ArtifactSpec(
        "phase7",
        "m2/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_neutral.xyz",
        "input/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_neutral.xyz",
        "e41e87daca3c7a74383364a427d277df5cf8a0aa70bff015c4cf432455f26bd0",
    ),
    ArtifactSpec(
        "phase7",
        "audit/endpoint_atom_maps/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_endpoint_atom_map.json",
        "input/maps/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_endpoint_atom_map.json",
        "0cb13e918f2fa88348affb2385d37e01a75d73376118d18aa4c7647ef4982152",
    ),
    ArtifactSpec(
        "phase7",
        "m2/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_atom_map.json",
        "input/maps/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_legacy_atom_map.json",
        "7766fad207561b79ac8e7278b70eb07c37dcf31d4114b76ad9a9383b235681f8",
    ),
    ArtifactSpec(
        "phase7",
        "audit/geometry_validation.json",
        "evidence/phase7_geometry_validation.json",
        "35e99683a32e416752014c6e1ecb8121e2bc06d5407911435e5c1250fd639f90",
    ),
    ArtifactSpec(
        "phase7",
        "package_manifest.json",
        "evidence/phase7_package_manifest.json",
        "2c4d776ab009a1c265d080dc55392fc7cdf38137a62200fa4b67a38f79746ae9",
    ),
    ArtifactSpec(
        "phase7",
        "input/smoke_candidates.csv",
        "evidence/phase7_smoke_candidates.csv",
        "f486f93a2d58fb144c05a7340fd432334eeec46385c9319aca34d2e1b5c4cc87",
    ),
    ArtifactSpec(
        "phase7",
        "input/geometry_request.json",
        "evidence/phase7_geometry_request.json",
        "9993105e2a542d6abd1b8bf735640fb5bf3e9fd078bbb6ccc604e21768a5b5ef",
    ),
    ArtifactSpec(
        "phase7",
        _REMOTE_INVENTORY_NAME,
        "evidence/phase7_remote_inventory.json",
        PHASE7_INVENTORY_SHA256,
    ),
    ArtifactSpec(
        "phase8a",
        "PHASE8A_API_PREFLIGHT_V001.json",
        "evidence/phase8a_api_preflight.json",
        PHASE8A_EVIDENCE_SHA256,
    ),
)

_REQUIRED_FINAL_SOURCE_FILES: Final[frozenset[str]] = frozenset(
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


class PermitRenderer(Protocol):
    def __call__(
        self,
        *,
        project_root: str,
        request_sha256: str,
        runner_source_sha256: str,
        payload_manifest_sha256: str,
    ) -> bytes:
        """Return canonical private permit bytes."""


@dataclass(frozen=True, slots=True)
class Phase8BBundleResult:
    """Identity of one immutable local transfer bundle."""

    output_dir: Path
    request_sha256: str
    runner_source_sha256: str
    payload_manifest_sha256: str
    permit_sha256: str
    transport_inventory_sha256: str
    file_count: int


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
        raise Phase8BBundleError(f"{label} must be a lowercase SHA256")
    return value


def _safe_relative(value: str, *, label: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise Phase8BBundleError(f"{label} is not a safe relative path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
    ):
        raise Phase8BBundleError(f"{label} is not a canonical relative path")
    return relative


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, object]:
    if not raw or len(raw) > _MAX_JSON_BYTES:
        raise Phase8BBundleError(f"{label} byte size is invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase8BBundleError(f"{label} must be UTF-8") from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase8BBundleError(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise Phase8BBundleError(f"{label} contains non-finite number: {value}")

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except Phase8BBundleError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise Phase8BBundleError(f"{label} is not strict JSON") from exc
    if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
        raise Phase8BBundleError(f"{label} must be an object")
    return cast(dict[str, object], decoded)


def _read_regular(path: Path, *, label: str) -> bytes:
    if path.is_symlink():
        raise Phase8BBundleError(f"{label} must not be a symlink")
    try:
        if path.resolve(strict=True) != path:
            raise Phase8BBundleError(f"{label} traverses a symlink")
        file_stat = path.stat()
        raw = path.read_bytes()
    except Phase8BBundleError:
        raise
    except OSError as exc:
        raise Phase8BBundleError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise Phase8BBundleError(f"{label} must be a single-link regular file")
    return raw


def _validated_hash_map(value: object, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise Phase8BBundleError(f"{label} must be a non-empty hash object")
    result: dict[str, str] = {}
    for raw_name, raw_digest in value.items():
        if not isinstance(raw_name, str):
            raise Phase8BBundleError(f"{label} contains a non-string path")
        name = _safe_relative(raw_name, label=f"{label} path").as_posix()
        result[name] = _require_sha256(raw_digest, label=f"{label}[{name}]")
    return result


def _read_phase7_mirror(
    root: Path,
    *,
    expected_inventory_sha256: str,
    expected_success_sha256: str,
    require_production_identity: bool,
) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir() or root.resolve(strict=True) != root:
        raise Phase8BBundleError("Phase 7 mirror must be an exact real directory")
    inventory_path = root / _REMOTE_INVENTORY_NAME
    success_path = root / _PHASE7_SUCCESS_NAME
    inventory_raw = _read_regular(inventory_path, label="Phase 7 remote inventory")
    success_raw = _read_regular(success_path, label="Phase 7 success marker")
    if _sha256_bytes(inventory_raw) != expected_inventory_sha256:
        raise Phase8BBundleError("Phase 7 remote inventory SHA256 drifted")
    if _sha256_bytes(success_raw) != expected_success_sha256:
        raise Phase8BBundleError("Phase 7 success marker SHA256 drifted")

    inventory = _strict_json_object(inventory_raw, label="Phase 7 remote inventory")
    success = _strict_json_object(success_raw, label="Phase 7 success marker")
    hashes = _validated_hash_map(inventory.get("output_sha256"), label="Phase 7 output")
    if (
        inventory.get("schema_version") != "phase7.remote_inventory.v1"
        or inventory.get("validation_status") != "passed"
        or inventory.get("remote_local_hash_match") is not True
        or inventory.get("quantum_chemistry_run") is not False
        or inventory.get("hessian_computed") is not False
        or inventory.get("remote_mirror_file_count") != len(hashes)
    ):
        raise Phase8BBundleError("Phase 7 remote inventory status drifted")
    if (
        success.get("schema_version") != "phase7.geometry_smoke_success.v1"
        or success.get("status") != "geometry_smoke_passed"
        or success.get("remote_inventory_sha256") != expected_inventory_sha256
        or success.get("quantum_chemistry_run") is not False
        or success.get("hessian_computed") is not False
        or success.get("dedicated_runner_run") is not False
        or success.get("submit_hpc") is not False
        or success.get("remote_mirror_file_count") != len(hashes)
    ):
        raise Phase8BBundleError("Phase 7 success marker status drifted")
    if require_production_identity and (
        len(hashes) != 27
        or inventory.get("result_tree_sha256")
        != "644f027e276902dc1ab105f02f08864967f69ae87dc8883f608f5e4d17a372ad"
        or inventory.get("validated_candidates") != 4
        or success.get("validated_candidates") != 4
    ):
        raise Phase8BBundleError("Phase 7 production mirror identity drifted")

    actual_files: set[str] = set()
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise Phase8BBundleError(f"Phase 7 mirror contains a symlink: {name}")
        if path.is_file():
            actual_files.add(name)
    expected_files = {*hashes, _REMOTE_INVENTORY_NAME, _PHASE7_SUCCESS_NAME}
    if actual_files != expected_files:
        raise Phase8BBundleError("Phase 7 mirror file set drifted")

    contents: dict[str, bytes] = {
        _REMOTE_INVENTORY_NAME: inventory_raw,
        _PHASE7_SUCCESS_NAME: success_raw,
    }
    for name, expected_hash in sorted(hashes.items()):
        raw = _read_regular(root / Path(name), label=f"Phase 7 file {name}")
        if _sha256_bytes(raw) != expected_hash:
            raise Phase8BBundleError(f"Phase 7 file SHA256 drifted: {name}")
        contents[name] = raw
    return contents


def _read_phase8a_evidence(
    path: Path, *, expected_sha256: str, require_production_identity: bool
) -> bytes:
    raw = _read_regular(path, label="Phase 8A evidence")
    if _sha256_bytes(raw) != expected_sha256:
        raise Phase8BBundleError("Phase 8A evidence SHA256 drifted")
    payload = _strict_json_object(raw, label="Phase 8A evidence")
    safety = payload.get("safety")
    acceptance = payload.get("acceptance")
    versions = payload.get("versions")
    if (
        payload.get("schema_version") != "phase8a.api_preflight.v1"
        or payload.get("phase") != "8A"
        or payload.get("status") != "passed"
        or not isinstance(safety, dict)
        or safety.get("read_only") is not True
        or safety.get("molecule_constructed") is not False
        or safety.get("compute_kernel_called") is not False
        or safety.get("optimizer_called") is not False
        or safety.get("dispersion_evaluated") is not False
        or safety.get("hessian_computed") is not False
        or safety.get("server_file_written") is not False
        or not isinstance(acceptance, dict)
        or acceptance.get("passed") is not True
    ):
        raise Phase8BBundleError("Phase 8A evidence status drifted")
    if require_production_identity and versions != {
        "geometric": "1.1.1",
        "pyscf": "2.13.1",
        "pyscf_dispersion": "1.5.0",
        "python": "3.11.15",
    }:
        raise Phase8BBundleError("Phase 8A production versions drifted")
    return raw


def _canonical_runner_source_sha256(
    sources: Mapping[str, bytes], *, schema_version: str, ordered_paths: Sequence[str]
) -> str:
    if tuple(sources) != tuple(ordered_paths) or set(sources) != set(ordered_paths):
        raise Phase8BBundleError("runner source closure order or file set drifted")
    digest = hashlib.sha256()
    digest.update(schema_version.encode("ascii"))
    digest.update(b"\x00")
    for name in ordered_paths:
        encoded_name = name.encode("ascii")
        content = sources[name]
        if not content:
            raise Phase8BBundleError(f"runner source is empty: {name}")
        digest.update(len(encoded_name).to_bytes(2, "big"))
        digest.update(encoded_name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _read_source_closure(
    source_root: Path, source_relative_paths: Sequence[str]
) -> dict[str, bytes]:
    if source_root.is_symlink() or not source_root.is_dir() or source_root.resolve() != source_root:
        raise Phase8BBundleError("source root must be an exact real directory")
    if not source_relative_paths or len(set(source_relative_paths)) != len(source_relative_paths):
        raise Phase8BBundleError("runner source closure is empty or duplicated")
    result: dict[str, bytes] = {}
    for raw_name in source_relative_paths:
        name = _safe_relative(raw_name, label="runner source path").as_posix()
        try:
            name.encode("ascii")
        except UnicodeEncodeError as exc:
            raise Phase8BBundleError("runner source path must be ASCII") from exc
        result[name] = _read_regular(source_root / Path(name), label=f"runner source {name}")
    return result


def _file_entries(files: Mapping[str, bytes], modes: Mapping[str, int]) -> dict[str, object]:
    return {
        name: {
            "sha256": _sha256_bytes(files[name]),
            "bytes": len(files[name]),
            "mode": f"{modes[name]:04o}",
        }
        for name in sorted(files)
    }


def _tree_sha256(files: Mapping[str, bytes], modes: Mapping[str, int]) -> str:
    digest = hashlib.sha256()
    digest.update(b"phase8b-file-tree-v1\x00")
    for name in sorted(files):
        encoded = name.encode("ascii")
        digest.update(len(encoded).to_bytes(2, "big"))
        digest.update(encoded)
        digest.update(modes[name].to_bytes(2, "big"))
        digest.update(len(files[name]).to_bytes(8, "big"))
        digest.update(bytes.fromhex(_sha256_bytes(files[name])))
    return digest.hexdigest()


def _directory_modes_for_files(file_names: Sequence[str]) -> dict[str, int]:
    """Return the complete explicit directory contract for one bundle."""

    modes: dict[str, int] = {
        ".": _BUNDLE_MODE,
        "private": _PRIVATE_DIRECTORY_MODE,
        "runtime": _PRIVATE_DIRECTORY_MODE,
    }
    for raw_name in file_names:
        relative = _safe_relative(raw_name, label="directory source path")
        parent = relative.parent
        while parent != PurePosixPath("."):
            name = parent.as_posix()
            expected_mode = (
                _PRIVATE_DIRECTORY_MODE if name in {"private", "runtime"} else _DIRECTORY_MODE
            )
            previous = modes.setdefault(name, expected_mode)
            if previous != expected_mode:
                raise Phase8BBundleError(f"directory mode contract conflicts: {name}")
            parent = parent.parent
    return dict(sorted(modes.items()))


def _directory_entries(modes: Mapping[str, int]) -> dict[str, object]:
    return {name: {"mode": f"{modes[name]:04o}"} for name in sorted(modes)}


def _directory_tree_sha256(modes: Mapping[str, int]) -> str:
    digest = hashlib.sha256()
    digest.update(b"phase8b-directory-tree-v1\x00")
    for name in sorted(modes):
        encoded = name.encode("ascii")
        digest.update(len(encoded).to_bytes(2, "big"))
        digest.update(encoded)
        digest.update(modes[name].to_bytes(2, "big"))
    return digest.hexdigest()


def _validated_directory_entries(value: object, *, label: str) -> dict[str, int]:
    if not isinstance(value, dict) or not value:
        raise Phase8BBundleError(f"{label} must be a non-empty directory object")
    result: dict[str, int] = {}
    for raw_name, raw_entry in value.items():
        if not isinstance(raw_name, str) or not isinstance(raw_entry, dict):
            raise Phase8BBundleError(f"{label} entry is malformed")
        if raw_name == ".":
            name = raw_name
        else:
            name = _safe_relative(raw_name, label=f"{label} path").as_posix()
        if set(raw_entry) != {"mode"}:
            raise Phase8BBundleError(f"{label} entry fields drifted: {name}")
        raw_mode = raw_entry.get("mode")
        if not isinstance(raw_mode, str) or raw_mode not in {"0700", "0750"}:
            raise Phase8BBundleError(f"{label} mode is invalid: {name}")
        mode = int(raw_mode, 8)
        expected = (
            _BUNDLE_MODE
            if name == "."
            else _PRIVATE_DIRECTORY_MODE
            if name in {"private", "runtime"}
            else _DIRECTORY_MODE
        )
        if mode != expected:
            raise Phase8BBundleError(f"{label} mode drifted: {name}")
        result[name] = mode
    if result.get(".") != _BUNDLE_MODE:
        raise Phase8BBundleError(f"{label} omitted the root directory")
    if result.get("private") != _PRIVATE_DIRECTORY_MODE:
        raise Phase8BBundleError(f"{label} omitted the private directory")
    if result.get("runtime") != _PRIVATE_DIRECTORY_MODE:
        raise Phase8BBundleError(f"{label} omitted the runtime directory")
    return dict(sorted(result.items()))


def _validate_bundle_tree(root: Path, *, expected_inventory_sha256: str) -> None:
    if root.is_symlink() or not root.is_dir() or root.resolve(strict=True) != root:
        raise Phase8BBundleError("bundle root must be an exact real directory")
    if stat.S_IMODE(root.stat().st_mode) != _BUNDLE_MODE:
        raise Phase8BBundleError("bundle root mode drifted")
    inventory_path = root / _TRANSPORT_INVENTORY_NAME
    inventory_raw = _read_regular(inventory_path, label="transport inventory")
    if _sha256_bytes(inventory_raw) != expected_inventory_sha256:
        raise Phase8BBundleError("transport inventory SHA256 drifted after staging")
    inventory = _strict_json_object(inventory_raw, label="transport inventory")
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
        raise Phase8BBundleError("transport inventory fields drifted")
    if (
        inventory.get("schema_version") != TRANSPORT_INVENTORY_SCHEMA_VERSION
        or inventory.get("bundle_version") != BUNDLE_VERSION
        or inventory.get("excluded_from_inventory") != [_TRANSPORT_INVENTORY_NAME]
    ):
        raise Phase8BBundleError("transport inventory identity drifted")
    entries = inventory.get("files")
    if not isinstance(entries, dict) or not entries:
        raise Phase8BBundleError("transport inventory files are invalid")
    directory_modes = _validated_directory_entries(
        inventory.get("directories"), label="transport directories"
    )
    if inventory.get("directory_tree_sha256") != _directory_tree_sha256(directory_modes):
        raise Phase8BBundleError("transport directory tree SHA256 drifted")
    expected_directory_modes = _directory_modes_for_files(
        (*cast(dict[str, object], entries), _TRANSPORT_INVENTORY_NAME)
    )
    if directory_modes != expected_directory_modes:
        raise Phase8BBundleError("transport directory contract contains extras or omissions")

    actual_files: set[str] = set()
    actual_directories: set[str] = {"."}
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise Phase8BBundleError(f"bundle contains a symlink: {name}")
        if path.is_file():
            actual_files.add(name)
        elif path.is_dir():
            actual_directories.add(name)
        else:
            raise Phase8BBundleError(f"bundle contains a non-file entry: {name}")
    if actual_files != {*entries, _TRANSPORT_INVENTORY_NAME}:
        raise Phase8BBundleError("bundle file set differs from transport inventory")
    if actual_directories != set(directory_modes):
        raise Phase8BBundleError("bundle directory set differs from transport inventory")
    for name, expected_mode in directory_modes.items():
        directory = root if name == "." else root / Path(name)
        if stat.S_IMODE(directory.stat().st_mode) != expected_mode:
            raise Phase8BBundleError(f"bundle directory mode drifted: {name}")

    transport_files: dict[str, bytes] = {}
    transport_modes: dict[str, int] = {}
    for raw_name, raw_entry in entries.items():
        if not isinstance(raw_name, str) or not isinstance(raw_entry, dict):
            raise Phase8BBundleError("transport inventory entry is malformed")
        name = _safe_relative(raw_name, label="transport path").as_posix()
        if set(raw_entry) != {"sha256", "bytes", "mode"}:
            raise Phase8BBundleError(f"transport entry fields drifted: {name}")
        path = root / Path(name)
        raw = _read_regular(path, label=f"transport file {name}")
        mode = stat.S_IMODE(path.stat().st_mode)
        if (
            _sha256_bytes(raw) != raw_entry.get("sha256")
            or len(raw) != raw_entry.get("bytes")
            or f"{mode:04o}" != raw_entry.get("mode")
        ):
            raise Phase8BBundleError(f"transport entry drifted: {name}")
        transport_files[name] = raw
        transport_modes[name] = mode
    if inventory.get("transport_tree_sha256") != _tree_sha256(transport_files, transport_modes):
        raise Phase8BBundleError("transport file tree SHA256 drifted")
    if stat.S_IMODE(inventory_path.stat().st_mode) != _FILE_MODE:
        raise Phase8BBundleError("transport inventory mode drifted")

    payload_raw = transport_files.get(_PAYLOAD_MANIFEST_NAME)
    if payload_raw is None:
        raise Phase8BBundleError("payload manifest is missing from transport")
    if _sha256_bytes(payload_raw) != inventory.get("payload_manifest_sha256"):
        raise Phase8BBundleError("payload manifest SHA256 drifted in transport")
    payload = _strict_json_object(payload_raw, label="payload manifest")
    if set(payload) != {
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
    }:
        raise Phase8BBundleError("payload manifest fields drifted")
    payload_directory_modes = _validated_directory_entries(
        payload.get("directories"), label="payload directories"
    )
    if payload_directory_modes != directory_modes:
        raise Phase8BBundleError("payload and transport directory contracts differ")
    if payload.get("directory_tree_sha256") != _directory_tree_sha256(payload_directory_modes):
        raise Phase8BBundleError("payload directory tree SHA256 drifted")


def _prepare_phase8b_bundle(
    *,
    phase7_result_dir: Path,
    phase8a_evidence_path: Path,
    source_root: Path,
    source_relative_paths: Sequence[str],
    runner_source_schema_version: str,
    expected_runner_source_sha256: str,
    protocol: Mapping[str, object],
    remote_project_root: str,
    output_dir: Path,
    artifacts: Sequence[ArtifactSpec],
    expected_phase7_inventory_sha256: str,
    expected_phase7_success_sha256: str,
    expected_phase8a_evidence_sha256: str,
    require_production_identity: bool,
    permit_renderer: PermitRenderer = render_phase8b_permit,
) -> Phase8BBundleResult:
    """Private pure seam; synthetic callers still inherit the source gate."""

    from nhc_deprot_ranker.quantum import two_endpoint as runner

    if runner.EXECUTION_AUTHORIZED is not True:
        raise Phase8BBundleNotAuthorizedError("Phase 8B source execution gate is closed")
    if _PRODUCTION_AUTHORIZATION_CONSUMED:
        raise Phase8BBundleNotAuthorizedError(
            "the unique Phase 8B production authorization has been consumed"
        )
    if os.path.lexists(output_dir):
        raise FileExistsError(f"immutable Phase 8B bundle already exists: {output_dir}")
    if output_dir.parent.is_symlink() or not output_dir.parent.is_dir():
        raise Phase8BBundleError("bundle output parent must be an existing real directory")
    if output_dir.parent.resolve(strict=True) != output_dir.parent:
        raise Phase8BBundleError("bundle output parent must not traverse a symlink")

    root = PurePosixPath(remote_project_root)
    if (
        not root.is_absolute()
        or root == PurePosixPath("/")
        or root.as_posix() != remote_project_root
    ):
        raise Phase8BBundleError("remote project root must be a normalized specific POSIX path")
    if ".." in root.parts:
        raise Phase8BBundleError("remote project root contains traversal")

    phase7 = _read_phase7_mirror(
        phase7_result_dir,
        expected_inventory_sha256=_require_sha256(
            expected_phase7_inventory_sha256, label="expected Phase 7 inventory SHA256"
        ),
        expected_success_sha256=_require_sha256(
            expected_phase7_success_sha256, label="expected Phase 7 success SHA256"
        ),
        require_production_identity=require_production_identity,
    )
    phase8a_raw = _read_phase8a_evidence(
        phase8a_evidence_path,
        expected_sha256=_require_sha256(
            expected_phase8a_evidence_sha256, label="expected Phase 8A evidence SHA256"
        ),
        require_production_identity=require_production_identity,
    )
    if not artifacts or len({item.destination_relative for item in artifacts}) != len(artifacts):
        raise Phase8BBundleError("artifact destination set is empty or duplicated")
    if require_production_identity and tuple(artifacts) != FROZEN_ARTIFACTS:
        raise Phase8BBundleError("production artifact specification drifted")

    staged: dict[str, bytes] = {}
    artifact_hashes: dict[str, str] = {}
    for item in artifacts:
        destination = _safe_relative(
            item.destination_relative, label="artifact destination"
        ).as_posix()
        expected_hash = _require_sha256(item.expected_sha256, label=f"artifact {destination}")
        if item.source == "phase7":
            source_name = _safe_relative(
                item.source_relative, label="Phase 7 artifact source"
            ).as_posix()
            try:
                raw = phase7[source_name]
            except KeyError as exc:
                raise Phase8BBundleError(
                    f"Phase 7 artifact is not registered: {source_name}"
                ) from exc
        elif item.source == "phase8a":
            if item.source_relative != "PHASE8A_API_PREFLIGHT_V001.json":
                raise Phase8BBundleError("Phase 8A artifact source drifted")
            raw = phase8a_raw
        else:  # pragma: no cover - protected by the literal type
            raise Phase8BBundleError("artifact source kind is invalid")
        if _sha256_bytes(raw) != expected_hash:
            raise Phase8BBundleError(f"frozen artifact SHA256 drifted: {destination}")
        staged[destination] = raw
        artifact_hashes[destination] = expected_hash

    source_paths = tuple(source_relative_paths)
    source_bytes = _read_source_closure(source_root, source_paths)
    runner_source_sha256 = _canonical_runner_source_sha256(
        source_bytes,
        schema_version=runner_source_schema_version,
        ordered_paths=source_paths,
    )
    if runner_source_sha256 != _require_sha256(
        expected_runner_source_sha256, label="expected runner source SHA256"
    ):
        raise Phase8BBundleError("runner source closure SHA256 drifted")
    if require_production_identity and not _REQUIRED_FINAL_SOURCE_FILES.issubset(source_bytes):
        raise Phase8BBundleError("final Phase 8B source closure is incomplete")
    for name, raw in source_bytes.items():
        staged[f"src/{name}"] = raw

    protocol_payload = dict(protocol)
    protocol_sha256 = _sha256_bytes(_canonical_json_bytes(protocol_payload))
    if require_production_identity and protocol_sha256 != FROZEN_PROTOCOL_SHA256:
        raise Phase8BBundleError("frozen protocol SHA256 drifted")

    cation_name = "input/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_cation.xyz"
    neutral_name = "input/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_neutral.xyz"
    if cation_name not in artifact_hashes or neutral_name not in artifact_hashes:
        raise Phase8BBundleError("bundle lacks the exact two QXH endpoint inputs")
    request_payload: dict[str, object] = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "request_id": FROZEN_REQUEST_ID,
        "inchikey": FROZEN_INCHIKEY,
        "execution_authorized": True,
        "timeout_seconds": FROZEN_RESOURCES["hard_wall_timeout_seconds"],
        "runner_source_sha256": runner_source_sha256,
        "protocol": protocol_payload,
        "endpoints": {
            "cation": {
                "xyz_path": "xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_cation.xyz",
                "xyz_sha256": artifact_hashes[cation_name],
                "charge": 1,
                "multiplicity": 1,
            },
            "neutral": {
                "xyz_path": "xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_neutral.xyz",
                "xyz_sha256": artifact_hashes[neutral_name],
                "charge": 0,
                "multiplicity": 1,
            },
        },
    }
    request_raw = _canonical_json_bytes(request_payload)
    staged[_REQUEST_NAME] = request_raw
    request_sha256 = _sha256_bytes(request_raw)

    directory_modes = _directory_modes_for_files(
        (
            *staged,
            _PAYLOAD_MANIFEST_NAME,
            _PERMIT_NAME,
            _TRANSPORT_INVENTORY_NAME,
        )
    )
    payload_modes = {name: _FILE_MODE for name in staged}
    payload_manifest = {
        "schema_version": PAYLOAD_MANIFEST_SCHEMA_VERSION,
        "bundle_version": BUNDLE_VERSION,
        "identity": {
            "inchikey": FROZEN_INCHIKEY,
            "request_id": FROZEN_REQUEST_ID,
            "attempt_id": FROZEN_ATTEMPT_ID,
            "request_sha256": request_sha256,
            "runner_source_sha256": runner_source_sha256,
            "protocol_sha256": protocol_sha256,
            "endpoint_order": ["cation", "neutral"],
        },
        "resources": FROZEN_RESOURCES,
        "source_relative_paths": list(source_paths),
        "artifact_sha256": dict(sorted(artifact_hashes.items())),
        "files": _file_entries(staged, payload_modes),
        "payload_tree_sha256": _tree_sha256(staged, payload_modes),
        "directories": _directory_entries(directory_modes),
        "directory_tree_sha256": _directory_tree_sha256(directory_modes),
        "excluded_from_manifest": [
            _PAYLOAD_MANIFEST_NAME,
            _PERMIT_NAME,
            _TRANSPORT_INVENTORY_NAME,
        ],
    }
    payload_manifest_raw = _canonical_json_bytes(payload_manifest)
    payload_manifest_sha256 = _sha256_bytes(payload_manifest_raw)

    permit_raw = permit_renderer(
        project_root=remote_project_root,
        request_sha256=request_sha256,
        runner_source_sha256=runner_source_sha256,
        payload_manifest_sha256=payload_manifest_sha256,
    )
    if not isinstance(permit_raw, bytes) or not permit_raw:
        raise Phase8BBundleError("permit renderer did not return non-empty bytes")
    permit_sha256 = _sha256_bytes(permit_raw)

    transfer_files = {
        **staged,
        _PAYLOAD_MANIFEST_NAME: payload_manifest_raw,
        _PERMIT_NAME: permit_raw,
    }
    transfer_modes = {
        **payload_modes,
        _PAYLOAD_MANIFEST_NAME: _FILE_MODE,
        _PERMIT_NAME: _PERMIT_MODE,
    }
    transport_inventory = {
        "schema_version": TRANSPORT_INVENTORY_SCHEMA_VERSION,
        "bundle_version": BUNDLE_VERSION,
        "payload_manifest_sha256": payload_manifest_sha256,
        "permit_sha256": permit_sha256,
        "files": _file_entries(transfer_files, transfer_modes),
        "transport_tree_sha256": _tree_sha256(transfer_files, transfer_modes),
        "directories": _directory_entries(directory_modes),
        "directory_tree_sha256": _directory_tree_sha256(directory_modes),
        "excluded_from_inventory": [_TRANSPORT_INVENTORY_NAME],
    }
    transport_inventory_raw = _canonical_json_bytes(transport_inventory)
    transport_inventory_sha256 = _sha256_bytes(transport_inventory_raw)
    all_files = {**transfer_files, _TRANSPORT_INVENTORY_NAME: transport_inventory_raw}
    all_modes = {**transfer_modes, _TRANSPORT_INVENTORY_NAME: _FILE_MODE}

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=str(output_dir.parent))
    )
    temporary.chmod(_BUNDLE_MODE)
    try:
        for name, mode in sorted(
            directory_modes.items(),
            key=lambda item: (0 if item[0] == "." else len(PurePosixPath(item[0]).parts), item[0]),
        ):
            directory = temporary if name == "." else temporary / Path(name)
            if name != ".":
                directory.mkdir(parents=False, exist_ok=False)
            directory.chmod(mode)
        for name, raw in sorted(all_files.items()):
            relative = _safe_relative(name, label="staged bundle path")
            path = temporary.joinpath(*relative.parts)
            if not path.parent.is_dir():
                raise Phase8BBundleError(f"staged parent directory is unregistered: {name}")
            path.write_bytes(raw)
            path.chmod(all_modes[name])
        _validate_bundle_tree(
            temporary,
            expected_inventory_sha256=transport_inventory_sha256,
        )
        if os.path.lexists(output_dir):
            raise FileExistsError(f"immutable Phase 8B bundle already exists: {output_dir}")
        temporary.rename(output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return Phase8BBundleResult(
        output_dir=output_dir,
        request_sha256=request_sha256,
        runner_source_sha256=runner_source_sha256,
        payload_manifest_sha256=payload_manifest_sha256,
        permit_sha256=permit_sha256,
        transport_inventory_sha256=transport_inventory_sha256,
        file_count=len(all_files),
    )


def prepare_phase8b_bundle(
    *,
    phase7_result_dir: Path,
    phase8a_evidence_path: Path,
    source_root: Path,
    remote_project_root: str,
    output_dir: Path,
) -> Phase8BBundleResult:
    """Build the production bundle only after the reviewed source gate is true."""

    from nhc_deprot_ranker.quantum import two_endpoint as runner

    if runner.EXECUTION_AUTHORIZED is not True:
        raise Phase8BBundleNotAuthorizedError("Phase 8B source execution gate is closed")
    source_relative_paths = runner._RUNNER_SOURCE_RELATIVE_PATHS
    return _prepare_phase8b_bundle(
        phase7_result_dir=phase7_result_dir,
        phase8a_evidence_path=phase8a_evidence_path,
        source_root=source_root,
        source_relative_paths=source_relative_paths,
        runner_source_schema_version=runner.RUNNER_SOURCE_SCHEMA_VERSION,
        expected_runner_source_sha256=runner.current_runner_source_sha256(),
        protocol=runner.LOCKED_PROTOCOL,
        remote_project_root=remote_project_root,
        output_dir=output_dir,
        artifacts=FROZEN_ARTIFACTS,
        expected_phase7_inventory_sha256=PHASE7_INVENTORY_SHA256,
        expected_phase7_success_sha256=PHASE7_SUCCESS_SHA256,
        expected_phase8a_evidence_sha256=PHASE8A_EVIDENCE_SHA256,
        require_production_identity=True,
    )


__all__ = [
    "BUNDLE_VERSION",
    "FROZEN_ARTIFACTS",
    "FROZEN_INCHIKEY",
    "FROZEN_REQUEST_ID",
    "PHASE7_INVENTORY_SHA256",
    "PHASE7_SUCCESS_SHA256",
    "PHASE8A_EVIDENCE_SHA256",
    "ArtifactSpec",
    "Phase8BBundleError",
    "Phase8BBundleNotAuthorizedError",
    "Phase8BBundleResult",
    "prepare_phase8b_bundle",
    "render_phase8b_permit",
]
