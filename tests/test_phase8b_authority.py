"""No-chemistry tests for the exact post-consumption Phase 8B authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import pytest

from nhc_deprot_ranker.quantum import phase8b_authority as authority
from nhc_deprot_ranker.quantum.phase8b_permit import (
    FROZEN_ATTEMPT_ID,
    FROZEN_INCHIKEY,
    FROZEN_INPUT_SHA256,
    FROZEN_PROTOCOL_SHA256,
    FROZEN_REQUEST_ID,
    ConsumedPhase8BPermit,
    Phase8BPermit,
)


@dataclass(frozen=True)
class _Atom:
    element: str


@dataclass(frozen=True)
class _Geometry:
    atoms: tuple[_Atom, ...]


@dataclass(frozen=True)
class _Endpoint:
    xyz_sha256: str
    charge: int
    multiplicity: int
    electron_count: int
    geometry: _Geometry


@dataclass(frozen=True)
class _Request:
    schema_version: str
    request_id: str
    inchikey: str
    execution_authorized: bool
    timeout_seconds: int
    runner_source_sha256: str
    request_path: Path
    request_sha256: str
    protocol_sha256: str
    cation: _Endpoint
    neutral: _Endpoint


def _endpoint_map() -> dict[str, object]:
    mapping = {"C2_carbene": 4, "N1": 3, "N3": 5}
    return {
        "schema_version": "phase7.endpoint_atom_map.v1",
        "inchikey": FROZEN_INCHIKEY,
        "mapping_basis": {
            "cation": "validated_legacy_m2_cation_map",
            "neutral": "independent_graph_shared_five_membered_ring",
        },
        "cation": mapping,
        "neutral": mapping,
    }


def _geometry_validation() -> dict[str, object]:
    mapping = {"C2_carbene": 4, "N1": 3, "N3": 5}
    return {
        "schema_version": "phase7.geometry_validation.v1",
        "validation_status": "passed",
        "expected_candidates": 4,
        "validated_candidates": 4,
        "quantum_chemistry_run": False,
        "hessian_computed": False,
        "replacement_candidate_used": False,
        "endpoint_atom_map_sha256": {
            "QXHIEGFUWOLQIJ-UHFFFAOYSA-N_endpoint_atom_map.json": FROZEN_INPUT_SHA256[
                "endpoint_atom_map"
            ]
        },
        "candidate_results": [
            {
                "inchikey": FROZEN_INCHIKEY,
                "status": "passed",
                "geometry_quality": "initial_force_field_geometry",
                "force_field_convergence": "unavailable_legacy_m2",
                "checks": {
                    "atom_counts": {"cation": 22, "neutral": 21},
                    "formal_charges": {"cation": 1, "neutral": 0},
                    "heavy_element_multiset": {"C": 7, "N": 6, "O": 4},
                    "hydrogen_counts": {"cation": 5, "neutral": 4},
                    "legacy_cation_map": mapping,
                    "neutral_graph_map": mapping,
                    "one_c2_proton_difference": True,
                },
                "files": {
                    "QXHIEGFUWOLQIJ-UHFFFAOYSA-N_atom_map.json": FROZEN_INPUT_SHA256[
                        "legacy_atom_map"
                    ],
                    "QXHIEGFUWOLQIJ-UHFFFAOYSA-N_cation.xyz": FROZEN_INPUT_SHA256["cation_xyz"],
                    "QXHIEGFUWOLQIJ-UHFFFAOYSA-N_neutral.xyz": FROZEN_INPUT_SHA256["neutral_xyz"],
                },
            }
        ],
    }


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[_Request, ConsumedPhase8BPermit, Path]:
    project = (tmp_path / "project").resolve()
    run = project / "data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001"
    request_path = run / "input/request.json"
    output = run / "runtime/output"
    private = run / "private"
    request_path.parent.mkdir(parents=True)
    output.parent.mkdir(parents=True)
    private.mkdir()
    run.chmod(0o700)
    private.chmod(0o700)
    output.parent.chmod(0o700)
    request_path.write_bytes(b"frozen request\n")
    request_path.chmod(0o640)
    request_sha = hashlib.sha256(request_path.read_bytes()).hexdigest()
    source_sha = "a" * 64
    payload_sha = "b" * 64
    permit_sha = "c" * 64
    permit = Phase8BPermit(
        request_sha256=request_sha,
        runner_source_sha256=source_sha,
        payload_manifest_sha256=payload_sha,
        project_root=project,
        run_root=run,
        request_path=request_path,
        output_root=output,
        ready_path=private / "permit.ready.json",
        consumed_path=private / "permit.consumed.json",
        raw_bytes=b"permit\n",
        permit_sha256=permit_sha,
    )
    consumed = ConsumedPhase8BPermit(
        permit=permit,
        consumed_path=permit.consumed_path,
        consumed_sha256=permit_sha,
    )
    heavy = ("N", "C", "C", "N", "C", "N", "C", "C", "N", "C", "N", "O", "O", "C", "N", "O", "O")
    cation_elements = tuple(_Atom(item) for item in (*heavy, "H", "H", "H", "H", "H"))
    neutral_elements = tuple(_Atom(item) for item in (*heavy, "H", "H", "H", "H"))
    request = _Request(
        schema_version="nhc-two-endpoint-request-v1",
        request_id=FROZEN_REQUEST_ID,
        inchikey=FROZEN_INCHIKEY,
        execution_authorized=True,
        timeout_seconds=7_200,
        runner_source_sha256=source_sha,
        request_path=request_path,
        request_sha256=request_sha,
        protocol_sha256=FROZEN_PROTOCOL_SHA256,
        cation=_Endpoint(FROZEN_INPUT_SHA256["cation_xyz"], 1, 1, 120, _Geometry(cation_elements)),
        neutral=_Endpoint(
            FROZEN_INPUT_SHA256["neutral_xyz"], 0, 1, 120, _Geometry(neutral_elements)
        ),
    )

    def fake_read(path: Path, *, expected_sha256: str, label: str) -> dict[str, object]:
        del expected_sha256, label
        if path.name.endswith("endpoint_atom_map.json"):
            return _endpoint_map()
        if path.name.endswith("legacy_atom_map.json"):
            return {"C2_carbene": 4, "N1": 3, "N3": 5}
        if path.name == "phase7_geometry_validation.json":
            return _geometry_validation()
        raise AssertionError(f"unexpected evidence path: {path}")

    monkeypatch.setattr(authority, "_read_bound_json", fake_read)
    monkeypatch.setattr(authority, "_validate_payload_manifest", lambda *args, **kwargs: {})
    return request, consumed, output


def _validate(
    request: _Request,
    consumed: ConsumedPhase8BPermit,
    output: Path,
    *,
    attempt_id: str = FROZEN_ATTEMPT_ID,
    require_output_absent: bool = True,
) -> authority.ExactPhase8BAuthority:
    return authority.validate_exact_phase8b_authority(
        cast(authority.Phase8BRequestLike, request),
        consumed,
        output_root=output,
        attempt_id=attempt_id,
        expected_source_relative_paths=("nhc_deprot_ranker/quantum/two_endpoint.py",),
        require_output_absent=require_output_absent,
    )


def test_exact_request_permit_map_and_120_electron_closure_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, consumed, output = _fixture(tmp_path, monkeypatch)
    result = _validate(request, consumed, output)
    assert result.request_sha256 == request.request_sha256
    assert result.permit_sha256 == consumed.consumed_sha256
    assert result.electron_count == 120


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", "phase8b-other"),
        ("inchikey", "IJWCXRPLHNQISE-UHFFFAOYSA-N"),
        ("execution_authorized", False),
        ("timeout_seconds", 7_201),
        ("protocol_sha256", "d" * 64),
        ("runner_source_sha256", "e" * 64),
        ("request_sha256", "f" * 64),
    ],
)
def test_request_or_source_drift_is_rejected_before_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    request, consumed, output = _fixture(tmp_path, monkeypatch)
    drifted = replace(request, **{field: value})
    with pytest.raises(authority.Phase8BAuthorityError):
        _validate(drifted, consumed, output)


@pytest.mark.parametrize(
    ("endpoint_name", "field", "value"),
    [
        ("cation", "xyz_sha256", "0" * 64),
        ("cation", "charge", 0),
        ("cation", "electron_count", 119),
        ("neutral", "multiplicity", 3),
        ("neutral", "electron_count", 122),
    ],
)
def test_endpoint_hash_state_and_exact_electron_count_are_mandatory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint_name: str,
    field: str,
    value: object,
) -> None:
    request, consumed, output = _fixture(tmp_path, monkeypatch)
    endpoint = replace(getattr(request, endpoint_name), **{field: value})
    drifted = replace(request, **{endpoint_name: endpoint})
    with pytest.raises(authority.Phase8BAuthorityError, match="endpoint"):
        _validate(drifted, consumed, output)


def test_attempt_output_path_and_n1_c2_n3_order_are_mandatory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, consumed, output = _fixture(tmp_path, monkeypatch)
    with pytest.raises(authority.Phase8BAuthorityError, match="identity"):
        _validate(request, consumed, output, attempt_id="attempt-phase8b-other")
    with pytest.raises(authority.Phase8BAuthorityError, match="output"):
        _validate(request, consumed, output.with_name("other"))
    bad_cation_atoms = list(request.cation.geometry.atoms)
    bad_neutral_atoms = list(request.neutral.geometry.atoms)
    for atoms in (bad_cation_atoms, bad_neutral_atoms):
        atoms[4], atoms[8] = atoms[8], atoms[4]
    bad_cation = replace(request.cation, geometry=_Geometry(tuple(bad_cation_atoms)))
    bad_neutral = replace(request.neutral, geometry=_Geometry(tuple(bad_neutral_atoms)))
    with pytest.raises(authority.Phase8BAuthorityError, match="N1/C2/N3"):
        _validate(replace(request, cation=bad_cation, neutral=bad_neutral), consumed, output)


def test_pre_spawn_rejects_existing_output_but_worker_recheck_can_validate_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, consumed, output = _fixture(tmp_path, monkeypatch)
    output.mkdir()
    with pytest.raises(authority.Phase8BAuthorityError, match="resume is prohibited"):
        _validate(request, consumed, output)
    result = _validate(request, consumed, output, require_output_absent=False)
    assert result.electron_count == 120


def test_forged_stored_120_count_cannot_hide_wrong_geometry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, consumed, output = _fixture(tmp_path, monkeypatch)
    forged = replace(
        request.cation,
        electron_count=120,
        geometry=_Geometry(tuple(_Atom(item) for item in ("C", "C", "C", "N", "C", "N"))),
    )
    with pytest.raises(authority.Phase8BAuthorityError, match="composition"):
        _validate(replace(request, cation=forged), consumed, output)


def test_phase7_c2_proton_and_map_evidence_must_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, consumed, output = _fixture(tmp_path, monkeypatch)
    bad_validation = _geometry_validation()
    candidates = cast(list[dict[str, object]], bad_validation["candidate_results"])
    checks = cast(dict[str, object], candidates[0]["checks"])
    checks["one_c2_proton_difference"] = False

    def bad_read(path: Path, *, expected_sha256: str, label: str) -> dict[str, object]:
        del expected_sha256, label
        if path.name == "phase7_geometry_validation.json":
            return bad_validation
        if path.name.endswith("endpoint_atom_map.json"):
            return _endpoint_map()
        return {"C2_carbene": 4, "N1": 3, "N3": 5}

    monkeypatch.setattr(authority, "_read_bound_json", bad_read)
    with pytest.raises(authority.Phase8BAuthorityError, match="chemistry closure"):
        _validate(request, consumed, output)


def test_bound_evidence_reader_rejects_hash_mode_and_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()
    path = (tmp_path / "evidence.json").resolve()
    raw = b'{"passed": true}\n'
    path.write_bytes(raw)
    path.chmod(0o640)
    expected = hashlib.sha256(raw).hexdigest()
    assert authority._read_bound_json(  # pyright: ignore[reportPrivateUsage]
        path, expected_sha256=expected, label="synthetic evidence"
    ) == {"passed": True}
    path.chmod(0o600)
    with pytest.raises(authority.Phase8BAuthorityError, match="filesystem"):
        authority._read_bound_json(  # pyright: ignore[reportPrivateUsage]
            path, expected_sha256=expected, label="synthetic evidence"
        )
    path.chmod(0o640)
    with pytest.raises(authority.Phase8BAuthorityError, match="SHA256"):
        authority._read_bound_json(  # pyright: ignore[reportPrivateUsage]
            path, expected_sha256="0" * 64, label="synthetic evidence"
        )
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(authority.Phase8BAuthorityError, match="symlink"):
        authority._read_bound_json(  # pyright: ignore[reportPrivateUsage]
            link, expected_sha256=expected, label="synthetic evidence"
        )


def test_bound_reader_rejects_same_bytes_replaced_during_fd_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = (tmp_path / "evidence.json").resolve()
    replacement = tmp_path / "replacement.json"
    raw = b'{"passed": true}\n'
    path.write_bytes(raw)
    path.chmod(0o640)
    replacement.write_bytes(raw)
    replacement.chmod(0o640)
    expected = hashlib.sha256(raw).hexdigest()
    real_read = authority.os.read
    replaced = False

    def replace_after_first_read(descriptor: int, byte_count: int) -> bytes:
        nonlocal replaced
        chunk = real_read(descriptor, byte_count)
        if chunk and not replaced:
            replaced = True
            replacement.replace(path)
        return chunk

    monkeypatch.setattr(authority.os, "read", replace_after_first_read)
    with pytest.raises(authority.Phase8BAuthorityError, match="changed while read"):
        authority._read_bound_json(  # pyright: ignore[reportPrivateUsage]
            path, expected_sha256=expected, label="synthetic evidence"
        )
