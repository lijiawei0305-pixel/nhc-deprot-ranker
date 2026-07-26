"""Phase 9B one-shot permit regressions. No chemistry, no server, no compute."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nhc_deprot_ranker.quantum import phase9b_supervisor as p9b_supervisor
from nhc_deprot_ranker.quantum import worker
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_permit import (
    CONSUMED_RELATIVE,
    REMOTE_ROOT_RELATIVE,
    REQUEST_ID,
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
    Phase9BPermitValidationError,
    load_consumed_phase9b_permit,
    parse_phase9b_permit,
    render_phase9b_permit,
)

_REQ = "1" * 64
_SRC = "2" * 64
_PAY = "3" * 64
_PRE_C = "4" * 64
_PRE_N = "5" * 64
_RES: dict[str, object] = {"threads": 4, "hard_wall_timeout_seconds": 7200}


def _render(route: str, *, cation: str | None = None, neutral: str | None = None) -> bytes:
    if route == ROUTE_DIRECT:
        cation = cation or PHASE9B_CANDIDATE.cation_xyz_sha256
        neutral = neutral or PHASE9B_CANDIDATE.neutral_xyz_sha256
    else:
        cation = cation or _PRE_C
        neutral = neutral or _PRE_N
    return render_phase9b_permit(
        route=route,
        project_root="/srv/project",
        request_sha256=_REQ,
        runner_source_sha256=_SRC,
        payload_manifest_sha256=_PAY,
        cation_xyz_sha256=cation,
        neutral_xyz_sha256=neutral,
        resources=_RES,
    )


def test_direct_and_assisted_render_parse_round_trip() -> None:
    for route in (ROUTE_DIRECT, ROUTE_ASSISTED):
        permit = parse_phase9b_permit(_render(route))
        assert permit.route == route
        assert permit.attempt_id == ROUTE_ATTEMPT_IDS[route]
        assert permit.request_sha256 == _REQ
        assert permit.run_root.as_posix() == f"/srv/project/{REMOTE_ROOT_RELATIVE}/{route}"
        assert permit.consumed_path.name == Path(CONSUMED_RELATIVE).name


def test_route_constants_agree_with_supervisor_and_worker_profile() -> None:
    assert REQUEST_ID == p9b_supervisor.REQUEST_ID
    assert REMOTE_ROOT_RELATIVE == p9b_supervisor.REMOTE_ROOT_RELATIVE
    assert ROUTE_ATTEMPT_IDS[ROUTE_DIRECT] == p9b_supervisor.ROUTE_D_ATTEMPT_ID
    assert ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED] == p9b_supervisor.ROUTE_A_ATTEMPT_ID
    assert tuple(ROUTE_ATTEMPT_IDS.values()) == worker.PHASE9B_WORKER_PROFILE.attempt_ids


def test_direct_route_must_carry_the_frozen_initial_geometry() -> None:
    with pytest.raises(Phase9BPermitValidationError, match="frozen initial geometry"):
        _render(ROUTE_DIRECT, cation=_PRE_C)


def test_assisted_route_must_not_carry_the_initial_geometry() -> None:
    with pytest.raises(Phase9BPermitValidationError, match="not the initial geometry"):
        _render(
            ROUTE_ASSISTED,
            cation=PHASE9B_CANDIDATE.cation_xyz_sha256,
            neutral=PHASE9B_CANDIDATE.neutral_xyz_sha256,
        )


def test_unknown_route_fails_closed() -> None:
    with pytest.raises(Phase9BPermitValidationError, match="unknown Phase 9B route"):
        _render("sideways")


def test_retired_qxh_identity_cannot_parse() -> None:
    payload = json.loads(_render(ROUTE_DIRECT))
    payload["identity"]["inchikey"] = "QXHIEGFUWOLQIJ-UHFFFAOYSA-N"
    raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(Phase9BPermitValidationError, match="candidate drifted"):
        parse_phase9b_permit(raw)


def test_attempt_id_must_match_its_route() -> None:
    payload = json.loads(_render(ROUTE_DIRECT))
    payload["identity"]["attempt_id"] = ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED]
    raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(Phase9BPermitValidationError, match="does not match its route"):
        parse_phase9b_permit(raw)


def test_path_layout_drift_fails_closed() -> None:
    payload = json.loads(_render(ROUTE_DIRECT))
    payload["paths"]["output_root"] = "/srv/elsewhere/output"
    raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(Phase9BPermitValidationError, match="path layout drifted"):
        parse_phase9b_permit(raw)


def test_duplicate_json_keys_are_rejected() -> None:
    raw = _render(ROUTE_DIRECT)
    text = raw.decode()
    injected = text.replace('"schema_version"', '"schema_version": "x", "schema_version"', 1)
    with pytest.raises(Phase9BPermitValidationError, match="duplicate key"):
        parse_phase9b_permit(injected.encode())


def test_electron_count_drift_fails_closed() -> None:
    payload = json.loads(_render(ROUTE_DIRECT))
    payload["identity"]["electron_count"] = 120
    raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(Phase9BPermitValidationError, match="electron count drifted"):
        parse_phase9b_permit(raw)


def _consumed_layout(tmp_path: Path, raw: bytes, *, mode: int = 0o400) -> Path:
    import hashlib

    permit = parse_phase9b_permit(raw)
    # Rebuild the same layout under tmp_path as project root.
    rebuilt = render_phase9b_permit(
        route=permit.route,
        project_root=tmp_path.as_posix(),
        request_sha256=permit.request_sha256,
        runner_source_sha256=permit.runner_source_sha256,
        payload_manifest_sha256=permit.payload_manifest_sha256,
        cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
        neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
        resources=_RES,
    )
    parsed = parse_phase9b_permit(rebuilt)
    consumed = parsed.consumed_path
    consumed.parent.mkdir(parents=True)
    consumed.write_bytes(rebuilt)
    os.chmod(consumed, mode)
    globals()["_LAST_SHA"] = hashlib.sha256(rebuilt).hexdigest()
    return consumed


def test_consumed_load_round_trip(tmp_path: Path) -> None:
    consumed_path = _consumed_layout(tmp_path, _render(ROUTE_DIRECT))
    loaded = load_consumed_phase9b_permit(
        consumed_path,
        expected_route=ROUTE_DIRECT,
        expected_permit_sha256=globals()["_LAST_SHA"],
        expected_request_sha256=_REQ,
        expected_runner_source_sha256=_SRC,
        expected_payload_manifest_sha256=_PAY,
    )
    assert loaded.permit.attempt_id == ROUTE_ATTEMPT_IDS[ROUTE_DIRECT]
    assert loaded.consumed_sha256 == globals()["_LAST_SHA"]


def test_reappeared_ready_permit_breaks_the_one_shot_proof(tmp_path: Path) -> None:
    consumed_path = _consumed_layout(tmp_path, _render(ROUTE_DIRECT))
    (consumed_path.parent / "permit.ready.json").write_bytes(b"{}")
    with pytest.raises(Phase9BPermitValidationError, match="one-shot proof failed"):
        load_consumed_phase9b_permit(
            consumed_path,
            expected_route=ROUTE_DIRECT,
            expected_permit_sha256=globals()["_LAST_SHA"],
            expected_request_sha256=_REQ,
            expected_runner_source_sha256=_SRC,
            expected_payload_manifest_sha256=_PAY,
        )


def test_wrong_file_mode_fails_closed(tmp_path: Path) -> None:
    consumed_path = _consumed_layout(tmp_path, _render(ROUTE_DIRECT), mode=0o600)
    with pytest.raises(Phase9BPermitValidationError, match="file identity drifted"):
        load_consumed_phase9b_permit(
            consumed_path,
            expected_route=ROUTE_DIRECT,
            expected_permit_sha256=globals()["_LAST_SHA"],
            expected_request_sha256=_REQ,
            expected_runner_source_sha256=_SRC,
            expected_payload_manifest_sha256=_PAY,
        )


def test_expected_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    consumed_path = _consumed_layout(tmp_path, _render(ROUTE_DIRECT))
    with pytest.raises(Phase9BPermitValidationError, match="differs from the expected permit"):
        load_consumed_phase9b_permit(
            consumed_path,
            expected_route=ROUTE_DIRECT,
            expected_permit_sha256="f" * 64,
            expected_request_sha256=_REQ,
            expected_runner_source_sha256=_SRC,
            expected_payload_manifest_sha256=_PAY,
        )


def test_route_expectation_mismatch_fails_closed(tmp_path: Path) -> None:
    consumed_path = _consumed_layout(tmp_path, _render(ROUTE_DIRECT))
    with pytest.raises(Phase9BPermitValidationError, match="differs from the expected route"):
        load_consumed_phase9b_permit(
            consumed_path,
            expected_route=ROUTE_ASSISTED,
            expected_permit_sha256=globals()["_LAST_SHA"],
            expected_request_sha256=_REQ,
            expected_runner_source_sha256=_SRC,
            expected_payload_manifest_sha256=_PAY,
        )


def test_module_imports_no_chemistry_and_declares_no_label() -> None:
    from nhc_deprot_ranker.quantum import phase9b_permit as permit_module

    assert permit_module.__file__ is not None
    source = Path(permit_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("import pyscf", "import torch", "import aimnet", "627.509474", "kcal"):
        assert forbidden not in source, forbidden
