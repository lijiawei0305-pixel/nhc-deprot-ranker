from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase9b_science_pilot_timing_benchmark.py"
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
    payload = MODULE.manifest(tmp_path)
    assert [item["relative_path"] for item in payload["files"]] == ["durable"]
