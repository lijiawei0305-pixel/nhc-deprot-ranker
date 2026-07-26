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
FINAL_SOURCE_SCHEMA = "nhc-two-endpoint-runner-source-v5"
FINAL_SOURCE_SHA256 = "c914afe3f166ea1ef47dd2e27901aac660c918d110f51299c806ee605164fea8"
FINAL_RESOURCES_SHA256 = "0fec2c1914f413a2762e1fafc7daa9900551981b5af72897746864edffac7df8"
DIRECT_REQUEST_SHA256 = "8f8d892b8f161f4aafb6fb03c712f531c0acdb590850ccf7ffcc8c772387546a"
DIRECT_MANIFEST_SHA256 = "1c0ef215b234033dc545ac5f5e613bc9757c34bf2a8e7e77d5a8df387a2d1c0f"

_DOC = Path("docs/PHASE9B_IDENTITY_REBASELINE.md")


def _direct_chain() -> tuple[str, str]:
    request = build_route_request(
        route=ROUTE_DIRECT,
        runner_source_sha256=runner.current_runner_source_sha256(),
        protocol=runner.LOCKED_PROTOCOL,
        cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
        neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
    )
    return request.request_sha256, build_route_payload(request).manifest_sha256


def test_the_source_schema_was_upgraded() -> None:
    assert runner.RUNNER_SOURCE_SCHEMA_VERSION == FINAL_SOURCE_SCHEMA
    assert FINAL_SOURCE_SCHEMA.endswith("-v5")


def test_the_source_closure_is_re_frozen_at_the_recorded_digest() -> None:
    """Any future closure edit fails here until this constant is re-baselined."""

    assert runner.current_runner_source_sha256() == FINAL_SOURCE_SHA256
    assert FINAL_SOURCE_SHA256 != SUPERSEDED_SOURCE_SHA256
    assert len(runner._RUNNER_SOURCE_RELATIVE_PATHS) == 18  # pyright: ignore[reportPrivateUsage]


def test_the_three_edited_files_are_inside_the_closure() -> None:
    closure = set(runner._RUNNER_SOURCE_RELATIVE_PATHS)  # pyright: ignore[reportPrivateUsage]
    assert "nhc_deprot_ranker/quantum/phase9b_supervisor.py" in closure
    assert "nhc_deprot_ranker/quantum/two_endpoint.py" in closure
    # And the new control-plane module is outside it, so it moves nothing.
    assert not any("permit_stage" in path for path in closure)


def test_the_resource_budget_did_not_move() -> None:
    assert phase9b_resources_sha256() == FINAL_RESOURCES_SHA256


def test_the_direct_chain_is_regenerated_against_the_final_digest() -> None:
    request_sha256, manifest_sha256 = _direct_chain()
    assert request_sha256 == DIRECT_REQUEST_SHA256
    assert manifest_sha256 == DIRECT_MANIFEST_SHA256
    assert request_sha256 != manifest_sha256


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


def test_the_assisted_chain_is_pending_rather_than_fabricated() -> None:
    """Its inputs are preoptimized geometry, which does not exist yet."""

    assert ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED] == "attempt-phase9b-lbnp-assisted-v001"
    text = _DOC.read_text(encoding="utf-8")
    assert "pending AIMNet2 preoptimization" in text
    assert "request_sha256         pending" in text
    # No fabricated assisted digests anywhere in the record.
    assisted_section = text.split("### Route A")[1].split("### Both permits")[0]
    assert not re.search(r"\b[0-9a-f]{64}\b", assisted_section.replace(FINAL_SOURCE_SHA256, ""))


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
    assert "guardian transaction does not exist" in text
    assert "launch transport is not reconciled" in text


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
