"""Phase 9B v9 composite freeze and retained-v8 supersession regressions.

Proves the source closure was re-frozen at v9, that every regenerated identity
references that one digest, and that the superseded v4-v8 identities are recorded
rather than deleted or relabelled. No chemistry, no server, no compute.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nhc_deprot_ranker.preparation.phase9b_bundle import (
    REQUEST_ID_V3,
    ROUTE_ATTEMPT_IDS_V3,
    build_route_payload_v3,
    build_route_request_v3,
)
from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_permit import (
    ROUTE_ASSISTED,
    ROUTE_DIRECT,
)
from nhc_deprot_ranker.quantum.phase9b_resources import (
    phase9b_campaign_resources_sha256,
)
from nhc_deprot_ranker.quantum.phase9b_source_identity import (
    SOURCE_LEAVES,
    compute_composite_source_identity,
    frozen_interpreter_profile_assignments,
)

# The re-baselined identities, recorded so drift is a test failure rather than a
# surprise at launch time. Permit digests are absent by design: they depend on the
# private project root.
SUPERSEDED_SOURCE_SHA256 = "2059b35d0e62bc844e7fc602929e9e53b79cd3e9fcc6644fb4e67580e1a5a52c"
SUPERSEDED_V5_SOURCE_SHA256 = "c914afe3f166ea1ef47dd2e27901aac660c918d110f51299c806ee605164fea8"
SUPERSEDED_V6_SOURCE_SHA256 = "72125b67abc9e52d41a41bc6d3f4dc5ce9a999d1f577717b30c011076de10de3"
SUPERSEDED_V7_SOURCE_SHA256 = "d7060a314993225595c616f4329b08689c6974de621ef663c18f891d6a7d9c22"
SUPERSEDED_V8_SOURCE_SHA256 = "5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2"
FINAL_SOURCE_SCHEMA = "nhc-two-endpoint-runner-source-v9"
FINAL_SOURCE_SHA256 = "13ba49fe33f8a85cceae76b043619df832d15633aa08a91d0eadfab7c6f580f5"
FINAL_RESOURCES_SHA256 = "39d1be30f30c85a21452a30548b5ba97414cb106461e8d0104beb6c34618c0ab"
DIRECT_REQUEST_SHA256 = "84046351c5ba6e1a8087acc6e3070f46ff3429f4781a1bf689a1fa473218c4d3"
DIRECT_MANIFEST_SHA256 = "f6e193706006fc1f6bc937ba636145e1c1617fe9245ea60db9703605f7707d9a"
ASSISTED_REQUEST_SHA256 = "24a1caf75b9cdbd061e366eab3202e7d1511d46ed2ca70245b4390fc04681933"
ASSISTED_MANIFEST_SHA256 = "ed91373bf0ced4a1d100f51966a8010812b41c9e55dbdf0ce56f68f5d06b1904"

_DOC = Path("docs/PHASE9B_IDENTITY_REBASELINE.md")


def _chain(route: str) -> tuple[str, str]:
    identity = _identity()
    request = build_route_request_v3(
        route=route,
        source_identity=identity,
        protocol=runner.LOCKED_PROTOCOL,
        cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
        neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
    )
    return request.request_sha256, build_route_payload_v3(
        request, source_identity=identity
    ).manifest_sha256


def _identity():
    return compute_composite_source_identity(
        Path(runner.__file__).resolve().parents[2],
        interpreter_profile_assignments=frozen_interpreter_profile_assignments(),
    )


def test_the_source_schema_was_upgraded() -> None:
    assert runner.RUNNER_SOURCE_SCHEMA_VERSION == FINAL_SOURCE_SCHEMA
    assert FINAL_SOURCE_SCHEMA.endswith("-v9")


def test_the_source_closure_is_re_frozen_at_the_recorded_digest() -> None:
    """Any future closure edit fails here until this constant is re-baselined."""

    assert runner.current_runner_source_sha256() == FINAL_SOURCE_SHA256
    assert FINAL_SOURCE_SHA256 != SUPERSEDED_SOURCE_SHA256
    assert len(runner._RUNNER_SOURCE_RELATIVE_PATHS) == 34  # pyright: ignore[reportPrivateUsage]
    assert len({path for leaf in SOURCE_LEAVES for path in leaf.files}) == 34


def test_public_v9_manifest_and_paired_generation_match_independent_recomputation() -> None:
    manifest = json.loads(Path("docs/PHASE9B_RUNNER_SOURCE_V9_MANIFEST.json").read_text())
    generation = json.loads(Path("docs/PHASE9B_PAIRED_GENERATION_V3.json").read_text())
    identity = _identity()
    assert manifest["full_assisted_campaign_source_sha256"] == FINAL_SOURCE_SHA256
    assert manifest["independent_recomputation_equal"] is True
    assert [item["name"] for item in manifest["leaves"]] == [leaf.name for leaf in identity.leaves]
    assert manifest["previous_v8"] == {
        "deployed": False,
        "launched": False,
        "permit_consumed": False,
        "permit_placed": False,
        "sha256": SUPERSEDED_V8_SOURCE_SHA256,
        "state": "superseded_before_execution",
    }
    assert generation["runner_source_sha256"] == FINAL_SOURCE_SHA256
    assert generation["campaign_resources_sha256"] == FINAL_RESOURCES_SHA256
    assert generation["routes"]["direct"]["request_sha256"] == DIRECT_REQUEST_SHA256
    assert generation["routes"]["assisted"]["request_sha256"] == (ASSISTED_REQUEST_SHA256)
    assert generation["real_permit_generated"] is False
    assert generation["public_execution_gates_open"] == 0
    assert generation["production_label_count"] == 71


def test_split_process_runtime_files_are_inside_disjoint_leaves() -> None:
    closure = set(runner._RUNNER_SOURCE_RELATIVE_PATHS)  # pyright: ignore[reportPrivateUsage]
    assert "nhc_deprot_ranker/quantum/phase9b_supervisor.py" in closure
    assert "nhc_deprot_ranker/quantum/two_endpoint.py" in closure
    assert "nhc_deprot_ranker/quantum/phase9b_campaign_supervisor.py" in closure
    assert "nhc_deprot_ranker/quantum/phase9b_stage_a1.py" in closure
    assert "nhc_deprot_ranker/quantum/phase9b_stage_a2.py" in closure


def test_the_resource_budget_did_not_move() -> None:
    assert phase9b_campaign_resources_sha256() == FINAL_RESOURCES_SHA256


def test_both_chains_are_regenerated_against_the_final_digest() -> None:
    """The assisted chain is now concrete rather than pending."""

    assert _chain(ROUTE_DIRECT) == (DIRECT_REQUEST_SHA256, DIRECT_MANIFEST_SHA256)
    assert _chain(ROUTE_ASSISTED) == (ASSISTED_REQUEST_SHA256, ASSISTED_MANIFEST_SHA256)
    assert len({DIRECT_REQUEST_SHA256, ASSISTED_REQUEST_SHA256}) == 2
    assert len({DIRECT_MANIFEST_SHA256, ASSISTED_MANIFEST_SHA256}) == 2


def test_both_routes_start_from_the_same_frozen_initial_geometry() -> None:
    """The invariant that makes the paired comparison interpretable."""

    from nhc_deprot_ranker.preparation.phase9b_bundle import validate_route_parity_v3

    identity = _identity()
    payloads = {}
    for route in (ROUTE_DIRECT, ROUTE_ASSISTED):
        request = build_route_request_v3(
            route=route,
            source_identity=identity,
            protocol=runner.LOCKED_PROTOCOL,
            cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
            neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
        )
        assert request.cation_xyz_sha256 == PHASE9B_CANDIDATE.cation_xyz_sha256
        assert request.neutral_xyz_sha256 == PHASE9B_CANDIDATE.neutral_xyz_sha256
        payloads[route] = build_route_payload_v3(request, source_identity=identity)
    validate_route_parity_v3(payloads[ROUTE_DIRECT], payloads[ROUTE_ASSISTED])


def test_neither_chain_depends_on_a_pre_existing_preoptimized_geometry() -> None:
    """Requiring one made step 5 depend on step 10.  It no longer does."""

    identity = _identity()
    for route in (ROUTE_DIRECT, ROUTE_ASSISTED):
        request = build_route_request_v3(
            route=route,
            source_identity=identity,
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

    identity = _identity()
    assert identity.full_assisted_campaign_source_sha256 == source
    for route in (ROUTE_DIRECT, ROUTE_ASSISTED):
        request = build_route_request_v3(
            route=route,
            source_identity=identity,
            protocol=runner.LOCKED_PROTOCOL,
            cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
            neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
        )
        body = json.loads(request.request_bytes)
        assert body["runner_source_sha256"] == source
        manifest = json.loads(
            build_route_payload_v3(request, source_identity=identity).manifest_bytes
        )
        assert manifest["source_closures"]["full_assisted_campaign_source"] == source
        assert manifest["real_permit_generated"] is False


def test_an_identity_built_against_the_superseded_digest_is_refused() -> None:
    """A v4-era request cannot be revived by pointing a new permit at it."""

    assert runner.current_runner_source_sha256() != SUPERSEDED_V8_SOURCE_SHA256
    assert SUPERSEDED_V8_SOURCE_SHA256 in _DOC.read_text(encoding="utf-8")


def test_every_superseded_generation_is_recorded(tmp_path: Path) -> None:
    """v4 through v7 are all preserved; none is deleted or relabelled."""

    del tmp_path
    text = _DOC.read_text(encoding="utf-8")
    superseded = (
        SUPERSEDED_SOURCE_SHA256,
        SUPERSEDED_V5_SOURCE_SHA256,
        SUPERSEDED_V6_SOURCE_SHA256,
        SUPERSEDED_V7_SOURCE_SHA256,
        SUPERSEDED_V8_SOURCE_SHA256,
    )
    for digest in superseded:
        assert digest in text, digest
    assert text.count("superseded_before_execution") >= 5
    assert FINAL_SOURCE_SHA256 not in superseded
    # v7's own chain is preserved rather than overwritten by v8's.
    for digest in (
        "a53c26201fd1f2989fd242681c3c382fd17cc1c88c1433cd5dcc7c0a58ec04d2",
        "f73cdb9a3a34fe49738994800a1d7d79bc0b854ae197a385c3151cce2c8305b5",
        "feaecb7b6de9e7ab0f8710b4fd9e094d019b3cc6c1f68d349dc901137ebe7659",
        "bc0534f72fe16eb69338af1eb897c3a705b71b7973825f7a4fe9e9732e236d7b",
    ):
        assert digest in text, f"a v7 identity was deleted rather than superseded: {digest}"


def test_the_superseded_identities_are_recorded_and_correctly_labelled() -> None:
    text = _DOC.read_text(encoding="utf-8")
    assert SUPERSEDED_SOURCE_SHA256 in text
    assert SUPERSEDED_V8_SOURCE_SHA256 in text
    assert "superseded_before_execution" in text
    # Never described as consumed, failed, or rejected: none of those happened.
    body = text.split("## Status of the previous identities")[1].split("## The final closure")[0]
    for wrong in ("was consumed", "were consumed", "was rejected", "were rejected"):
        assert wrong not in body


def test_the_rebaseline_record_names_what_is_still_not_wired() -> None:
    text = _DOC.read_text(encoding="utf-8")
    assert "Postflight does not exist" in text
    assert "no validated unified" in text
    assert "preflight invokes unbound `python3`" in text
    assert "failed_incomplete_environment" in text
    assert "No Phase 9B payload has been deployed" in text


def test_the_record_leaks_no_private_path_or_host() -> None:
    text = _DOC.read_text(encoding="utf-8")
    assert "/Users/" not in text and "/home/" not in text
    assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text)
    assert "@" not in text


@pytest.mark.parametrize("route", [ROUTE_DIRECT, ROUTE_ASSISTED])
def test_the_v3_request_identity_and_attempt_pairing_are_frozen(route: str) -> None:
    assert REQUEST_ID_V3 == "phase9b-lbnp-paired-split-process-v003"
    assert ROUTE_ATTEMPT_IDS_V3[route].endswith("-v003")
    assert PHASE9B_CANDIDATE.inchikey == "LBNPGYISTSLAHY-UHFFFAOYSA-N"
    assert PHASE9B_CANDIDATE.electron_count == 160
