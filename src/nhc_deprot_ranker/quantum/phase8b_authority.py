"""Exact post-consumption authority checks for the one Phase 8B smoke.

The one-shot permit proves an irreversible authorization transition.  This
module independently proves that the request and Phase 7 evidence behind that
transition are the single pre-registered QXH cation/neutral pair.  It imports
no chemistry package and is safe to run before the worker bootstrap release.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Protocol, cast

from nhc_deprot_ranker.quantum.phase8b_permit import (
    FROZEN_ATTEMPT_ID,
    FROZEN_INCHIKEY,
    FROZEN_INPUT_SHA256,
    FROZEN_PROTOCOL_SHA256,
    FROZEN_REQUEST_ID,
    FROZEN_RESOURCES,
    ConsumedPhase8BPermit,
)

PHASE7_GEOMETRY_VALIDATION_SHA256: Final = (
    "35e99683a32e416752014c6e1ecb8121e2bc06d5407911435e5c1250fd639f90"
)
ENDPOINT_MAP_RELATIVE: Final = "input/maps/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_endpoint_atom_map.json"
LEGACY_MAP_RELATIVE: Final = "input/maps/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_legacy_atom_map.json"
GEOMETRY_VALIDATION_RELATIVE: Final = "evidence/phase7_geometry_validation.json"
FROZEN_ELECTRON_COUNT: Final = 120
_PUBLIC_MODE: Final = 0o640
_MAX_JSON_BYTES: Final = 2 * 1024 * 1024
_MAX_BOUND_FILE_BYTES: Final = 8 * 1024 * 1024
_QXH_LEGACY_MAP: Final[dict[str, int]] = {"C2_carbene": 4, "N1": 3, "N3": 5}
_PAYLOAD_MANIFEST_RELATIVE: Final = "payload_manifest.json"
_TRANSPORT_INVENTORY_RELATIVE: Final = "transport_inventory.json"
_PERMIT_READY_RELATIVE: Final = "private/permit.ready.json"
_PAYLOAD_SCHEMA: Final = "phase8b.payload_manifest.v2"
_TRANSPORT_SCHEMA: Final = "phase8b.transport_inventory.v2"
_BUNDLE_VERSION: Final = "phase8b-dft-smoke-v001"
_DIRECTORY_MODE: Final = 0o750
_PRIVATE_DIRECTORY_MODE: Final = 0o700
_PERMIT_READY_MODE: Final = 0o600
_FROZEN_ARTIFACT_SHA256: Final[dict[str, str]] = {
    "input/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_cation.xyz": FROZEN_INPUT_SHA256["cation_xyz"],
    "input/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_neutral.xyz": FROZEN_INPUT_SHA256["neutral_xyz"],
    ENDPOINT_MAP_RELATIVE: FROZEN_INPUT_SHA256["endpoint_atom_map"],
    LEGACY_MAP_RELATIVE: FROZEN_INPUT_SHA256["legacy_atom_map"],
    GEOMETRY_VALIDATION_RELATIVE: PHASE7_GEOMETRY_VALIDATION_SHA256,
    "evidence/phase7_package_manifest.json": (
        "2c4d776ab009a1c265d080dc55392fc7cdf38137a62200fa4b67a38f79746ae9"
    ),
    "evidence/phase7_smoke_candidates.csv": (
        "f486f93a2d58fb144c05a7340fd432334eeec46385c9319aca34d2e1b5c4cc87"
    ),
    "evidence/phase7_geometry_request.json": (
        "9993105e2a542d6abd1b8bf735640fb5bf3e9fd078bbb6ccc604e21768a5b5ef"
    ),
    "evidence/phase7_remote_inventory.json": (
        "f0e04f5adb32b7688cbe30ddc68b63263d78dfe7411955cfd0131847946dac3b"
    ),
    "evidence/phase8a_api_preflight.json": (
        "ba1c74dc919424a439a25f84e6d8b4e2f5a68d8af092aa049484546d8b1787a3"
    ),
}


class Phase8BAuthorityError(RuntimeError):
    """The consumed permit does not authorize the supplied exact request."""


class _AtomLike(Protocol):
    element: str


class _GeometryLike(Protocol):
    atoms: tuple[_AtomLike, ...]


class _EndpointLike(Protocol):
    xyz_sha256: str
    charge: int
    multiplicity: int
    electron_count: int
    geometry: _GeometryLike


class Phase8BRequestLike(Protocol):
    schema_version: str
    request_id: str
    inchikey: str
    execution_authorized: bool
    timeout_seconds: int
    runner_source_sha256: str
    request_path: Path
    request_sha256: str
    protocol_sha256: str
    cation: _EndpointLike
    neutral: _EndpointLike


@dataclass(frozen=True, slots=True)
class ExactPhase8BAuthority:
    """Portable identity proven before any worker may be spawned or released."""

    request_sha256: str
    runner_source_sha256: str
    permit_sha256: str
    payload_manifest_sha256: str
    endpoint_atom_map_sha256: str
    legacy_atom_map_sha256: str
    geometry_validation_sha256: str
    electron_count: int
    request_id: str
    inchikey: str
    attempt_id: str
    project_root: str
    run_root: str
    request_path: str
    output_root: str
    resources_sha256: str


@dataclass(frozen=True, slots=True)
class Phase8BBundleIdentity:
    """Strict pre-consumption identity extracted from the outer inventory."""

    transport_inventory_sha256: str
    payload_manifest_sha256: str
    permit_sha256: str
    request_sha256: str
    runner_source_sha256: str


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, object]:
    if not raw or len(raw) > _MAX_JSON_BYTES:
        raise Phase8BAuthorityError(f"{label} byte size is invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase8BAuthorityError(f"{label} must be UTF-8") from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase8BAuthorityError(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise Phase8BAuthorityError(f"{label} contains non-finite number: {value}")

    try:
        payload = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except Phase8BAuthorityError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise Phase8BAuthorityError(f"{label} is not strict JSON") from exc
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise Phase8BAuthorityError(f"{label} must be an object")
    return cast(dict[str, object], payload)


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _require_sha256(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise Phase8BAuthorityError(f"{label} must be a lowercase SHA256")
    return value


def _safe_relative(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise Phase8BAuthorityError(f"{label} is not a safe relative path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
    ):
        raise Phase8BAuthorityError(f"{label} is not a canonical relative path")
    return value


def _read_bound_bytes(
    path: Path,
    *,
    expected_sha256: str,
    expected_mode: int,
    label: str,
) -> bytes:
    if path.is_symlink():
        raise Phase8BAuthorityError(f"{label} must not be a symlink")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise Phase8BAuthorityError("platform lacks O_NOFOLLOW")
    descriptor: int | None = None
    try:
        if path.resolve(strict=True) != path:
            raise Phase8BAuthorityError(f"{label} traverses a symlink")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | nofollow)
        opened_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_uid != os.geteuid()
            or opened_stat.st_nlink != 1
            or stat.S_IMODE(opened_stat.st_mode) != expected_mode
            or opened_stat.st_size <= 0
            or opened_stat.st_size > _MAX_BOUND_FILE_BYTES
        ):
            raise Phase8BAuthorityError(f"{label} filesystem identity drifted")
        chunks: list[bytes] = []
        remaining = opened_stat.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise Phase8BAuthorityError(f"{label} changed while read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise Phase8BAuthorityError(f"{label} grew while read")
        finished_stat = os.fstat(descriptor)
        current_stat = os.stat(path, follow_symlinks=False)
    except Phase8BAuthorityError:
        raise
    except OSError as exc:
        raise Phase8BAuthorityError(f"{label} is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(
        getattr(opened_stat, field) != getattr(observed, field)
        for observed in (finished_stat, current_stat)
        for field in identity_fields
    ):
        raise Phase8BAuthorityError(f"{label} changed while read")
    raw = b"".join(chunks)
    if len(raw) != opened_stat.st_size:
        raise Phase8BAuthorityError(f"{label} byte count drifted")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Phase8BAuthorityError(f"{label} SHA256 drifted")
    return raw


def _file_tree_sha256(entries: Mapping[str, tuple[str, int, int]]) -> str:
    digest = hashlib.sha256()
    digest.update(b"phase8b-file-tree-v1\x00")
    for name in sorted(entries):
        file_sha256, byte_count, mode = entries[name]
        encoded = name.encode("ascii")
        digest.update(len(encoded).to_bytes(2, "big"))
        digest.update(encoded)
        digest.update(mode.to_bytes(2, "big"))
        digest.update(byte_count.to_bytes(8, "big"))
        digest.update(bytes.fromhex(file_sha256))
    return digest.hexdigest()


def _directory_modes_for_files(file_names: Sequence[str]) -> dict[str, int]:
    result: dict[str, int] = {
        ".": _PRIVATE_DIRECTORY_MODE,
        "private": _PRIVATE_DIRECTORY_MODE,
        "runtime": _PRIVATE_DIRECTORY_MODE,
    }
    for name in file_names:
        parent = PurePosixPath(_safe_relative(name, label="bundle file path")).parent
        while parent != PurePosixPath("."):
            text = parent.as_posix()
            result[text] = (
                _PRIVATE_DIRECTORY_MODE if text in {"private", "runtime"} else _DIRECTORY_MODE
            )
            parent = parent.parent
    return dict(sorted(result.items()))


def _parse_directory_modes(value: object, *, label: str) -> dict[str, int]:
    if not isinstance(value, dict) or not value:
        raise Phase8BAuthorityError(f"{label} is invalid")
    result: dict[str, int] = {}
    for raw_name, raw_entry in value.items():
        if not isinstance(raw_name, str) or not isinstance(raw_entry, dict):
            raise Phase8BAuthorityError(f"{label} entry is malformed")
        name = raw_name if raw_name == "." else _safe_relative(raw_name, label=label)
        if set(raw_entry) != {"mode"} or raw_entry.get("mode") not in {"0700", "0750"}:
            raise Phase8BAuthorityError(f"{label} mode entry drifted")
        result[name] = int(cast(str, raw_entry["mode"]), 8)
    return dict(sorted(result.items()))


def _directory_tree_sha256(modes: Mapping[str, int]) -> str:
    digest = hashlib.sha256()
    digest.update(b"phase8b-directory-tree-v1\x00")
    for name in sorted(modes):
        encoded = name.encode("ascii")
        digest.update(len(encoded).to_bytes(2, "big"))
        digest.update(encoded)
        digest.update(modes[name].to_bytes(2, "big"))
    return digest.hexdigest()


def _parse_file_entries(value: object, *, label: str) -> dict[str, tuple[str, int, int]]:
    if not isinstance(value, dict) or not value:
        raise Phase8BAuthorityError(f"{label} is invalid")
    result: dict[str, tuple[str, int, int]] = {}
    for raw_name, raw_entry in value.items():
        name = _safe_relative(raw_name, label=label)
        if not isinstance(raw_entry, dict) or set(raw_entry) != {"sha256", "bytes", "mode"}:
            raise Phase8BAuthorityError(f"{label} entry fields drifted: {name}")
        digest = _require_sha256(raw_entry.get("sha256"), label=f"{label} {name}")
        byte_count = raw_entry.get("bytes")
        raw_mode = raw_entry.get("mode")
        if (
            isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or byte_count <= 0
            or raw_mode not in {"0600", "0640"}
        ):
            raise Phase8BAuthorityError(f"{label} entry value drifted: {name}")
        result[name] = (digest, byte_count, int(cast(str, raw_mode), 8))
    return dict(sorted(result.items()))


def _read_bound_json(path: Path, *, expected_sha256: str, label: str) -> dict[str, object]:
    raw = _read_bound_bytes(
        path,
        expected_sha256=expected_sha256,
        expected_mode=_PUBLIC_MODE,
        label=label,
    )
    return _strict_json_object(raw, label=label)


def _validate_payload_manifest(
    run_root: Path,
    *,
    expected_payload_manifest_sha256: str,
    expected_request_sha256: str,
    expected_runner_source_sha256: str,
    expected_source_relative_paths: Sequence[str],
) -> dict[str, tuple[str, int, int]]:
    manifest_path = run_root / _PAYLOAD_MANIFEST_RELATIVE
    manifest_raw = _read_bound_bytes(
        manifest_path,
        expected_sha256=expected_payload_manifest_sha256,
        expected_mode=_PUBLIC_MODE,
        label="Phase 8B payload manifest",
    )
    manifest = _strict_json_object(manifest_raw, label="Phase 8B payload manifest")
    if manifest_raw != _canonical_json_bytes(manifest):
        raise Phase8BAuthorityError("payload manifest is not canonical JSON")
    expected_fields = {
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
    }
    if set(manifest) != expected_fields:
        raise Phase8BAuthorityError("payload manifest fields drifted")
    identity = {
        "inchikey": FROZEN_INCHIKEY,
        "request_id": FROZEN_REQUEST_ID,
        "attempt_id": FROZEN_ATTEMPT_ID,
        "request_sha256": expected_request_sha256,
        "runner_source_sha256": expected_runner_source_sha256,
        "protocol_sha256": FROZEN_PROTOCOL_SHA256,
        "endpoint_order": ["cation", "neutral"],
    }
    source_paths = tuple(
        _safe_relative(name, label="runner source path") for name in expected_source_relative_paths
    )
    if (
        manifest.get("schema_version") != _PAYLOAD_SCHEMA
        or manifest.get("bundle_version") != _BUNDLE_VERSION
        or manifest.get("identity") != identity
        or manifest.get("resources") != FROZEN_RESOURCES
        or manifest.get("source_relative_paths") != list(source_paths)
        or manifest.get("artifact_sha256") != dict(sorted(_FROZEN_ARTIFACT_SHA256.items()))
        or manifest.get("excluded_from_manifest")
        != [
            _PAYLOAD_MANIFEST_RELATIVE,
            _PERMIT_READY_RELATIVE,
            _TRANSPORT_INVENTORY_RELATIVE,
        ]
    ):
        raise Phase8BAuthorityError("payload manifest frozen identity drifted")

    entries = _parse_file_entries(manifest.get("files"), label="payload files")
    expected_names = {
        "input/request.json",
        *_FROZEN_ARTIFACT_SHA256,
        *(f"src/{name}" for name in source_paths),
    }
    if set(entries) != expected_names:
        raise Phase8BAuthorityError("payload manifest file set drifted")
    if entries["input/request.json"][0] != expected_request_sha256:
        raise Phase8BAuthorityError("payload request registration drifted")
    for name, expected_hash in _FROZEN_ARTIFACT_SHA256.items():
        if entries[name][0] != expected_hash:
            raise Phase8BAuthorityError(f"payload artifact registration drifted: {name}")
    if any(mode != _PUBLIC_MODE for _, _, mode in entries.values()):
        raise Phase8BAuthorityError("payload file mode contract drifted")
    for name, (digest, byte_count, mode) in entries.items():
        raw = _read_bound_bytes(
            run_root / Path(name),
            expected_sha256=digest,
            expected_mode=mode,
            label=f"payload file {name}",
        )
        if len(raw) != byte_count:
            raise Phase8BAuthorityError(f"payload file byte count drifted: {name}")
    if manifest.get("payload_tree_sha256") != _file_tree_sha256(entries):
        raise Phase8BAuthorityError("payload file tree SHA256 drifted")

    directory_modes = _parse_directory_modes(
        manifest.get("directories"), label="payload directories"
    )
    expected_directory_modes = _directory_modes_for_files(
        (
            *entries,
            _PAYLOAD_MANIFEST_RELATIVE,
            _PERMIT_READY_RELATIVE,
            _TRANSPORT_INVENTORY_RELATIVE,
        )
    )
    if directory_modes != expected_directory_modes:
        raise Phase8BAuthorityError("payload directory contract drifted")
    if manifest.get("directory_tree_sha256") != _directory_tree_sha256(directory_modes):
        raise Phase8BAuthorityError("payload directory tree SHA256 drifted")
    for name, expected_mode in directory_modes.items():
        path = run_root if name == "." else run_root / Path(name)
        if path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
            raise Phase8BAuthorityError(f"payload directory is unsafe: {name}")
        observed = path.stat()
        if observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) != expected_mode:
            raise Phase8BAuthorityError(f"payload directory mode/owner drifted: {name}")
    return entries


def validate_phase8b_transport_bundle(
    run_root: Path,
    *,
    expected_transport_inventory_sha256: str,
    expected_source_relative_paths: Sequence[str],
) -> Phase8BBundleIdentity:
    """Verify the complete untouched transfer tree before permit consumption."""

    if (
        not run_root.is_absolute()
        or run_root.is_symlink()
        or not run_root.is_dir()
        or run_root.resolve(strict=True) != run_root
    ):
        raise Phase8BAuthorityError("Phase 8B run root is unsafe")
    inventory_path = run_root / _TRANSPORT_INVENTORY_RELATIVE
    inventory_raw = _read_bound_bytes(
        inventory_path,
        expected_sha256=expected_transport_inventory_sha256,
        expected_mode=_PUBLIC_MODE,
        label="Phase 8B transport inventory",
    )
    inventory = _strict_json_object(inventory_raw, label="Phase 8B transport inventory")
    if inventory_raw != _canonical_json_bytes(inventory):
        raise Phase8BAuthorityError("transport inventory is not canonical JSON")
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
        raise Phase8BAuthorityError("transport inventory fields drifted")
    if (
        inventory.get("schema_version") != _TRANSPORT_SCHEMA
        or inventory.get("bundle_version") != _BUNDLE_VERSION
        or inventory.get("excluded_from_inventory") != [_TRANSPORT_INVENTORY_RELATIVE]
    ):
        raise Phase8BAuthorityError("transport inventory identity drifted")
    payload_sha256 = _require_sha256(
        inventory.get("payload_manifest_sha256"), label="payload_manifest_sha256"
    )
    permit_sha256 = _require_sha256(inventory.get("permit_sha256"), label="permit_sha256")
    entries = _parse_file_entries(inventory.get("files"), label="transport files")
    if _PAYLOAD_MANIFEST_RELATIVE not in entries or _PERMIT_READY_RELATIVE not in entries:
        raise Phase8BAuthorityError("transport inventory omitted permit or payload manifest")
    if (
        entries[_PAYLOAD_MANIFEST_RELATIVE][0] != payload_sha256
        or entries[_PERMIT_READY_RELATIVE][0] != permit_sha256
        or entries[_PERMIT_READY_RELATIVE][2] != _PERMIT_READY_MODE
    ):
        raise Phase8BAuthorityError("transport hash layer drifted")
    for name, (digest, byte_count, mode) in entries.items():
        raw = _read_bound_bytes(
            run_root / Path(name),
            expected_sha256=digest,
            expected_mode=mode,
            label=f"transport file {name}",
        )
        if len(raw) != byte_count:
            raise Phase8BAuthorityError(f"transport byte count drifted: {name}")
    if inventory.get("transport_tree_sha256") != _file_tree_sha256(entries):
        raise Phase8BAuthorityError("transport file tree SHA256 drifted")
    directories = _parse_directory_modes(
        inventory.get("directories"), label="transport directories"
    )
    expected_directories = _directory_modes_for_files((*entries, _TRANSPORT_INVENTORY_RELATIVE))
    if directories != expected_directories:
        raise Phase8BAuthorityError("transport directory contract drifted")
    if inventory.get("directory_tree_sha256") != _directory_tree_sha256(directories):
        raise Phase8BAuthorityError("transport directory tree SHA256 drifted")

    actual_files: set[str] = set()
    actual_directories: set[str] = {"."}
    for path in run_root.rglob("*"):
        name = path.relative_to(run_root).as_posix()
        if path.is_symlink():
            raise Phase8BAuthorityError(f"transport tree contains a symlink: {name}")
        if path.is_file():
            actual_files.add(name)
        elif path.is_dir():
            actual_directories.add(name)
        else:
            raise Phase8BAuthorityError(f"transport tree contains a special file: {name}")
    if actual_files != {*entries, _TRANSPORT_INVENTORY_RELATIVE}:
        raise Phase8BAuthorityError("transport tree contains extra or missing files")
    if actual_directories != set(directories):
        raise Phase8BAuthorityError("transport tree contains extra or missing directories")

    manifest = _strict_json_object(
        (run_root / _PAYLOAD_MANIFEST_RELATIVE).read_bytes(),
        label="Phase 8B payload manifest",
    )
    identity = manifest.get("identity")
    if not isinstance(identity, dict):
        raise Phase8BAuthorityError("payload identity is unavailable")
    request_sha256 = _require_sha256(identity.get("request_sha256"), label="request_sha256")
    runner_sha256 = _require_sha256(
        identity.get("runner_source_sha256"), label="runner_source_sha256"
    )
    payload_entries = _validate_payload_manifest(
        run_root,
        expected_payload_manifest_sha256=payload_sha256,
        expected_request_sha256=request_sha256,
        expected_runner_source_sha256=runner_sha256,
        expected_source_relative_paths=expected_source_relative_paths,
    )
    if set(entries) != {*payload_entries, _PAYLOAD_MANIFEST_RELATIVE, _PERMIT_READY_RELATIVE}:
        raise Phase8BAuthorityError("transport and payload file sets disagree")
    return Phase8BBundleIdentity(
        transport_inventory_sha256=expected_transport_inventory_sha256,
        payload_manifest_sha256=payload_sha256,
        permit_sha256=permit_sha256,
        request_sha256=request_sha256,
        runner_source_sha256=runner_sha256,
    )


def _require_exact_output_path(output_root: Path, expected: Path, *, require_absent: bool) -> None:
    if not output_root.is_absolute() or output_root != expected:
        raise Phase8BAuthorityError("output root differs from the consumed permit")
    if (
        output_root.parent.is_symlink()
        or output_root.parent.resolve(strict=True) != output_root.parent
    ):
        raise Phase8BAuthorityError("output parent is not an exact real directory")
    output_exists = os.path.lexists(output_root)
    if require_absent and output_exists:
        raise Phase8BAuthorityError("fixed output root already exists; resume is prohibited")
    if output_exists:
        if not output_root.is_dir() or output_root.is_symlink():
            raise Phase8BAuthorityError("output root is not an exact real directory")
        if output_root.resolve(strict=True) != output_root:
            raise Phase8BAuthorityError("output root is not an exact real directory")


def _validate_exact_qxh_endpoint_pair(cation: _EndpointLike, neutral: _EndpointLike) -> None:
    """Recompute the exact QXH composition/electron closure from geometry."""

    cation_elements = tuple(atom.element for atom in cation.geometry.atoms)
    neutral_elements = tuple(atom.element for atom in neutral.geometry.atoms)
    if Counter(cation_elements) != Counter({"C": 7, "N": 6, "O": 4, "H": 5}):
        raise Phase8BAuthorityError("frozen cation element composition drifted")
    if Counter(neutral_elements) != Counter({"C": 7, "N": 6, "O": 4, "H": 4}):
        raise Phase8BAuthorityError("frozen neutral element composition drifted")
    cation_heavy = tuple(element for element in cation_elements if element != "H")
    neutral_heavy = tuple(element for element in neutral_elements if element != "H")
    if cation_heavy != neutral_heavy:
        raise Phase8BAuthorityError("frozen endpoint heavy-element ordering drifted")
    atomic_numbers = {"H": 1, "C": 6, "N": 7, "O": 8}
    cation_electrons = sum(atomic_numbers[element] for element in cation_elements) - cation.charge
    neutral_electrons = (
        sum(atomic_numbers[element] for element in neutral_elements) - neutral.charge
    )
    if (cation_electrons, neutral_electrons) != (
        FROZEN_ELECTRON_COUNT,
        FROZEN_ELECTRON_COUNT,
    ):
        raise Phase8BAuthorityError("frozen endpoint electron count did not recompute to 120")
    for elements in (cation_elements, neutral_elements):
        if (elements[3], elements[4], elements[5]) != ("N", "C", "N"):
            raise Phase8BAuthorityError("frozen N1/C2/N3 atom ordering drifted")


def _validate_endpoint_map(payload: dict[str, object]) -> None:
    expected = {
        "schema_version": "phase7.endpoint_atom_map.v1",
        "inchikey": FROZEN_INCHIKEY,
        "mapping_basis": {
            "cation": "validated_legacy_m2_cation_map",
            "neutral": "independent_graph_shared_five_membered_ring",
        },
        "cation": _QXH_LEGACY_MAP,
        "neutral": _QXH_LEGACY_MAP,
    }
    if payload != expected:
        raise Phase8BAuthorityError("endpoint atom map identity drifted")


def _validate_geometry_evidence(payload: dict[str, object]) -> None:
    if (
        payload.get("schema_version") != "phase7.geometry_validation.v1"
        or payload.get("validation_status") != "passed"
        or payload.get("expected_candidates") != 4
        or payload.get("validated_candidates") != 4
        or payload.get("quantum_chemistry_run") is not False
        or payload.get("hessian_computed") is not False
        or payload.get("replacement_candidate_used") is not False
    ):
        raise Phase8BAuthorityError("Phase 7 geometry validation identity drifted")
    endpoint_hashes = payload.get("endpoint_atom_map_sha256")
    if (
        not isinstance(endpoint_hashes, dict)
        or endpoint_hashes.get("QXHIEGFUWOLQIJ-UHFFFAOYSA-N_endpoint_atom_map.json")
        != FROZEN_INPUT_SHA256["endpoint_atom_map"]
    ):
        raise Phase8BAuthorityError("Phase 7 endpoint-map registration drifted")
    candidates = payload.get("candidate_results")
    if not isinstance(candidates, list):
        raise Phase8BAuthorityError("Phase 7 candidate evidence is unavailable")
    matches = [
        item
        for item in candidates
        if isinstance(item, dict) and item.get("inchikey") == FROZEN_INCHIKEY
    ]
    if len(matches) != 1:
        raise Phase8BAuthorityError("Phase 7 QXH candidate evidence is not unique")
    record = cast(dict[str, object], matches[0])
    checks = record.get("checks")
    files = record.get("files")
    if (
        record.get("status") != "passed"
        or record.get("geometry_quality") != "initial_force_field_geometry"
        or record.get("force_field_convergence") != "unavailable_legacy_m2"
        or not isinstance(checks, dict)
        or not isinstance(files, dict)
    ):
        raise Phase8BAuthorityError("Phase 7 QXH validation record drifted")
    required_checks: dict[str, object] = {
        "atom_counts": {"cation": 22, "neutral": 21},
        "formal_charges": {"cation": 1, "neutral": 0},
        "heavy_element_multiset": {"C": 7, "N": 6, "O": 4},
        "hydrogen_counts": {"cation": 5, "neutral": 4},
        "legacy_cation_map": _QXH_LEGACY_MAP,
        "neutral_graph_map": _QXH_LEGACY_MAP,
        "one_c2_proton_difference": True,
    }
    if any(checks.get(key) != value for key, value in required_checks.items()):
        raise Phase8BAuthorityError("Phase 7 QXH chemistry closure drifted")
    expected_files = {
        "QXHIEGFUWOLQIJ-UHFFFAOYSA-N_atom_map.json": FROZEN_INPUT_SHA256["legacy_atom_map"],
        "QXHIEGFUWOLQIJ-UHFFFAOYSA-N_cation.xyz": FROZEN_INPUT_SHA256["cation_xyz"],
        "QXHIEGFUWOLQIJ-UHFFFAOYSA-N_neutral.xyz": FROZEN_INPUT_SHA256["neutral_xyz"],
    }
    if files != expected_files:
        raise Phase8BAuthorityError("Phase 7 QXH input registration drifted")


def validate_exact_phase8b_authority(
    request: Phase8BRequestLike,
    consumed: ConsumedPhase8BPermit,
    *,
    output_root: Path,
    attempt_id: str,
    expected_source_relative_paths: Sequence[str],
    require_output_absent: bool = True,
) -> ExactPhase8BAuthority:
    """Cross-check a loaded request against the irreversible exact permit."""

    permit = consumed.permit
    if consumed.consumed_path != permit.consumed_path or (
        consumed.consumed_sha256 != permit.permit_sha256
    ):
        raise Phase8BAuthorityError("consumed permit identity is internally inconsistent")
    if request.schema_version != "nhc-two-endpoint-request-v1":
        raise Phase8BAuthorityError("request schema is not the frozen Phase 8B schema")
    if (
        request.request_id != FROZEN_REQUEST_ID
        or request.inchikey != FROZEN_INCHIKEY
        or request.execution_authorized is not True
        or request.timeout_seconds != FROZEN_RESOURCES["hard_wall_timeout_seconds"]
        or request.protocol_sha256 != FROZEN_PROTOCOL_SHA256
        or attempt_id != FROZEN_ATTEMPT_ID
    ):
        raise Phase8BAuthorityError("request identity or resource boundary drifted")
    if (
        request.request_sha256 != permit.request_sha256
        or request.runner_source_sha256 != permit.runner_source_sha256
        or request.request_path != permit.request_path
        or request.request_path.resolve(strict=True) != permit.request_path
    ):
        raise Phase8BAuthorityError("request path/hash/source differs from the consumed permit")
    _require_exact_output_path(
        output_root,
        permit.output_root,
        require_absent=require_output_absent,
    )
    _validate_payload_manifest(
        permit.run_root,
        expected_payload_manifest_sha256=permit.payload_manifest_sha256,
        expected_request_sha256=permit.request_sha256,
        expected_runner_source_sha256=permit.runner_source_sha256,
        expected_source_relative_paths=expected_source_relative_paths,
    )

    endpoint_expectations = (
        (request.cation, FROZEN_INPUT_SHA256["cation_xyz"], 1),
        (request.neutral, FROZEN_INPUT_SHA256["neutral_xyz"], 0),
    )
    for endpoint, expected_hash, expected_charge in endpoint_expectations:
        if (
            endpoint.xyz_sha256 != expected_hash
            or endpoint.charge != expected_charge
            or endpoint.multiplicity != 1
            or endpoint.electron_count != FROZEN_ELECTRON_COUNT
        ):
            raise Phase8BAuthorityError("frozen endpoint identity/electron count drifted")
    _validate_exact_qxh_endpoint_pair(request.cation, request.neutral)

    endpoint_map = _read_bound_json(
        permit.run_root / ENDPOINT_MAP_RELATIVE,
        expected_sha256=FROZEN_INPUT_SHA256["endpoint_atom_map"],
        label="Phase 7 endpoint atom map",
    )
    _validate_endpoint_map(endpoint_map)
    legacy_map = _read_bound_json(
        permit.run_root / LEGACY_MAP_RELATIVE,
        expected_sha256=FROZEN_INPUT_SHA256["legacy_atom_map"],
        label="Phase 7 legacy atom map",
    )
    if legacy_map != _QXH_LEGACY_MAP:
        raise Phase8BAuthorityError("legacy atom map identity drifted")
    geometry_validation = _read_bound_json(
        permit.run_root / GEOMETRY_VALIDATION_RELATIVE,
        expected_sha256=PHASE7_GEOMETRY_VALIDATION_SHA256,
        label="Phase 7 geometry validation",
    )
    _validate_geometry_evidence(geometry_validation)
    return ExactPhase8BAuthority(
        request_sha256=request.request_sha256,
        runner_source_sha256=request.runner_source_sha256,
        permit_sha256=permit.permit_sha256,
        payload_manifest_sha256=permit.payload_manifest_sha256,
        endpoint_atom_map_sha256=FROZEN_INPUT_SHA256["endpoint_atom_map"],
        legacy_atom_map_sha256=FROZEN_INPUT_SHA256["legacy_atom_map"],
        geometry_validation_sha256=PHASE7_GEOMETRY_VALIDATION_SHA256,
        electron_count=FROZEN_ELECTRON_COUNT,
        request_id=FROZEN_REQUEST_ID,
        inchikey=FROZEN_INCHIKEY,
        attempt_id=FROZEN_ATTEMPT_ID,
        project_root=permit.project_root.as_posix(),
        run_root=permit.run_root.as_posix(),
        request_path=permit.request_path.as_posix(),
        output_root=permit.output_root.as_posix(),
        resources_sha256=hashlib.sha256(_canonical_json_bytes(FROZEN_RESOURCES)).hexdigest(),
    )


__all__ = [
    "ENDPOINT_MAP_RELATIVE",
    "GEOMETRY_VALIDATION_RELATIVE",
    "LEGACY_MAP_RELATIVE",
    "PHASE7_GEOMETRY_VALIDATION_SHA256",
    "ExactPhase8BAuthority",
    "Phase8BAuthorityError",
    "Phase8BBundleIdentity",
    "validate_exact_phase8b_authority",
    "validate_phase8b_transport_bundle",
]
