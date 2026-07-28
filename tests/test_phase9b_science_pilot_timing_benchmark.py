from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase9b_science_pilot_timing_benchmark.py"
PUBLIC_RESULT = ROOT / "docs" / "PHASE9B_SCIENCE_PILOT_V006_RESULT.json"
SPEC = importlib.util.spec_from_file_location("phase9b_science_pilot_timing_benchmark", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_speedup_direction_and_percent() -> None:
    result = MODULE.timing_comparison(100.0, 250.0)
    assert result["time_saved_seconds"] == 150.0
    assert result["speedup_ratio_pyscf_only_over_assisted"] == 2.5
    assert result["percent_time_saved"] == 60.0


def test_speedup_rejects_nonpositive_time() -> None:
    with pytest.raises(MODULE.BenchmarkError):
        MODULE.timing_comparison(0.0, 1.0)


def test_timeout_lower_bound_direction() -> None:
    result = MODULE.timeout_lower_bound(200.0, 7200.0)
    assert result["minimum_time_saved_seconds"] == 7000.0
    assert result["minimum_speedup_lower_bound"] == 36.0
    assert result["minimum_percent_time_saved_lower_bound"] == pytest.approx(97.22222222222223)


def test_external_elapsed_accepts_gnu_timeout_prefix(tmp_path: Path) -> None:
    observed = tmp_path / "elapsed"
    observed.write_text("Command exited with non-zero status 124\n7190.06\n")
    assert MODULE.read_external_elapsed(observed) == 7190.06


def test_last_geometric_observation_preserves_timeout_state() -> None:
    result = MODULE.last_geometric_observation(
        b"Step   17 : Displace = 2.4e-02/6.3e-02 (rms/max) "
        b"Grad = 6.766e-04/1.861e-03 (rms/max) "
        b"E (change) = -1407.1447765721 (-2.1e-04)\n"
    )
    assert result == {
        "last_completed_step": 17,
        "gradient_rms": 6.766e-04,
        "gradient_maximum": 1.861e-03,
        "energy_hartree": -1407.1447765721,
        "source": "geomeTRIC structured stderr line",
        "not_a_wrapper_call_count": True,
    }


def test_frozen_formula_never_accepts_aimnet_energy() -> None:
    result = MODULE.deprotonation(-10.0, -9.5)
    assert result["aimnet2_energy_used"] is False
    assert result["value_kcal_per_mol"] == pytest.approx(307.474737)


def test_frozen_endpoint_identity() -> None:
    assert MODULE.CHARGES == {"cation": 1, "neutral": 0}
    assert MODULE.MULTIPLICITIES == {"cation": 1, "neutral": 1}
    assert MODULE.SPINS == {"cation": 0, "neutral": 0}
    assert MODULE.ATOM_COUNTS == {"cation": 26, "neutral": 25}


def test_source_has_no_control_plane_or_retry() -> None:
    source = SCRIPT.read_text()
    assert "guardian" not in source.lower()
    assert "permit" not in source.lower()
    assert "campaign" not in source.lower()
    assert '"retry": False' in source
    assert '"production_accepted": False' in source


def test_manifest_excludes_runtime_tmp_and_self(tmp_path: Path) -> None:
    (tmp_path / "runtime_tmp").mkdir()
    (tmp_path / "runtime_tmp" / "checkpoint").write_bytes(b"ephemeral")
    (tmp_path / "durable").write_bytes(b"evidence")
    (tmp_path / "manifest.json").write_bytes(b"old")
    (tmp_path / "file_manifest.json").write_bytes(b"old-final")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "manifest.json").write_bytes(b"route-manifest")
    payload = MODULE.manifest(tmp_path)
    assert [item["relative_path"] for item in payload["files"]] == [
        "durable",
        "nested/manifest.json",
    ]


def test_public_partial_pass_is_formula_consistent_and_nonproduction() -> None:
    result = json.loads(PUBLIC_RESULT.read_bytes())
    timing = result["timing_comparison"]
    assisted = timing["assisted_total_seconds"]
    observed = timing["pyscf_only_observed_seconds"]
    assert result["final_outcome"] == "PARTIAL_PASS"
    assert timing["minimum_speedup_lower_bound"] == pytest.approx(observed / assisted)
    assert timing["minimum_time_saved_seconds"] == pytest.approx(observed - assisted)
    assert result["pyscf_only"]["neutral"]["final_single_point"] == "not_run"
    assert result["pyscf_only"]["deprotonation_electronic_kcal_per_mol"].startswith("unavailable")
    assert result["production_accepted"] is False
    assert result["production_label_inserted"] is False
    assert result["public_execution_gates_false"] == 11
    assert result["production_label_count"] == 71
    assert (
        result["source"]["publication_source_sha256"]
        == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    )
