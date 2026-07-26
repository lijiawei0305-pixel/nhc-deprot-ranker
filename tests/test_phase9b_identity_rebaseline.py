"""Phase 9B identity re-baseline regressions.

Proves the source closure was re-frozen at v5, that every regenerated identity
references that one digest, and that the superseded v4 identities are recorded
rather than deleted or relabelled. No chemistry, no server, no compute.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nhc_deprot_ranker.preparation.phase9b_bundle import build_route_payload, build_route_request
from nhc_deprot_ranker.preparation.phase9b_permit_stage import build_route_permit_plan
from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_permit import (
    REQUEST_ID,
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
    parse_phase9b_permit,
    render_phase9b_permit,
)
from nhc_deprot_ranker.quantum.phase9b_resources import (
    phase9b_resources_payload,
    phase9b_resources_sha256,
)

# The re-baselined identities, recorded so drift is a test failure rather than a
# surprise at launch time. Permit digests are absent by design: they depend on the
# private project root.
SUPERSEDED_SOURCE_SHA256 = "2059b35d0e62bc844e7fc602929e9e53b79cd3e9fcc6644fb4e67580e1a5a52c"
SUPERSEDED_V5_SOURCE_SHA256 = "c914afe3f166ea1ef47dd2e27901aac660c918d110f51299c806ee605164fea8"
SUPERSEDED_V6_SOURCE_SHA256 = "72125b67abc9e52d41a41bc6d3f4dc5ce9a999d1f577717b30c011076de10de3"
FINAL_SOURCE_SCHEMA = "nhc-two-endpoint-runner-source-v7"
FINAL_SOURCE_SHA256 = "d7060a314993225595c616f4329b08689c6974de621ef663c18f891d6a7d9c22"
FINAL_RESOURCES_SHA256 = "0fec2c1914f413a2762e1fafc7daa9900551981b5af72897746864edffac7df8"
DIRECT_REQUEST_SHA256 = "a53c26201fd1f2989fd242681c3c382fd17cc1c88c1433cd5dcc7c0a58ec04d2"
DIRECT_MANIFEST_SHA256 = "f73cdb9a3a34fe49738994800a1d7d79bc0b854ae197a385c3151cce2c8305b5"
ASSISTED_REQUEST_SHA256 = "feaecb7b6de9e7ab0f8710b4fd9e094d019b3cc6c1f68d349dc901137ebe7659"
ASSISTED_MANIFEST_SHA256 = "bc0534f72fe16eb69338af1eb897c3a705b71b7973825f7a4fe9e9732e236d7b"

_DOC = Path("docs/PHASE9B_IDENTITY_REBASELINE.md")


def _chain(route: str) -> tuple[str, str]:
    request = build_route_request(
        route=route,
        runner_source_sha256=runner.current_runner_source_sha256(),
        protocol=runner.LOCKED_PROTOCOL,
        cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
        neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
    )
    return request.request_sha256, build_route_payload(request).manifest_sha256


def test_the_source_schema_was_upgraded() -> None:
    assert runner.RUNNER_SOURCE_SCHEMA_VERSION == FINAL_SOURCE_SCHEMA
    assert FINAL_SOURCE_SCHEMA.endswith("-v7")


def test_the_source_closure_is_re_frozen_at_the_recorded_digest() -> None:
    """Any future closure edit fails here until this constant is re-baselined."""

    assert runner.current_runner_source_sha256() == FINAL_SOURCE_SHA256
    assert FINAL_SOURCE_SHA256 != SUPERSEDED_SOURCE_SHA256
    assert len(runner._RUNNER_SOURCE_RELATIVE_PATHS) == 23  # pyright: ignore[reportPrivateUsage]


def test_the_three_edited_files_are_inside_the_closure() -> None:
    closure = set(runner._RUNNER_SOURCE_RELATIVE_PATHS)  # pyright: ignore[reportPrivateUsage]
    assert "nhc_deprot_ranker/quantum/phase9b_supervisor.py" in closure
    assert "nhc_deprot_ranker/quantum/two_endpoint.py" in closure
    # And the new control-plane module is outside it, so it moves nothing.
    assert not any("permit_stage" in path for path in closure)


def test_the_resource_budget_did_not_move() -> None:
    assert phase9b_resources_sha256() == FINAL_RESOURCES_SHA256


def test_both_chains_are_regenerated_against_the_final_digest() -> None:
    """The assisted chain is now concrete rather than pending."""

    assert _chain(ROUTE_DIRECT) == (DIRECT_REQUEST_SHA256, DIRECT_MANIFEST_SHA256)
    assert _chain(ROUTE_ASSISTED) == (ASSISTED_REQUEST_SHA256, ASSISTED_MANIFEST_SHA256)
    assert len({DIRECT_REQUEST_SHA256, ASSISTED_REQUEST_SHA256}) == 2
    assert len({DIRECT_MANIFEST_SHA256, ASSISTED_MANIFEST_SHA256}) == 2


def test_both_routes_start_from_the_same_frozen_initial_geometry() -> None:
    """The invariant that makes the paired comparison interpretable."""

    from nhc_deprot_ranker.preparation.phase9b_bundle import validate_route_parity

    payloads = {}
    for route in (ROUTE_DIRECT, ROUTE_ASSISTED):
        request = build_route_request(
            route=route,
            runner_source_sha256=runner.current_runner_source_sha256(),
            protocol=runner.LOCKED_PROTOCOL,
            cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
            neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
        )
        assert request.cation_xyz_sha256 == PHASE9B_CANDIDATE.cation_xyz_sha256
        assert request.neutral_xyz_sha256 == PHASE9B_CANDIDATE.neutral_xyz_sha256
        payloads[route] = build_route_payload(request)
    validate_route_parity(payloads[ROUTE_DIRECT], payloads[ROUTE_ASSISTED])


def test_neither_chain_depends_on_a_pre_existing_preoptimized_geometry() -> None:
    """Requiring one made step 5 depend on step 10.  It no longer does."""

    for route in (ROUTE_DIRECT, ROUTE_ASSISTED):
        request = build_route_request(
            route=route,
            runner_source_sha256=runner.current_runner_source_sha256(),
            protocol=runner.LOCKED_PROTOCOL,
            cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
            neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
        )
        body = json.loads(request.request_bytes.decode())
        assert body["endpoints"]["cation"]["xyz_sha256"] == PHASE9B_CANDIDATE.cation_xyz_sha256
        stage = body["preoptimization"]
        if route == ROUTE_ASSISTED:
            assert stage["runs_inside_route"] is True
            assert stage["external_preparation_authorized"] is False
        else:
            assert stage == {"stage": "none", "aimnet2_authorized": False}


def test_every_new_identity_references_the_same_final_source_digest() -> None:
    """The whole point of the re-baseline: one digest, referenced everywhere."""

    source = runner.current_runner_source_sha256()
    assert source == FINAL_SOURCE_SHA256

    request = build_route_request(
        route=ROUTE_DIRECT,
        runner_source_sha256=source,
        protocol=runner.LOCKED_PROTOCOL,
        cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
        neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
    )
    payload = build_route_payload(request)
    permit = parse_phase9b_permit(
        render_phase9b_permit(
            route=ROUTE_DIRECT,
            project_root="/srv/project",
            request_sha256=request.request_sha256,
            runner_source_sha256=source,
            payload_manifest_sha256=payload.manifest_sha256,
            cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
            neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
            resources=phase9b_resources_payload(),
        )
    )
    plan = build_route_permit_plan(permit=permit, payload_manifest_sha256=payload.manifest_sha256)
    assert permit.runner_source_sha256 == source
    assert plan.runner_source_sha256 == source
    assert plan.request_sha256 == request.request_sha256
    assert plan.payload_manifest_sha256 == payload.manifest_sha256


def test_an_identity_built_against_the_superseded_digest_is_refused() -> None:
    """A v4-era request cannot be revived by pointing a new permit at it."""

    stale = build_route_request(
        route=ROUTE_DIRECT,
        runner_source_sha256=SUPERSEDED_SOURCE_SHA256,
        protocol=runner.LOCKED_PROTOCOL,
        cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
        neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
    )
    # The request itself can still be built -- it is only bytes -- but it no longer
    # matches the code that would run, and every consumer compares the two.
    assert stale.request_sha256 != DIRECT_REQUEST_SHA256
    body = json.loads(stale.request_bytes.decode())
    assert body["runner_source_sha256"] == SUPERSEDED_SOURCE_SHA256
    assert body["runner_source_sha256"] != runner.current_runner_source_sha256()


def test_every_superseded_generation_is_recorded(tmp_path: Path) -> None:
    """v4, v5, and v6 are all preserved; none is deleted or relabelled."""

    del tmp_path
    text = _DOC.read_text(encoding="utf-8")
    assert SUPERSEDED_SOURCE_SHA256 in text
    assert SUPERSEDED_V5_SOURCE_SHA256 in text
    assert SUPERSEDED_V6_SOURCE_SHA256 in text
    assert text.count("superseded_before_execution") >= 3
    assert FINAL_SOURCE_SHA256 not in {
        SUPERSEDED_SOURCE_SHA256,
        SUPERSEDED_V5_SOURCE_SHA256,
        SUPERSEDED_V6_SOURCE_SHA256,
    }


def test_the_superseded_identities_are_recorded_and_correctly_labelled() -> None:
    text = _DOC.read_text(encoding="utf-8")
    assert SUPERSEDED_SOURCE_SHA256 in text
    assert "superseded_before_execution" in text
    # Never described as consumed, failed, or rejected: none of those happened.
    body = text.split("## Status of the previous identities")[1].split("## The final closure")[0]
    for wrong in ("was consumed", "were consumed", "was rejected", "were rejected"):
        assert wrong not in body


def test_the_rebaseline_record_names_what_is_still_not_wired() -> None:
    text = _DOC.read_text(encoding="utf-8")
    assert "Postflight does not exist" in text
    assert "no runtime implementation inside the route" in text
    assert "Nothing here has been executed" in text


def test_the_record_leaks_no_private_path_or_host() -> None:
    text = _DOC.read_text(encoding="utf-8")
    assert "/Users/" not in text and "/home/" not in text
    assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text)
    assert "@" not in text


@pytest.mark.parametrize("route", [ROUTE_DIRECT, ROUTE_ASSISTED])
def test_the_request_identity_and_attempt_pairing_did_not_move(route: str) -> None:
    assert REQUEST_ID == "phase9b-lbnp-paired-smoke-v001"
    assert ROUTE_ATTEMPT_IDS[route].startswith("attempt-phase9b-lbnp-")
    assert PHASE9B_CANDIDATE.inchikey == "LBNPGYISTSLAHY-UHFFFAOYSA-N"
    assert PHASE9B_CANDIDATE.electron_count == 160
