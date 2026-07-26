"""Phase 9B exact authority regressions. No chemistry, no server, no compute."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import pytest

from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_permit import (
    REQUEST_ID,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
    ConsumedPhase9BPermit,
    Phase9BPermitValidationError,
    parse_phase9b_permit,
    render_phase9b_permit,
    validate_exact_phase9b_authority,
)
from nhc_deprot_ranker.quantum.phase9b_resources import PHASE9B_RESOURCES
from nhc_deprot_ranker.quantum.two_endpoint import (
    LOCKED_PROTOCOL_SHA256,
    REQUEST_SCHEMA_VERSION,
)

_FROZEN_TIMEOUT: int = int(cast(int, PHASE9B_RESOURCES["hard_wall_timeout_seconds"]))

_REQ = "1" * 64
_SRC = "2" * 64
_PAY = "3" * 64


@dataclass(frozen=True)
class _Atom:
    element: str


@dataclass(frozen=True)
class _Geometry:
    atoms: tuple[_Atom, ...]


@dataclass(frozen=True)
class _Endpoint:
    geometry: _Geometry
    charge: int
    multiplicity: int
    xyz_sha256: str


@dataclass(frozen=True)
class _Request:
    schema_version: str
    execution_authorized: bool
    protocol_sha256: str
    timeout_seconds: int
    request_sha256: str
    runner_source_sha256: str
    request_id: str
    inchikey: str
    request_path: Path
    cation: _Endpoint
    neutral: _Endpoint


def _elements(hydrogens: int) -> tuple[str, ...]:
    heavy = ["C"] * 8 + ["N"] + ["F"] * 5 + ["C"] + ["N"] + ["N"] + ["F"] * 4
    return tuple(heavy + ["H"] * hydrogens)


def _endpoint(hydrogens: int, charge: int, sha: str) -> _Endpoint:
    return _Endpoint(
        geometry=_Geometry(tuple(_Atom(e) for e in _elements(hydrogens))),
        charge=charge,
        multiplicity=1,
        xyz_sha256=sha,
    )


def _consumed(tmp_path: Path) -> ConsumedPhase9BPermit:
    raw = render_phase9b_permit(
        route=ROUTE_DIRECT,
        project_root=tmp_path.as_posix(),
        request_sha256=_REQ,
        runner_source_sha256=_SRC,
        payload_manifest_sha256=_PAY,
        cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
        neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
        resources={"threads": 4},
    )
    permit = parse_phase9b_permit(raw)
    return ConsumedPhase9BPermit(
        permit=permit,
        consumed_path=permit.consumed_path,
        consumed_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _request(consumed: ConsumedPhase9BPermit) -> _Request:
    permit = consumed.permit
    return _Request(
        schema_version=REQUEST_SCHEMA_VERSION,
        execution_authorized=True,
        protocol_sha256=LOCKED_PROTOCOL_SHA256,
        timeout_seconds=_FROZEN_TIMEOUT,
        request_sha256=permit.request_sha256,
        runner_source_sha256=permit.runner_source_sha256,
        request_id=REQUEST_ID,
        inchikey=PHASE9B_CANDIDATE.inchikey,
        request_path=permit.request_path,
        cation=_endpoint(5, 1, permit.cation_xyz_sha256),
        neutral=_endpoint(4, 0, permit.neutral_xyz_sha256),
    )


def test_exact_authority_round_trip(tmp_path: Path) -> None:
    consumed = _consumed(tmp_path)
    authority = validate_exact_phase9b_authority(
        _request(consumed),
        consumed,
        output_root=consumed.permit.output_root,
        attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
    )
    assert authority.route == ROUTE_DIRECT
    assert authority.electron_count == 160
    assert authority.request_sha256 == _REQ
    assert authority.output_root == consumed.permit.output_root.as_posix()


def test_request_hash_disagreement_fails(tmp_path: Path) -> None:
    consumed = _consumed(tmp_path)
    bad = replace(_request(consumed), request_sha256="f" * 64)
    with pytest.raises(Phase9BPermitValidationError, match="request hash disagrees"):
        validate_exact_phase9b_authority(
            bad,
            consumed,
            output_root=consumed.permit.output_root,
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        )


def test_retired_qxh_candidate_fails(tmp_path: Path) -> None:
    consumed = _consumed(tmp_path)
    bad = replace(_request(consumed), inchikey="QXHIEGFUWOLQIJ-UHFFFAOYSA-N")
    with pytest.raises(Phase9BPermitValidationError, match="candidate disagrees"):
        validate_exact_phase9b_authority(
            bad,
            consumed,
            output_root=consumed.permit.output_root,
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        )


def test_wrong_route_attempt_fails(tmp_path: Path) -> None:
    consumed = _consumed(tmp_path)
    with pytest.raises(Phase9BPermitValidationError, match="attempt identity disagrees"):
        validate_exact_phase9b_authority(
            _request(consumed),
            consumed,
            output_root=consumed.permit.output_root,
            attempt_id=ROUTE_ATTEMPT_IDS["assisted"],
        )


def test_geometry_hash_drift_fails(tmp_path: Path) -> None:
    consumed = _consumed(tmp_path)
    request = _request(consumed)
    bad = replace(request, cation=replace(request.cation, xyz_sha256="a" * 64))
    with pytest.raises(Phase9BPermitValidationError, match="geometry disagrees"):
        validate_exact_phase9b_authority(
            bad,
            consumed,
            output_root=consumed.permit.output_root,
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        )


def test_output_root_mismatch_and_resume_prohibition(tmp_path: Path) -> None:
    consumed = _consumed(tmp_path)
    with pytest.raises(Phase9BPermitValidationError, match="output root disagrees"):
        validate_exact_phase9b_authority(
            _request(consumed),
            consumed,
            output_root=tmp_path / "elsewhere",
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        )
    existing = consumed.permit.output_root
    existing.mkdir(parents=True)
    with pytest.raises(Phase9BPermitValidationError, match="resume is prohibited"):
        validate_exact_phase9b_authority(
            _request(consumed),
            consumed,
            output_root=existing,
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        )


def test_broken_endpoint_pair_fails(tmp_path: Path) -> None:
    consumed = _consumed(tmp_path)
    request = _request(consumed)
    bad = replace(request, neutral=replace(request.neutral, charge=1))
    with pytest.raises(Phase9BPermitValidationError, match="endpoint validation failed"):
        validate_exact_phase9b_authority(
            bad,
            consumed,
            output_root=consumed.permit.output_root,
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        )


def test_unlinearized_consumed_hash_fails(tmp_path: Path) -> None:
    consumed = _consumed(tmp_path)
    bad = ConsumedPhase9BPermit(
        permit=consumed.permit,
        consumed_path=consumed.consumed_path,
        consumed_sha256="9" * 64,
    )
    with pytest.raises(Phase9BPermitValidationError, match="not linearized"):
        validate_exact_phase9b_authority(
            _request(bad),
            bad,
            output_root=bad.permit.output_root,
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        )


def _valid(consumed: ConsumedPhase9BPermit) -> _Request:
    return _request(consumed)


def test_schema_version_drift_fails(tmp_path: Path) -> None:
    """Parity with the Phase 8B frozen-worker match, which checks all four."""

    consumed = _consumed(tmp_path)
    bad = replace(_valid(consumed), schema_version="nhc-two-endpoint-request-v0")
    with pytest.raises(Phase9BPermitValidationError, match="schema version drifted"):
        validate_exact_phase9b_authority(
            bad,
            consumed,
            output_root=consumed.permit.output_root,
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        )


def test_unauthorized_request_fails(tmp_path: Path) -> None:
    consumed = _consumed(tmp_path)
    bad = replace(_valid(consumed), execution_authorized=False)
    with pytest.raises(Phase9BPermitValidationError, match="does not authorize execution"):
        validate_exact_phase9b_authority(
            bad,
            consumed,
            output_root=consumed.permit.output_root,
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        )


def test_non_locked_protocol_fails(tmp_path: Path) -> None:
    consumed = _consumed(tmp_path)
    bad = replace(_valid(consumed), protocol_sha256="e" * 64)
    with pytest.raises(Phase9BPermitValidationError, match="locked protocol"):
        validate_exact_phase9b_authority(
            bad,
            consumed,
            output_root=consumed.permit.output_root,
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        )


def test_widened_wall_time_fails(tmp_path: Path) -> None:
    """A request may not enlarge the frozen budget at runtime."""

    consumed = _consumed(tmp_path)
    bad = replace(_valid(consumed), timeout_seconds=86_400)
    with pytest.raises(Phase9BPermitValidationError, match="frozen budget"):
        validate_exact_phase9b_authority(
            bad,
            consumed,
            output_root=consumed.permit.output_root,
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        )
