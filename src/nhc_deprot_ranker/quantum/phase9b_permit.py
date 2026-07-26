"""Phase 9B one-shot private permit: render and consumed-load.

Mirrors the Phase 8B permit discipline — canonical JSON, strict parsing, byte
caps, exact key sets, hash closure, no-follow directory access, and the
one-shot rule that a consumed permit is valid only while the ready permit is
absent — but takes every candidate-specific value from the frozen
:class:`~nhc_deprot_ranker.quantum.phase9b_authority.CandidateProfile` instead
of module constants.

Phase 9B runs two routes under one request.  Each route is its own attempt with
its own permit under its own route root; the two permits can never be one
reused authorization.

The Route D (direct) permit must carry exactly the profile's frozen initial
geometry hashes.  The Route A (assisted) permit carries the AIMNet2-preoptimized
geometry hashes — unknowable before the preoptimization runs — and must bind the
profile's initial hashes alongside them as parent linkage, encoding the handoff
contract into the permit itself.

This module renders and loads permit *bytes and files*.  It grants nothing:
rendering happens only inside a user-authorized execution transaction, and the
execution gates live elsewhere.  ``phase8b_permit.py`` is untouched history.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Protocol, cast

from nhc_deprot_ranker.quantum.phase9b_authority import (
    PHASE9B_CANDIDATE,
    CandidateProfile,
    Phase9BAuthorityError,
    validate_endpoint_pair,
    validate_profile_self_consistency,
)

PERMIT_SCHEMA_VERSION: Final = "nhc-phase9b-private-permit-v1"
REQUEST_ID: Final = "phase9b-lbnp-paired-smoke-v001"
REMOTE_ROOT_RELATIVE: Final = "data/runs/nhc_deprot_ranker_phase9b_paired_smoke_v001"

ROUTE_DIRECT: Final = "direct"
ROUTE_ASSISTED: Final = "assisted"
ROUTE_ATTEMPT_IDS: Final[dict[str, str]] = {
    ROUTE_DIRECT: "attempt-phase9b-lbnp-direct-v001",
    ROUTE_ASSISTED: "attempt-phase9b-lbnp-assisted-v001",
}

REQUEST_RELATIVE: Final = "input/request.json"
OUTPUT_RELATIVE: Final = "runtime/output"
READY_RELATIVE: Final = "private/permit.ready.json"
CONSUMED_RELATIVE: Final = "private/permit.consumed.json"

_MAX_PERMIT_BYTES: Final = 64 * 1024
_CONSUMED_MODE: Final = 0o400


class Phase9BPermitError(RuntimeError):
    """The Phase 9B permit could not prove its exact one-shot authority."""


class Phase9BPermitValidationError(Phase9BPermitError):
    """Permit bytes, layout, or identity failed strict validation."""


@dataclass(frozen=True, slots=True)
class Phase9BPermit:
    """A fully validated per-route authorization, before or after consumption."""

    route: str
    attempt_id: str
    cation_xyz_sha256: str
    neutral_xyz_sha256: str
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


@dataclass(frozen=True, slots=True)
class ConsumedPhase9BPermit:
    """Proof that one route's ready permit crossed its irreversible point."""

    permit: Phase9BPermit
    consumed_path: Path
    consumed_sha256: str


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
        raise Phase9BPermitValidationError(f"{label} must be a lowercase SHA256")
    return value


def _require_route(value: object) -> str:
    if not isinstance(value, str) or value not in ROUTE_ATTEMPT_IDS:
        raise Phase9BPermitValidationError(f"unknown Phase 9B route: {value!r}")
    return value


def _normalized_absolute_path(value: object, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise Phase9BPermitValidationError(f"{label} is not a safe absolute path")
    path = PurePosixPath(value)
    if not path.is_absolute() or path.as_posix() != value:
        raise Phase9BPermitValidationError(f"{label} is not a normalized absolute path")
    if any(part in {".", ".."} for part in path.parts):
        raise Phase9BPermitValidationError(f"{label} must not contain dot segments")
    return path


def _route_paths(project_root: PurePosixPath, route: str) -> dict[str, str]:
    route_root = project_root / REMOTE_ROOT_RELATIVE / route
    return {
        "project_root": project_root.as_posix(),
        "run_root": route_root.as_posix(),
        "request_path": (route_root / REQUEST_RELATIVE).as_posix(),
        "output_root": (route_root / OUTPUT_RELATIVE).as_posix(),
        "ready_path": (route_root / READY_RELATIVE).as_posix(),
        "consumed_path": (route_root / CONSUMED_RELATIVE).as_posix(),
    }


def render_phase9b_permit(
    *,
    profile: CandidateProfile = PHASE9B_CANDIDATE,
    route: str,
    project_root: str,
    request_sha256: str,
    runner_source_sha256: str,
    payload_manifest_sha256: str,
    cation_xyz_sha256: str,
    neutral_xyz_sha256: str,
    resources: dict[str, object],
) -> bytes:
    """Render deterministic private permit bytes for exactly one route."""

    try:
        validate_profile_self_consistency(profile)
    except Phase9BAuthorityError as exc:
        raise Phase9BPermitValidationError(f"candidate profile is invalid: {exc}") from exc
    chosen_route = _require_route(route)
    root = _normalized_absolute_path(project_root, label="project_root")
    request_hash = _require_sha256(request_sha256, label="request_sha256")
    source_hash = _require_sha256(runner_source_sha256, label="runner_source_sha256")
    payload_hash = _require_sha256(payload_manifest_sha256, label="payload_manifest_sha256")
    cation_hash = _require_sha256(cation_xyz_sha256, label="cation_xyz_sha256")
    neutral_hash = _require_sha256(neutral_xyz_sha256, label="neutral_xyz_sha256")

    if chosen_route == ROUTE_DIRECT:
        if cation_hash != profile.cation_xyz_sha256 or neutral_hash != profile.neutral_xyz_sha256:
            raise Phase9BPermitValidationError(
                "direct-route inputs must be exactly the profile's frozen initial geometry"
            )
    else:
        if cation_hash == profile.cation_xyz_sha256 and neutral_hash == profile.neutral_xyz_sha256:
            raise Phase9BPermitValidationError(
                "assisted-route inputs must be preoptimized geometry, not the initial geometry"
            )

    if not resources or any(type(key) is not str or not key for key in resources):
        raise Phase9BPermitValidationError("resources must be a non-empty string-keyed mapping")

    input_sha256: dict[str, str] = {
        "cation_xyz": cation_hash,
        "neutral_xyz": neutral_hash,
        "initial_cation_xyz": profile.cation_xyz_sha256,
        "initial_neutral_xyz": profile.neutral_xyz_sha256,
    }
    permit = {
        "schema_version": PERMIT_SCHEMA_VERSION,
        "authorization": {
            "one_shot": True,
            "server_write_authorized": True,
            "quantum_execution_authorized": True,
            "candidate_replacement_authorized": False,
            "second_attempt_authorized": False,
            "resume_authorized": False,
            "ensemble_uncertainty_available": False,
        },
        "identity": {
            "route": chosen_route,
            "inchikey": profile.inchikey,
            "request_id": REQUEST_ID,
            "attempt_id": ROUTE_ATTEMPT_IDS[chosen_route],
            "endpoint_order": ["cation", "neutral"],
            "electron_count": profile.electron_count,
            "request_sha256": request_hash,
            "runner_source_sha256": source_hash,
            "payload_manifest_sha256": payload_hash,
            "input_sha256": input_sha256,
        },
        "resources": resources,
        "paths": _route_paths(root, chosen_route),
    }
    return _canonical_json_bytes(permit)


def _strict_object(raw: bytes, *, label: str) -> dict[str, object]:
    if not raw or len(raw) > _MAX_PERMIT_BYTES:
        raise Phase9BPermitValidationError(f"{label} byte size is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase9BPermitValidationError(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                Phase9BPermitValidationError(f"{label} contains non-finite number: {value}")
            ),
        )
    except Phase9BPermitValidationError:
        raise
    except (UnicodeDecodeError, ValueError) as exc:
        raise Phase9BPermitValidationError(f"{label} is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise Phase9BPermitValidationError(f"{label} must be one JSON object")
    return cast(dict[str, object], decoded)


def _section(payload: dict[str, object], key: str, *, expected_keys: set[str]) -> dict[str, object]:
    section = payload.get(key)
    if not isinstance(section, dict) or set(section) != expected_keys:
        raise Phase9BPermitValidationError(f"permit section drifted: {key}")
    return cast(dict[str, object], section)


def parse_phase9b_permit(
    raw: bytes, *, profile: CandidateProfile = PHASE9B_CANDIDATE
) -> Phase9BPermit:
    """Strictly parse permit bytes back into a validated identity."""

    try:
        validate_profile_self_consistency(profile)
    except Phase9BAuthorityError as exc:
        raise Phase9BPermitValidationError(f"candidate profile is invalid: {exc}") from exc
    payload = _strict_object(raw, label="phase9b permit")
    if set(payload) != {"schema_version", "authorization", "identity", "resources", "paths"}:
        raise Phase9BPermitValidationError("permit top-level keys drifted")
    if payload["schema_version"] != PERMIT_SCHEMA_VERSION:
        raise Phase9BPermitValidationError("permit schema version drifted")

    authorization = _section(
        payload,
        "authorization",
        expected_keys={
            "one_shot",
            "server_write_authorized",
            "quantum_execution_authorized",
            "candidate_replacement_authorized",
            "second_attempt_authorized",
            "resume_authorized",
            "ensemble_uncertainty_available",
        },
    )
    if (
        authorization["one_shot"] is not True
        or authorization["candidate_replacement_authorized"] is not False
        or authorization["second_attempt_authorized"] is not False
        or authorization["resume_authorized"] is not False
        or authorization["ensemble_uncertainty_available"] is not False
    ):
        raise Phase9BPermitValidationError("permit authorization booleans drifted")

    identity = _section(
        payload,
        "identity",
        expected_keys={
            "route",
            "inchikey",
            "request_id",
            "attempt_id",
            "endpoint_order",
            "electron_count",
            "request_sha256",
            "runner_source_sha256",
            "payload_manifest_sha256",
            "input_sha256",
        },
    )
    route = _require_route(identity["route"])
    if identity["inchikey"] != profile.inchikey:
        raise Phase9BPermitValidationError("permit candidate drifted")
    if identity["request_id"] != REQUEST_ID:
        raise Phase9BPermitValidationError("permit request id drifted")
    if identity["attempt_id"] != ROUTE_ATTEMPT_IDS[route]:
        raise Phase9BPermitValidationError("permit attempt id does not match its route")
    if identity["endpoint_order"] != ["cation", "neutral"]:
        raise Phase9BPermitValidationError("permit endpoint order drifted")
    if identity["electron_count"] != profile.electron_count:
        raise Phase9BPermitValidationError("permit electron count drifted")

    inputs = identity["input_sha256"]
    if not isinstance(inputs, dict) or set(inputs) != {
        "cation_xyz",
        "neutral_xyz",
        "initial_cation_xyz",
        "initial_neutral_xyz",
    }:
        raise Phase9BPermitValidationError("permit input hash set drifted")
    if (
        inputs["initial_cation_xyz"] != profile.cation_xyz_sha256
        or inputs["initial_neutral_xyz"] != profile.neutral_xyz_sha256
    ):
        raise Phase9BPermitValidationError("permit initial-geometry linkage drifted")
    cation_hash = _require_sha256(inputs["cation_xyz"], label="permit cation_xyz")
    neutral_hash = _require_sha256(inputs["neutral_xyz"], label="permit neutral_xyz")
    if route == ROUTE_DIRECT and (
        cation_hash != profile.cation_xyz_sha256 or neutral_hash != profile.neutral_xyz_sha256
    ):
        raise Phase9BPermitValidationError("direct-route permit inputs drifted from the profile")
    if route == ROUTE_ASSISTED and (
        cation_hash == profile.cation_xyz_sha256 and neutral_hash == profile.neutral_xyz_sha256
    ):
        raise Phase9BPermitValidationError("assisted-route permit inputs are not preoptimized")

    paths = _section(
        payload,
        "paths",
        expected_keys={
            "project_root",
            "run_root",
            "request_path",
            "output_root",
            "ready_path",
            "consumed_path",
        },
    )
    project_root = _normalized_absolute_path(paths["project_root"], label="project_root")
    expected_paths = _route_paths(project_root, route)
    if {key: paths[key] for key in expected_paths} != expected_paths:
        raise Phase9BPermitValidationError("permit path layout drifted from the fixed route root")

    resources = payload.get("resources")
    if not isinstance(resources, dict) or not resources:
        raise Phase9BPermitValidationError("permit resources drifted")

    return Phase9BPermit(
        route=route,
        attempt_id=ROUTE_ATTEMPT_IDS[route],
        cation_xyz_sha256=cation_hash,
        neutral_xyz_sha256=neutral_hash,
        request_sha256=_require_sha256(identity["request_sha256"], label="request_sha256"),
        runner_source_sha256=_require_sha256(
            identity["runner_source_sha256"], label="runner_source_sha256"
        ),
        payload_manifest_sha256=_require_sha256(
            identity["payload_manifest_sha256"], label="payload_manifest_sha256"
        ),
        project_root=Path(project_root.as_posix()),
        run_root=Path(expected_paths["run_root"]),
        request_path=Path(expected_paths["request_path"]),
        output_root=Path(expected_paths["output_root"]),
        ready_path=Path(expected_paths["ready_path"]),
        consumed_path=Path(expected_paths["consumed_path"]),
        raw_bytes=raw,
        permit_sha256=hashlib.sha256(raw).hexdigest(),
    )


def load_consumed_phase9b_permit(
    consumed_path: Path,
    *,
    profile: CandidateProfile = PHASE9B_CANDIDATE,
    expected_route: str,
    expected_permit_sha256: str,
    expected_request_sha256: str,
    expected_runner_source_sha256: str,
    expected_payload_manifest_sha256: str,
) -> ConsumedPhase9BPermit:
    """Read and revalidate one route's irreversibly consumed permit.

    Read-only and repeatable.  The one-shot proof is structural: the consumed
    file must exist with its exact identity while the ready permit is absent.
    """

    route = _require_route(expected_route)
    if not consumed_path.is_absolute() or consumed_path.name != Path(CONSUMED_RELATIVE).name:
        raise Phase9BPermitValidationError("consumed_path must be the exact absolute permit path")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise Phase9BPermitValidationError("platform lacks required no-follow directory flags")

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        directory_fd = os.open(consumed_path.parent, directory_flags)
    except OSError as exc:
        raise Phase9BPermitValidationError("permit directory cannot be opened safely") from exc
    try:
        ready_name = Path(READY_RELATIVE).name
        try:
            os.lstat(ready_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        else:
            raise Phase9BPermitValidationError(
                "ready permit reappeared beside the consumed permit; one-shot proof failed"
            )
        try:
            consumed_fd = os.open(
                consumed_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd
            )
        except OSError as exc:
            raise Phase9BPermitValidationError("consumed permit cannot be opened safely") from exc
        try:
            file_stat = os.fstat(consumed_fd)
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_nlink != 1
                or stat.S_IMODE(file_stat.st_mode) != _CONSUMED_MODE
                or file_stat.st_size <= 0
                or file_stat.st_size > _MAX_PERMIT_BYTES
            ):
                raise Phase9BPermitValidationError("consumed permit file identity drifted")
            raw = os.read(consumed_fd, _MAX_PERMIT_BYTES + 1)
        finally:
            os.close(consumed_fd)
    finally:
        os.close(directory_fd)

    if len(raw) > _MAX_PERMIT_BYTES:
        raise Phase9BPermitValidationError("consumed permit exceeded its byte cap")
    consumed_sha256 = hashlib.sha256(raw).hexdigest()
    if consumed_sha256 != _require_sha256(expected_permit_sha256, label="expected_permit_sha256"):
        raise Phase9BPermitValidationError("consumed permit hash differs from the expected permit")

    permit = parse_phase9b_permit(raw, profile=profile)
    if permit.route != route:
        raise Phase9BPermitValidationError("consumed permit route differs from the expected route")
    if permit.consumed_path != consumed_path:
        raise Phase9BPermitValidationError("consumed permit path differs from its own layout")
    if permit.request_sha256 != _require_sha256(
        expected_request_sha256, label="expected_request_sha256"
    ):
        raise Phase9BPermitValidationError("consumed permit request hash drifted")
    if permit.runner_source_sha256 != _require_sha256(
        expected_runner_source_sha256, label="expected_runner_source_sha256"
    ):
        raise Phase9BPermitValidationError("consumed permit runner source hash drifted")
    if permit.payload_manifest_sha256 != _require_sha256(
        expected_payload_manifest_sha256, label="expected_payload_manifest_sha256"
    ):
        raise Phase9BPermitValidationError("consumed permit payload manifest hash drifted")
    return ConsumedPhase9BPermit(
        permit=permit,
        consumed_path=consumed_path,
        consumed_sha256=consumed_sha256,
    )


class _AuthorityAtomLike(Protocol):
    @property
    def element(self) -> str: ...


class _AuthorityGeometryLike(Protocol):
    @property
    def atoms(self) -> Sequence[_AuthorityAtomLike]: ...


class _AuthorityEndpointLike(Protocol):
    @property
    def geometry(self) -> _AuthorityGeometryLike: ...

    @property
    def charge(self) -> int: ...

    @property
    def multiplicity(self) -> int: ...

    @property
    def xyz_sha256(self) -> str: ...


class Phase9BRequestLike(Protocol):
    """The request fields the exact authority cross-checks."""

    @property
    def request_sha256(self) -> str: ...

    @property
    def runner_source_sha256(self) -> str: ...

    @property
    def request_id(self) -> str: ...

    @property
    def inchikey(self) -> str: ...

    @property
    def request_path(self) -> Path: ...

    @property
    def cation(self) -> _AuthorityEndpointLike: ...

    @property
    def neutral(self) -> _AuthorityEndpointLike: ...


@dataclass(frozen=True, slots=True)
class Phase9BExactAuthority:
    """Portable identity proven before any Phase 9B worker may run one route."""

    route: str
    request_sha256: str
    runner_source_sha256: str
    permit_sha256: str
    payload_manifest_sha256: str
    cation_xyz_sha256: str
    neutral_xyz_sha256: str
    legacy_atom_map_sha256: str
    endpoint_atom_map_sha256: str
    geometry_validation_sha256: str
    electron_count: int
    request_id: str
    inchikey: str
    attempt_id: str
    project_root: str
    run_root: str
    request_path: str
    output_root: str


def validate_exact_phase9b_authority(
    request: Phase9BRequestLike,
    consumed: ConsumedPhase9BPermit,
    *,
    output_root: Path,
    attempt_id: str,
    profile: CandidateProfile = PHASE9B_CANDIDATE,
    require_output_absent: bool = True,
) -> Phase9BExactAuthority:
    """Cross-check a loaded request against one route's consumed exact permit."""

    if not isinstance(consumed, ConsumedPhase9BPermit):
        raise Phase9BPermitValidationError("a consumed Phase 9B permit is required")
    try:
        validate_profile_self_consistency(profile)
    except Phase9BAuthorityError as exc:
        raise Phase9BPermitValidationError(f"candidate profile is invalid: {exc}") from exc
    permit = consumed.permit
    if consumed.consumed_path != permit.consumed_path:
        raise Phase9BPermitValidationError("consumed path escaped the permit layout")
    if consumed.consumed_sha256 != permit.permit_sha256:
        raise Phase9BPermitValidationError("consumed permit hash is not linearized")
    if attempt_id != permit.attempt_id or attempt_id != ROUTE_ATTEMPT_IDS[permit.route]:
        raise Phase9BPermitValidationError("attempt identity disagrees with the consumed permit")
    if request.request_id != REQUEST_ID:
        raise Phase9BPermitValidationError("request id disagrees with the Phase 9B chain")
    if request.inchikey != profile.inchikey:
        raise Phase9BPermitValidationError("request candidate disagrees with the profile")
    if request.request_sha256 != permit.request_sha256:
        raise Phase9BPermitValidationError("request hash disagrees with the consumed permit")
    if request.runner_source_sha256 != permit.runner_source_sha256:
        raise Phase9BPermitValidationError("runner source hash disagrees with the permit")
    if request.request_path != permit.request_path:
        raise Phase9BPermitValidationError("request path disagrees with the permit layout")
    if output_root != permit.output_root:
        raise Phase9BPermitValidationError("output root disagrees with the permit layout")
    if (
        request.cation.xyz_sha256 != permit.cation_xyz_sha256
        or request.neutral.xyz_sha256 != permit.neutral_xyz_sha256
    ):
        raise Phase9BPermitValidationError("request geometry disagrees with the permit inputs")
    if require_output_absent and os.path.lexists(output_root):
        raise Phase9BPermitValidationError("output root already exists; resume is prohibited")
    try:
        validate_endpoint_pair(request.cation, request.neutral, profile=profile)
    except Phase9BAuthorityError as exc:
        raise Phase9BPermitValidationError(f"endpoint validation failed: {exc}") from exc
    return Phase9BExactAuthority(
        route=permit.route,
        request_sha256=permit.request_sha256,
        runner_source_sha256=permit.runner_source_sha256,
        permit_sha256=permit.permit_sha256,
        payload_manifest_sha256=permit.payload_manifest_sha256,
        cation_xyz_sha256=permit.cation_xyz_sha256,
        neutral_xyz_sha256=permit.neutral_xyz_sha256,
        legacy_atom_map_sha256=profile.legacy_atom_map_sha256,
        endpoint_atom_map_sha256=profile.endpoint_atom_map_sha256,
        geometry_validation_sha256=profile.geometry_validation_sha256,
        electron_count=profile.electron_count,
        request_id=REQUEST_ID,
        inchikey=profile.inchikey,
        attempt_id=permit.attempt_id,
        project_root=permit.project_root.as_posix(),
        run_root=permit.run_root.as_posix(),
        request_path=permit.request_path.as_posix(),
        output_root=permit.output_root.as_posix(),
    )


__all__ = [
    "CONSUMED_RELATIVE",
    "PERMIT_SCHEMA_VERSION",
    "READY_RELATIVE",
    "REMOTE_ROOT_RELATIVE",
    "REQUEST_ID",
    "ROUTE_ASSISTED",
    "ROUTE_ATTEMPT_IDS",
    "ROUTE_DIRECT",
    "ConsumedPhase9BPermit",
    "Phase9BExactAuthority",
    "Phase9BPermit",
    "Phase9BPermitError",
    "Phase9BPermitValidationError",
    "Phase9BRequestLike",
    "load_consumed_phase9b_permit",
    "parse_phase9b_permit",
    "render_phase9b_permit",
    "validate_exact_phase9b_authority",
]
