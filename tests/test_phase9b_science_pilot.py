from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase9b_science_pilot.py"


def _load_pilot() -> Any:
    spec = importlib.util.spec_from_file_location("phase9b_science_pilot", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_science_pilot_freezes_candidate_formula_and_single_pair() -> None:
    pilot = _load_pilot()

    assert pilot.PILOT_KIND == "science_pilot_only"
    assert pilot.CANDIDATE == "LBNPGYISTSLAHY-UHFFFAOYSA-N"
    assert pilot.ENDPOINTS == ("cation", "neutral")
    assert pilot.CHARGES == {"cation": 1, "neutral": 0}
    assert pilot.MULTIPLICITIES == {"cation": 1, "neutral": 1}
    assert pilot.ATOM_COUNTS == {"cation": 26, "neutral": 25}
    assert pilot.ATOM_MAP == {"C2_carbene": 14, "N1": 8, "N3": 15}
    cation = -100.0
    neutral = -99.0
    observed = (neutral - cation) * pilot.HARTREE_TO_KCAL_MOL + pilot.GAS_PROTON_KCAL_MOL
    assert observed == pytest.approx(621.229474, abs=1.0e-12)
    assert pilot.LABEL_FORMULA == ("((E_neutral_PySCF - E_cation_PySCF) * 627.509474) - 6.28")


def test_science_pilot_identity_matches_frozen_generation() -> None:
    pilot = _load_pilot()
    generation = json.loads((ROOT / "docs/PHASE9B_PAIRED_GENERATION_V3.json").read_text())
    assisted_request = generation["routes"]["assisted"]["request"]
    preoptimization = assisted_request["preoptimization"]

    assert preoptimization["weight_filename"] == pilot.WEIGHT_FILENAME
    assert preoptimization["weight_bytes"] == pilot.WEIGHT_BYTES
    assert preoptimization["weight_sha256"] == pilot.WEIGHT_SHA256


def test_handoff_is_same_inode_and_exact_bytes(tmp_path: Path) -> None:
    pilot = _load_pilot()
    source = tmp_path / "aimnet2" / "cation" / "final.xyz"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"1\nscience_pilot_only\nH 0.0 0.0 0.0\n")
    destination = tmp_path / "pyscf" / "cation" / "input.xyz"

    evidence = pilot._link_authoritative_input(source, destination, endpoint="cation")

    assert source.stat().st_ino == destination.stat().st_ino
    assert source.read_bytes() == destination.read_bytes()
    assert evidence["same_device_inode"] is True
    assert evidence["bytes_equal"] is True
    assert evidence["method"] == "same_inode_hardlink_no_copy_no_reserialization"
    assert evidence["source_relative"] == "aimnet2/cation/final.xyz"
    assert evidence["input_relative"] == "pyscf/cation/input.xyz"


def test_handoff_refuses_nonexclusive_source(tmp_path: Path) -> None:
    pilot = _load_pilot()
    source = tmp_path / "aimnet2" / "cation" / "final.xyz"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"bytes")
    alias = tmp_path / "existing-alias"
    alias.hardlink_to(source)

    with pytest.raises(pilot.PilotError, match="exclusive regular file"):
        pilot._link_authoritative_input(
            source,
            tmp_path / "pyscf" / "cation" / "input.xyz",
            endpoint="cation",
        )


def test_handoff_must_match_durable_aimnet_receipt() -> None:
    pilot = _load_pilot()
    handoff = {"sha256": "a" * 64, "byte_count": 123}
    summary: dict[str, Any] = {
        "endpoints": {
            "cation": {
                "status": "success",
                "final_xyz": {"sha256": "a" * 64, "bytes": 123},
            }
        }
    }

    pilot._verify_handoff_against_aimnet_summary(
        aimnet_summary=summary, endpoint="cation", handoff=handoff
    )
    summary["endpoints"]["cation"]["final_xyz"]["sha256"] = "b" * 64
    with pytest.raises(pilot.HandoffFailure, match="durable AIMNet2"):
        pilot._verify_handoff_against_aimnet_summary(
            aimnet_summary=summary, endpoint="cation", handoff=handoff
        )


def test_main_persists_inconclusive_setup_failure(tmp_path: Path) -> None:
    pilot = _load_pilot()
    root = tmp_path / "science_pilot_lbn_v001"
    root.mkdir()

    with pytest.raises(pilot.PilotError, match="source root"):
        pilot.main(
            [
                "pyscf",
                "--pilot-root",
                str(root),
                "--source-root",
                str(tmp_path / "missing-source"),
                "--source-commit",
                "0" * 40,
            ]
        )

    result = json.loads((root / "result.json").read_text())
    assert result["final_outcome"] == "INCONCLUSIVE"
    assert result["production_accepted"] is False
    assert result["production_label_written"] is False


def test_main_classifies_exact_handoff_failure_as_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pilot = _load_pilot()
    root = tmp_path / "science_pilot_lbn_v001"
    root.mkdir()

    def fail_handoff(_args: object) -> int:
        raise pilot.HandoffFailure("exact handoff mismatch")

    monkeypatch.setattr(pilot, "_pyscf_command", fail_handoff)
    with pytest.raises(pilot.HandoffFailure):
        pilot.main(
            [
                "pyscf",
                "--pilot-root",
                str(root),
                "--source-root",
                str(tmp_path),
                "--source-commit",
                "0" * 40,
            ]
        )

    result = json.loads((root / "result.json").read_text())
    assert result["final_outcome"] == "FAIL"
    assert result["failure"]["exception_class"] == "HandoffFailure"


def test_geometry_sanity_helpers_reject_nonfinite_and_measure_distance() -> None:
    pilot = _load_pilot()
    raw = b"2\nfixture\nH 0.0 0.0 0.0\nH 0.0 0.0 0.74\n"
    elements, coordinates = pilot._parse_xyz_minimal(raw)

    assert elements == ("H", "H")
    assert pilot._minimum_pair_distance(coordinates) == pytest.approx(0.74)
    with pytest.raises(pilot.PilotError, match="non-finite"):
        pilot._parse_xyz_minimal(b"1\nfixture\nH nan 0.0 0.0\n")


def test_pilot_source_is_outside_v9_runner_closure() -> None:
    manifest = json.loads((ROOT / "docs/PHASE9B_RUNNER_SOURCE_V9_MANIFEST.json").read_text())
    encoded = json.dumps(manifest, sort_keys=True)

    assert "scripts/phase9b_science_pilot.py" not in encoded
    assert "tests/test_phase9b_science_pilot.py" not in encoded


def test_production_source_gates_remain_closed() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from nhc_deprot_ranker.quantum import phase9b_aimnet2_runtime, two_endpoint

    assert phase9b_aimnet2_runtime.EXECUTION_AUTHORIZED is False
    assert two_endpoint.EXECUTION_AUTHORIZED is False
