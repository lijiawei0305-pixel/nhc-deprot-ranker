"""Phase 9B bundle regressions. No chemistry, no server, no compute, no permit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nhc_deprot_ranker.preparation import phase9b_bundle as bundle
from nhc_deprot_ranker.preparation.phase9b_bundle import (
    Phase9BBundleError,
    Phase9BBundleNotAuthorizedError,
    build_route_payload,
    build_route_request,
    validate_route_parity,
)
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_permit import ROUTE_ASSISTED, ROUTE_DIRECT
from nhc_deprot_ranker.quantum.phase9b_resources import phase9b_resources_sha256
from nhc_deprot_ranker.quantum.two_endpoint import (
    LOCKED_PROTOCOL,
    current_runner_source_sha256,
)

_PRE_C = "4" * 64
_PRE_N = "5" * 64


def _request(route: str, **kw: object) -> bundle.RouteRequest:
    if route == ROUTE_DIRECT:
        cation = PHASE9B_CANDIDATE.cation_xyz_sha256
        neutral = PHASE9B_CANDIDATE.neutral_xyz_sha256
    else:
        cation, neutral = _PRE_C, _PRE_N
    params: dict[str, object] = {
        "route": route,
        "runner_source_sha256": current_runner_source_sha256(),
        "protocol": LOCKED_PROTOCOL,
        "cation_xyz_sha256": cation,
        "neutral_xyz_sha256": neutral,
    }
    params.update(kw)
    return build_route_request(**params)  # type: ignore[arg-type]


def _payload(route: str) -> bundle.RoutePayload:
    return build_route_payload(_request(route))


def test_source_gate_is_closed_and_materialization_refuses() -> None:
    assert bundle.EXECUTION_AUTHORIZED is False
    source = Path(bundle.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source
    with pytest.raises(Phase9BBundleNotAuthorizedError, match="not authorized"):
        bundle.materialize_bundle()


def test_both_routes_build_canonical_requests() -> None:
    for route in (ROUTE_DIRECT, ROUTE_ASSISTED):
        request = _request(route)
        assert request.route == route
        assert len(request.request_sha256) == 64
        payload = json.loads(request.request_bytes)
        assert payload["request_id"] == "phase9b-lbnp-paired-smoke-v001"
        assert payload["inchikey"] == PHASE9B_CANDIDATE.inchikey
        assert payload["execution_authorized"] is True
        assert payload["timeout_seconds"] == 7200
        assert payload["endpoints"]["cation"]["charge"] == 1
        assert payload["endpoints"]["neutral"]["charge"] == 0
        assert payload["endpoints"]["cation"]["multiplicity"] == 1
        assert payload["endpoints"]["neutral"]["multiplicity"] == 1


def test_request_bytes_are_deterministic() -> None:
    assert _request(ROUTE_DIRECT).request_bytes == _request(ROUTE_DIRECT).request_bytes


def test_direct_route_must_carry_the_frozen_initial_geometry() -> None:
    with pytest.raises(Phase9BBundleError, match="frozen initial geometry"):
        _request(ROUTE_DIRECT, cation_xyz_sha256=_PRE_C)


def test_assisted_route_must_not_carry_the_initial_geometry() -> None:
    with pytest.raises(Phase9BBundleError, match="not the initial geometry"):
        _request(
            ROUTE_ASSISTED,
            cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
            neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
        )


def test_endpoints_cannot_share_one_geometry_hash() -> None:
    with pytest.raises(Phase9BBundleError, match="cannot share one geometry hash"):
        _request(ROUTE_ASSISTED, cation_xyz_sha256=_PRE_C, neutral_xyz_sha256=_PRE_C)


def test_unknown_route_and_bad_hashes_fail_closed() -> None:
    with pytest.raises(Phase9BBundleError, match="unknown Phase 9B route"):
        _request("sideways")
    with pytest.raises(Phase9BBundleError, match="must be a lowercase SHA256"):
        _request(ROUTE_ASSISTED, runner_source_sha256="nope")


def test_empty_protocol_fails_closed() -> None:
    with pytest.raises(Phase9BBundleError, match="must not be empty"):
        _request(ROUTE_DIRECT, protocol={})


def test_manifest_excludes_the_permit_and_declares_no_label() -> None:
    manifest = json.loads(_payload(ROUTE_DIRECT).manifest_bytes)
    assert manifest["excludes_permit"] is True
    assert manifest["label_produced"] is False
    assert manifest["hessian_computed"] is False
    assert manifest["ensemble_members"] == 1
    assert manifest["ensemble_uncertainty_available"] is False
    assert not any("permit" in name for name in manifest["files"])


def test_manifest_binds_the_frozen_provenance_and_resources() -> None:
    manifest = json.loads(_payload(ROUTE_ASSISTED).manifest_bytes)
    provenance = manifest["provenance"]
    assert provenance["initial_cation_xyz_sha256"] == PHASE9B_CANDIDATE.cation_xyz_sha256
    assert provenance["initial_neutral_xyz_sha256"] == PHASE9B_CANDIDATE.neutral_xyz_sha256
    assert provenance["legacy_atom_map_sha256"] == PHASE9B_CANDIDATE.legacy_atom_map_sha256
    assert provenance["geometry_validation_sha256"] == (
        PHASE9B_CANDIDATE.geometry_validation_sha256
    )
    assert manifest["resources_sha256"] == phase9b_resources_sha256()
    assert manifest["electron_count"] == 160


def test_assisted_manifest_keeps_the_initial_geometry_as_parent_lineage() -> None:
    """Route A's files are preoptimized; its provenance still names the parents."""

    manifest = json.loads(_payload(ROUTE_ASSISTED).manifest_bytes)
    assert manifest["files"][bundle.CATION_XYZ_RELATIVE] == _PRE_C
    assert manifest["provenance"]["initial_cation_xyz_sha256"] != _PRE_C


def test_route_parity_accepts_the_two_built_payloads() -> None:
    validate_route_parity(_payload(ROUTE_DIRECT), _payload(ROUTE_ASSISTED))


def test_route_parity_rejects_a_differing_timeout() -> None:
    """The only sanctioned differences are geometry hashes and attempt identity."""

    direct = _payload(ROUTE_DIRECT)
    tampered = json.loads(direct.request.request_bytes)
    tampered["timeout_seconds"] = 86_400
    raw = (json.dumps(tampered, sort_keys=True, indent=2) + "\n").encode()
    broken = bundle.RoutePayload(
        request=bundle.RouteRequest(
            route=ROUTE_DIRECT,
            attempt_id=direct.request.attempt_id,
            request_bytes=raw,
            request_sha256="0" * 64,
            cation_xyz_sha256=direct.request.cation_xyz_sha256,
            neutral_xyz_sha256=direct.request.neutral_xyz_sha256,
        ),
        manifest_bytes=direct.manifest_bytes,
        manifest_sha256=direct.manifest_sha256,
    )
    with pytest.raises(Phase9BBundleError, match="differ outside geometry: timeout_seconds"):
        validate_route_parity(broken, _payload(ROUTE_ASSISTED))


def test_route_parity_rejects_a_differing_endpoint_charge() -> None:
    assisted = _payload(ROUTE_ASSISTED)
    tampered = json.loads(assisted.request.request_bytes)
    tampered["endpoints"]["neutral"]["charge"] = 1
    raw = (json.dumps(tampered, sort_keys=True, indent=2) + "\n").encode()
    broken = bundle.RoutePayload(
        request=bundle.RouteRequest(
            route=ROUTE_ASSISTED,
            attempt_id=assisted.request.attempt_id,
            request_bytes=raw,
            request_sha256="1" * 64,
            cation_xyz_sha256=assisted.request.cation_xyz_sha256,
            neutral_xyz_sha256=assisted.request.neutral_xyz_sha256,
        ),
        manifest_bytes=assisted.manifest_bytes,
        manifest_sha256=assisted.manifest_sha256,
    )
    with pytest.raises(Phase9BBundleError, match="endpoint neutral differs outside geometry"):
        validate_route_parity(_payload(ROUTE_DIRECT), broken)


def test_route_parity_rejects_swapped_labels_and_shared_identity() -> None:
    with pytest.raises(Phase9BBundleError, match="one direct and one assisted"):
        validate_route_parity(_payload(ROUTE_ASSISTED), _payload(ROUTE_DIRECT))
    same = _payload(ROUTE_DIRECT)
    with pytest.raises(Phase9BBundleError, match="one direct and one assisted"):
        validate_route_parity(same, same)


def test_geometry_hashes_are_the_only_endpoint_difference() -> None:
    """Positive statement of the parity rule the comparison enforces."""

    left = json.loads(_payload(ROUTE_DIRECT).request.request_bytes)
    right = json.loads(_payload(ROUTE_ASSISTED).request.request_bytes)
    for endpoint in ("cation", "neutral"):
        a, b = left["endpoints"][endpoint], right["endpoints"][endpoint]
        differing = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
        assert differing == {"xyz_sha256"}, (endpoint, differing)


def test_module_declares_no_label_and_imports_no_chemistry() -> None:
    source = Path(bundle.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("import pyscf", "import torch", "import aimnet", "627.509474", "kcal"):
        assert forbidden not in source, forbidden
    assert "render_phase9b_permit" not in source


def test_module_is_outside_the_runner_source_closure() -> None:
    from nhc_deprot_ranker.quantum import two_endpoint

    closure = two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    assert not any("phase9b_bundle" in member for member in closure)


def _clone(payload: bundle.RoutePayload, **kw: object) -> bundle.RoutePayload:
    from dataclasses import replace

    return bundle.RoutePayload(
        request=replace(payload.request, **kw),  # type: ignore[arg-type]
        manifest_bytes=payload.manifest_bytes,
        manifest_sha256=payload.manifest_sha256,
    )


def test_route_parity_rejects_a_shared_attempt_identity() -> None:
    """Caught by mutation testing: built payloads always differ, so the guard was
    unreachable through the normal builder and needed driving directly.
    """

    direct = _payload(ROUTE_DIRECT)
    assisted = _clone(_payload(ROUTE_ASSISTED), attempt_id=direct.request.attempt_id)
    with pytest.raises(Phase9BBundleError, match="distinct attempt identities"):
        validate_route_parity(direct, assisted)


def test_route_parity_rejects_one_request_reused_as_both_routes() -> None:
    direct = _payload(ROUTE_DIRECT)
    assisted = _clone(_payload(ROUTE_ASSISTED), request_sha256=direct.request.request_sha256)
    with pytest.raises(Phase9BBundleError, match="distinct requests"):
        validate_route_parity(direct, assisted)
