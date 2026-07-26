"""Phase 9B request and payload-manifest builder.

Builds the two route requests and their payload manifests as deterministic bytes.
It does not touch a server, does not render a permit, and does not consume
anything: permit rendering belongs inside the authorized execution transaction,
because the Route A permit must bind AIMNet2-preoptimized geometry hashes that do
not exist until the preoptimization has run.

Route D and Route A must be byte-identical apart from their endpoint geometry
hashes and their attempt identity.  Any other difference makes the paired
comparison uninterpretable, so this module derives every shared field from one
place and a regression diffs the two payloads.

No chemistry import, no compute, no label.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from nhc_deprot_ranker.quantum.phase9b_authority import (
    PHASE9B_CANDIDATE,
    CandidateProfile,
    Phase9BAuthorityError,
    validate_profile_self_consistency,
)
from nhc_deprot_ranker.quantum.phase9b_handoff import (
    AIMNET2_WEIGHT_BYTES,
    AIMNET2_WEIGHT_FILENAME,
    AIMNET2_WEIGHT_SHA256,
    aimnet2_optimizer_protocol_sha256,
    aimnet2_structural_gates_sha256,
    handoff_contract_sha256,
    preoptimization_stage_sha256,
)
from nhc_deprot_ranker.quantum.phase9b_permit import (
    REQUEST_ID,
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
)
from nhc_deprot_ranker.quantum.phase9b_resources import (
    PHASE9B_RESOURCES,
    phase9b_resources_sha256,
)
from nhc_deprot_ranker.quantum.two_endpoint import REQUEST_SCHEMA_VERSION_V2

# Real bundle materialization is a separate authorization.  Source-level gate.
EXECUTION_AUTHORIZED: Final[bool] = False

# v2: single-transaction Route A.  Both routes register the frozen Phase 7
# initial geometry; the assisted route additionally registers its in-route
# AIMNet2 stage identity.
PAYLOAD_SCHEMA_VERSION: Final = "phase9b.payload_manifest.v2"

CATION_XYZ_RELATIVE: Final = "xyz/cation.xyz"
NEUTRAL_XYZ_RELATIVE: Final = "xyz/neutral.xyz"
REQUEST_RELATIVE: Final = "input/request.json"
PAYLOAD_MANIFEST_RELATIVE: Final = "payload_manifest.json"


class Phase9BBundleError(RuntimeError):
    """The Phase 9B bundle could not prove its closed, route-parity scope."""


class Phase9BBundleNotAuthorizedError(Phase9BBundleError):
    """Materialization was attempted while the source gate is closed."""


@dataclass(frozen=True, slots=True)
class RouteRequest:
    """One route's canonical request bytes and identity."""

    route: str
    attempt_id: str
    request_bytes: bytes
    request_sha256: str
    cation_xyz_sha256: str
    neutral_xyz_sha256: str


@dataclass(frozen=True, slots=True)
class RoutePayload:
    """One route's request plus its payload manifest."""

    request: RouteRequest
    manifest_bytes: bytes
    manifest_sha256: str


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
        raise Phase9BBundleError(f"{label} must be a lowercase SHA256")
    return value


def _require_route(value: object) -> str:
    if not isinstance(value, str) or value not in ROUTE_ATTEMPT_IDS:
        raise Phase9BBundleError(f"unknown Phase 9B route: {value!r}")
    return value


def _resources_payload() -> dict[str, object]:
    """Plain JSON view of the frozen budget, matching what its digest covers."""

    def normalize(value: object) -> object:
        if isinstance(value, Mapping):
            return {str(k): normalize(v) for k, v in value.items()}
        if isinstance(value, tuple | list):
            return [normalize(v) for v in value]
        return value

    normalized = normalize(PHASE9B_RESOURCES)
    if not isinstance(normalized, dict):  # pragma: no cover - structural guard
        raise Phase9BBundleError("frozen resources must normalize to one JSON object")
    return normalized


def _preoptimization_stage(route: str) -> dict[str, object]:
    """The AIMNet2 stage identity, from the closure module that owns it."""

    if route == ROUTE_DIRECT:
        return {"stage": "none", "aimnet2_authorized": False}
    return {
        "stage": "aimnet2",
        "aimnet2_authorized": True,
        "runs_inside_route": True,
        "external_preparation_authorized": False,
        "weight_filename": AIMNET2_WEIGHT_FILENAME,
        "weight_sha256": AIMNET2_WEIGHT_SHA256,
        "weight_bytes": AIMNET2_WEIGHT_BYTES,
        "optimizer_protocol_sha256": aimnet2_optimizer_protocol_sha256(),
        "structural_gates_sha256": aimnet2_structural_gates_sha256(),
        "handoff_contract_sha256": handoff_contract_sha256(),
        "stage_sha256": preoptimization_stage_sha256(),
    }


def build_route_request(
    *,
    route: str,
    runner_source_sha256: str,
    protocol: Mapping[str, object],
    cation_xyz_sha256: str,
    neutral_xyz_sha256: str,
    profile: CandidateProfile = PHASE9B_CANDIDATE,
) -> RouteRequest:
    """Build one route's canonical request bytes."""

    try:
        validate_profile_self_consistency(profile)
    except Phase9BAuthorityError as exc:
        raise Phase9BBundleError(f"candidate profile is invalid: {exc}") from exc

    chosen = _require_route(route)
    source_hash = _require_sha256(runner_source_sha256, label="runner_source_sha256")
    cation_hash = _require_sha256(cation_xyz_sha256, label="cation_xyz_sha256")
    neutral_hash = _require_sha256(neutral_xyz_sha256, label="neutral_xyz_sha256")
    if cation_hash == neutral_hash:
        raise Phase9BBundleError("the two endpoints cannot share one geometry hash")

    # Both routes begin from the identical frozen Phase 7 initial structure.  The
    # assisted route's preoptimized geometry is produced inside the route, so it
    # is never a build-time input and never a permit binding.
    if cation_hash != profile.cation_xyz_sha256 or neutral_hash != profile.neutral_xyz_sha256:
        raise Phase9BBundleError(
            "both routes must start from the profile's frozen initial geometry"
        )

    if not protocol:
        raise Phase9BBundleError("request protocol must not be empty")

    payload: dict[str, object] = {
        "schema_version": REQUEST_SCHEMA_VERSION_V2,
        "request_id": REQUEST_ID,
        "inchikey": profile.inchikey,
        "execution_authorized": True,
        "timeout_seconds": PHASE9B_RESOURCES["hard_wall_timeout_seconds"],
        "runner_source_sha256": source_hash,
        "protocol": dict(protocol),
        "preoptimization": _preoptimization_stage(chosen),
        "endpoints": {
            "cation": {
                "xyz_path": CATION_XYZ_RELATIVE,
                "xyz_sha256": cation_hash,
                "charge": 1,
                "multiplicity": 1,
            },
            "neutral": {
                "xyz_path": NEUTRAL_XYZ_RELATIVE,
                "xyz_sha256": neutral_hash,
                "charge": 0,
                "multiplicity": 1,
            },
        },
    }
    raw = _canonical_json_bytes(payload)
    return RouteRequest(
        route=chosen,
        attempt_id=ROUTE_ATTEMPT_IDS[chosen],
        request_bytes=raw,
        request_sha256=hashlib.sha256(raw).hexdigest(),
        cation_xyz_sha256=cation_hash,
        neutral_xyz_sha256=neutral_hash,
    )


def build_route_payload(
    request: RouteRequest, *, profile: CandidateProfile = PHASE9B_CANDIDATE
) -> RoutePayload:
    """Wrap one route's request in its payload manifest.

    The manifest deliberately excludes the permit: a manifest that covered its own
    authorization could not be built before the permit exists, and the permit binds
    the manifest hash.
    """

    if not isinstance(request, RouteRequest):
        raise Phase9BBundleError("a built RouteRequest is required")
    manifest: dict[str, object] = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "route": request.route,
        "request_id": REQUEST_ID,
        "attempt_id": request.attempt_id,
        "inchikey": profile.inchikey,
        "electron_count": profile.electron_count,
        "endpoint_order": ["cation", "neutral"],
        "files": {
            REQUEST_RELATIVE: request.request_sha256,
            CATION_XYZ_RELATIVE: request.cation_xyz_sha256,
            NEUTRAL_XYZ_RELATIVE: request.neutral_xyz_sha256,
        },
        "preoptimization": _preoptimization_stage(request.route),
        "provenance": {
            "initial_cation_xyz_sha256": profile.cation_xyz_sha256,
            "initial_neutral_xyz_sha256": profile.neutral_xyz_sha256,
            "legacy_atom_map_sha256": profile.legacy_atom_map_sha256,
            "endpoint_atom_map_sha256": profile.endpoint_atom_map_sha256,
            "geometry_validation_sha256": profile.geometry_validation_sha256,
        },
        "resources": _resources_payload(),
        "resources_sha256": phase9b_resources_sha256(),
        "excludes_permit": True,
        "hessian_computed": False,
        "label_produced": False,
        "ensemble_members": 1,
        "ensemble_uncertainty_available": False,
    }
    raw = _canonical_json_bytes(manifest)
    return RoutePayload(
        request=request,
        manifest_bytes=raw,
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
    )


def validate_route_parity(direct: RoutePayload, assisted: RoutePayload) -> None:
    """Both routes must differ only by the preoptimization stage and attempt.

    Under the single-transaction design the two requests now share their geometry
    as well: both start from the identical frozen Phase 7 initial structure, and
    the AIMNet2 stage is the *only* experimental variable. Anything else that
    differs makes a measured speedup uninterpretable, so it is rejected while the
    payloads are still local bytes rather than discovered after two attempts ran.
    """

    if direct.request.route != ROUTE_DIRECT or assisted.request.route != ROUTE_ASSISTED:
        raise Phase9BBundleError("route labels are not one direct and one assisted")
    if direct.request.attempt_id == assisted.request.attempt_id:
        raise Phase9BBundleError("the two routes must carry distinct attempt identities")
    if direct.request.request_sha256 == assisted.request.request_sha256:
        raise Phase9BBundleError("the two routes must be distinct requests")

    # The starting geometry is now shared, and that is the point.
    if direct.request.cation_xyz_sha256 != assisted.request.cation_xyz_sha256:
        raise Phase9BBundleError("the two routes must share the frozen initial cation geometry")
    if direct.request.neutral_xyz_sha256 != assisted.request.neutral_xyz_sha256:
        raise Phase9BBundleError("the two routes must share the frozen initial neutral geometry")

    # ``preoptimization`` is the experimental variable itself; every other
    # top-level field must be identical.
    variable = {"preoptimization"}
    left = json.loads(direct.request.request_bytes)
    right = json.loads(assisted.request.request_bytes)
    for key in sorted(set(left) | set(right)):
        if key in {"endpoints", *variable}:
            continue
        if left.get(key) != right.get(key):
            raise Phase9BBundleError(f"route requests differ outside the stage: {key}")
    if left["preoptimization"] == right["preoptimization"]:
        raise Phase9BBundleError("the two routes must differ by their preoptimization stage")
    if left["preoptimization"].get("stage") != "none":
        raise Phase9BBundleError("the direct route must declare no preoptimization stage")
    if right["preoptimization"].get("stage") != "aimnet2":
        raise Phase9BBundleError("the assisted route must declare the AIMNet2 stage")
    for endpoint in ("cation", "neutral"):
        a, b = left["endpoints"][endpoint], right["endpoints"][endpoint]
        for field in sorted(set(a) | set(b)):
            if a.get(field) != b.get(field):
                raise Phase9BBundleError(
                    f"route endpoint {endpoint} differs outside the stage: {field}"
                )


def materialize_bundle(*_args: object, **_kwargs: object) -> None:
    """Writing a real bundle is a separate authorization and stays closed."""

    if EXECUTION_AUTHORIZED is not True:
        raise Phase9BBundleNotAuthorizedError("Phase 9B bundle materialization is not authorized")
    raise Phase9BBundleNotAuthorizedError("no bundle materialization path exists yet")


__all__ = [
    "CATION_XYZ_RELATIVE",
    "EXECUTION_AUTHORIZED",
    "NEUTRAL_XYZ_RELATIVE",
    "PAYLOAD_MANIFEST_RELATIVE",
    "PAYLOAD_SCHEMA_VERSION",
    "REQUEST_RELATIVE",
    "Phase9BBundleError",
    "Phase9BBundleNotAuthorizedError",
    "RoutePayload",
    "RouteRequest",
    "build_route_payload",
    "build_route_request",
    "materialize_bundle",
    "validate_route_parity",
]
