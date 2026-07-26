"""Phase 9B geometry-provenance binding regressions.

No chemistry, no server, no compute.

The capability parameterization surfaced that Phase9BExactAuthority carried no
atom-map or geometry-validation binding, even though the Phase 7 validation hash
stays meaningful for Route D (whose inputs ARE the Phase 7 geometry) and the atom
maps stay meaningful for both routes (atom order is index-preserving across
preoptimization). These tests pin the extension rather than a weakened
expectation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from nhc_deprot_ranker.quantum.phase8b_authority import PHASE7_GEOMETRY_VALIDATION_SHA256
from nhc_deprot_ranker.quantum.phase9b_authority import (
    PHASE9B_CANDIDATE,
    Phase9BAuthorityError,
    validate_profile_self_consistency,
)
from nhc_deprot_ranker.quantum.phase9b_permit import (
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
    ConsumedPhase9BPermit,
    Phase9BPermitValidationError,
    parse_phase9b_permit,
    render_phase9b_permit,
    validate_exact_phase9b_authority,
)

_REQ = "1" * 64
_SRC = "2" * 64
_PAY = "3" * 64
_PRE_C = "4" * 64
_PRE_N = "5" * 64

_LEGACY_MAP = "ce0e2fc05b44e7e18a8be445ff23e398b0f6302dcfb0fe48da8f9522a1b48ab1"
_ENDPOINT_MAP = "f614486a6ae18afed109cd0bcf52efb27b290558e758f5c2e85c8f192b70d9ab"


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


def test_profile_carries_the_phase7_geometry_provenance() -> None:
    assert PHASE9B_CANDIDATE.legacy_atom_map_sha256 == _LEGACY_MAP
    assert PHASE9B_CANDIDATE.endpoint_atom_map_sha256 == _ENDPOINT_MAP
    assert PHASE9B_CANDIDATE.geometry_validation_sha256 == PHASE7_GEOMETRY_VALIDATION_SHA256


def test_geometry_validation_hash_is_the_shared_phase7_anchor() -> None:
    """It covers all four smoke candidates, so it is not candidate-specific."""

    assert (
        PHASE9B_CANDIDATE.geometry_validation_sha256
        == "35e99683a32e416752014c6e1ecb8121e2bc06d5407911435e5c1250fd639f90"
    )


def test_profile_rejects_a_malformed_provenance_hash() -> None:
    for bad in (
        replace(PHASE9B_CANDIDATE, legacy_atom_map_sha256="not-a-sha256"),
        replace(PHASE9B_CANDIDATE, endpoint_atom_map_sha256="not-a-sha256"),
        replace(PHASE9B_CANDIDATE, geometry_validation_sha256="not-a-sha256"),
        replace(PHASE9B_CANDIDATE, geometry_validation_sha256="A" * 64),
    ):
        with pytest.raises(Phase9BAuthorityError, match="SHA256"):
            validate_profile_self_consistency(bad)


def test_frozen_profile_is_still_self_consistent() -> None:
    validate_profile_self_consistency(PHASE9B_CANDIDATE)


def _consumed(tmp_path: Path, route: str) -> ConsumedPhase9BPermit:
    if route == ROUTE_DIRECT:
        cation, neutral = (
            PHASE9B_CANDIDATE.cation_xyz_sha256,
            PHASE9B_CANDIDATE.neutral_xyz_sha256,
        )
    else:
        cation, neutral = _PRE_C, _PRE_N
    raw = render_phase9b_permit(
        route=route,
        project_root=tmp_path.as_posix(),
        request_sha256=_REQ,
        runner_source_sha256=_SRC,
        payload_manifest_sha256=_PAY,
        cation_xyz_sha256=cation,
        neutral_xyz_sha256=neutral,
        resources={"threads": 4},
    )
    permit = parse_phase9b_permit(raw)
    return ConsumedPhase9BPermit(
        permit=permit,
        consumed_path=permit.consumed_path,
        consumed_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _authority(tmp_path: Path, route: str) -> object:
    from nhc_deprot_ranker.quantum.phase9b_permit import REQUEST_ID

    consumed = _consumed(tmp_path, route)
    permit = consumed.permit
    request = _Request(
        request_sha256=permit.request_sha256,
        runner_source_sha256=permit.runner_source_sha256,
        request_id=REQUEST_ID,
        inchikey=PHASE9B_CANDIDATE.inchikey,
        request_path=permit.request_path,
        cation=_endpoint(5, 1, permit.cation_xyz_sha256),
        neutral=_endpoint(4, 0, permit.neutral_xyz_sha256),
    )
    return validate_exact_phase9b_authority(
        request,
        consumed,
        output_root=permit.output_root,
        attempt_id=ROUTE_ATTEMPT_IDS[route],
    )


def test_both_routes_bind_the_geometry_provenance(tmp_path: Path) -> None:
    """Route A binds it as lineage; Route D binds it as its actual inputs."""

    for index, route in enumerate((ROUTE_DIRECT, ROUTE_ASSISTED)):
        authority = _authority(tmp_path / f"r{index}", route)
        assert authority.legacy_atom_map_sha256 == _LEGACY_MAP  # type: ignore[attr-defined]
        assert authority.endpoint_atom_map_sha256 == _ENDPOINT_MAP  # type: ignore[attr-defined]
        assert (
            authority.geometry_validation_sha256  # type: ignore[attr-defined]
            == PHASE7_GEOMETRY_VALIDATION_SHA256
        )


def test_authority_provenance_comes_from_the_profile_not_the_permit(tmp_path: Path) -> None:
    """A permit cannot assert its own geometry provenance."""

    source = Path(
        __import__("nhc_deprot_ranker.quantum.phase9b_permit", fromlist=["__file__"]).__file__  # type: ignore[arg-type]
    ).read_text(encoding="utf-8")
    start = source.index("def validate_exact_phase9b_authority")
    body = source[start:]
    assert "profile.legacy_atom_map_sha256" in body
    assert "profile.endpoint_atom_map_sha256" in body
    assert "profile.geometry_validation_sha256" in body


def test_route_d_inputs_remain_exactly_the_validated_phase7_geometry(tmp_path: Path) -> None:
    """The binding is only meaningful if Route D really uses that geometry."""

    consumed = _consumed(tmp_path, ROUTE_DIRECT)
    assert consumed.permit.cation_xyz_sha256 == PHASE9B_CANDIDATE.cation_xyz_sha256
    assert consumed.permit.neutral_xyz_sha256 == PHASE9B_CANDIDATE.neutral_xyz_sha256


def test_assisted_route_still_binds_the_initial_geometry_as_parent(tmp_path: Path) -> None:
    consumed = _consumed(tmp_path, ROUTE_ASSISTED)
    assert consumed.permit.cation_xyz_sha256 == _PRE_C
    raw = consumed.permit.raw_bytes.decode()
    assert PHASE9B_CANDIDATE.cation_xyz_sha256 in raw
    assert PHASE9B_CANDIDATE.neutral_xyz_sha256 in raw


def test_a_profile_with_drifted_provenance_cannot_authorize(tmp_path: Path) -> None:
    from nhc_deprot_ranker.quantum.phase9b_permit import REQUEST_ID

    consumed = _consumed(tmp_path, ROUTE_DIRECT)
    permit = consumed.permit
    request = _Request(
        request_sha256=permit.request_sha256,
        runner_source_sha256=permit.runner_source_sha256,
        request_id=REQUEST_ID,
        inchikey=PHASE9B_CANDIDATE.inchikey,
        request_path=permit.request_path,
        cation=_endpoint(5, 1, permit.cation_xyz_sha256),
        neutral=_endpoint(4, 0, permit.neutral_xyz_sha256),
    )
    drifted = replace(PHASE9B_CANDIDATE, geometry_validation_sha256="deadbeef")
    with pytest.raises(Phase9BPermitValidationError, match=r"SHA256|profile"):
        validate_exact_phase9b_authority(
            request,
            consumed,
            output_root=permit.output_root,
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
            profile=drifted,
        )
