from __future__ import annotations

import dataclasses
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts/phase9b_parent_level_protocol_audit.py"
BENCHMARK_PATH = ROOT / "scripts/phase9b_parent_level_paired_benchmark.py"
TRAINING_PATH = ROOT / "scripts/phase9b_parent_level_training_data.py"
SPLIT_PATH = ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json"
REJECTED_SPLIT_PATH = ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V001_REJECTION.json"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


audit = _load(AUDIT_PATH, "phase9b_parent_level_protocol_audit_test")
benchmark = _load(BENCHMARK_PATH, "phase9b_parent_level_paired_benchmark_test")
training = _load(TRAINING_PATH, "phase9b_parent_level_training_data_test")


def test_parent_protocol_identity_is_exact() -> None:
    protocol = audit.protocol_identity()
    assert protocol["pyscf_xc_alias"] == "wb97m-d3bj"
    assert protocol["basis"] == "def2-tzvpp"
    assert protocol["grid_level_selected_after_audit"] == 4
    assert protocol["vv10_nonlocal_correlation"] is False
    assert protocol["dispersion"] == {
        "version": "d3bj",
        "damping": "Becke-Johnson rational",
        "parameters": {"s6": 1.0, "s8": 0.3908, "a1": 0.566, "a2": 3.128},
        "two_body": True,
        "atm_three_body": False,
    }


def test_benchmark_protocol_matches_audit_projection() -> None:
    protocol = benchmark.protocol()
    assert protocol["pyscf_xc_alias"] == audit.PARENT_XC
    assert protocol["basis"].lower() == audit.PARENT_BASIS
    assert protocol["grid_level"] == 4
    assert protocol["atm"] is False
    assert protocol["vv10"] is False
    assert benchmark.protocols_equal(protocol, protocol)


def test_d3_comparison_preserves_signed_differences() -> None:
    left = {
        "d3_energy_hartree": -0.1,
        "d3_gradient_hartree_per_bohr": [[1.0, 2.0, 3.0]],
        "d3_parameters": audit.PARENT_D3_PARAMETERS,
        "atm_three_body": False,
    }
    right = {
        "d3_energy_hartree": -0.2,
        "d3_gradient_hartree_per_bohr": [[0.5, 2.5, 2.0]],
        "d3_parameters": audit.PARENT_D3_PARAMETERS,
        "atm_three_body": False,
    }
    result = audit.compare_d3(left, right)
    assert result["energy_difference_hartree"] == pytest.approx(0.1)
    assert result["gradient_max_difference_hartree_per_bohr"] == pytest.approx(1.0)
    assert result["same_parameters"] is True
    assert result["two_body_both"] is True


def test_grid_selection_keeps_raw_difference_and_chooses_level_four() -> None:
    level3 = {
        "total_energy_hartree": -10.0,
        "d3_energy_hartree": -0.1,
        "gradient_rms_hartree_per_bohr": 0.2,
        "gradient_max_hartree_per_bohr": 0.3,
        "scf_cycles": 8,
        "wall_seconds": 10.0,
    }
    level4 = {
        "total_energy_hartree": -10.1,
        "d3_energy_hartree": -0.1,
        "gradient_rms_hartree_per_bohr": 0.1,
        "gradient_max_hartree_per_bohr": 0.2,
        "scf_cycles": 9,
        "wall_seconds": 12.0,
    }
    result = audit.grid_difference(level3, level4)
    assert result["total_energy_level4_minus_level3_hartree"] == pytest.approx(-0.1)
    assert result["preregistered_numeric_threshold"] is False
    assert result["selected_grid_level"] == 4


def test_speedup_direction_is_pure_over_assisted() -> None:
    result = benchmark.timing_comparison(100.0, 1000.0)
    assert result["speedup_group_b_over_group_a"] == 10.0
    assert result["time_saved_seconds"] == 900.0
    assert result["percent_saved"] == 90.0


def test_timeout_produces_lower_bound_only() -> None:
    result = benchmark.timeout_lower_bound(100.0, 2100.0)
    assert result["minimum_speedup_lower_bound"] == 21.0
    assert "speedup_group_b_over_group_a" not in result


def test_label_uses_only_parent_endpoint_energies() -> None:
    result = benchmark.deprotonation(-10.0, -9.5)
    assert result["aimnet2_energy_used"] is False
    assert result["value_kcal_per_mol"] == pytest.approx(0.5 * 627.509474 - 6.28)
    with pytest.raises(benchmark.BenchmarkError):
        benchmark.deprotonation(math.nan, -9.5)


def test_frozen_endpoint_identity() -> None:
    assert benchmark.CHARGES == {"cation": 1, "neutral": 0}
    assert benchmark.MULTIPLICITIES == {"cation": 1, "neutral": 1}
    assert benchmark.ATOM_COUNTS == {"cation": 26, "neutral": 25}
    assert benchmark.ELECTRONS == 160
    assert benchmark.INPUT_SHA256 == {
        "cation": "543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286",
        "neutral": "af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8",
    }


def test_parent_worker_accepts_explicit_frozen_candidate_identity() -> None:
    args = benchmark.parser().parse_args(
        [
            "parent-worker",
            "--route",
            "pure_pyscf",
            "--route-limit-seconds",
            "86400",
            "--threads",
            "28",
            "--cpu-list",
            "28-55",
            "--max-memory-mb",
            "64000",
            "--candidate",
            "QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
            "--electron-count",
            "120",
            "--cation-atom-count",
            "22",
            "--neutral-atom-count",
            "21",
            "--cation-sha256",
            "a" * 64,
            "--neutral-sha256",
            "b" * 64,
            "--root",
            "/tmp/root",
            "--source-root",
            "/tmp/src",
            "--pilot-helper",
            "/tmp/pilot.py",
            "--sp-helper",
            "/tmp/sp.py",
            "--v006-helper",
            "/tmp/v006.py",
            "--cation-input",
            "/tmp/cation.xyz",
            "--neutral-input",
            "/tmp/neutral.xyz",
        ]
    )
    assert args.candidate == "QXHIEGFUWOLQIJ-UHFFFAOYSA-N"
    assert args.electron_count == 120
    assert args.cation_atom_count == 22
    assert args.neutral_atom_count == 21
    assert args.cation_sha256 == "a" * 64
    assert args.neutral_sha256 == "b" * 64


def test_parent_worker_training_frames_are_explicit_opt_in() -> None:
    args = benchmark.parser().parse_args(
        [
            "parent-worker",
            "--route",
            "pure_pyscf",
            "--route-limit-seconds",
            "100",
            "--threads",
            "1",
            "--cpu-list",
            "0",
            "--max-memory-mb",
            "1000",
            "--record-training-frames",
            "--training-data-helper",
            str(TRAINING_PATH),
            "--root",
            "/tmp/root",
            "--source-root",
            "/tmp/src",
            "--pilot-helper",
            "/tmp/pilot.py",
            "--sp-helper",
            "/tmp/sp.py",
            "--v006-helper",
            "/tmp/v006.py",
            "--cation-input",
            "/tmp/cation.xyz",
            "--neutral-input",
            "/tmp/neutral.xyz",
        ]
    )
    assert args.record_training_frames is True
    assert args.training_data_helper == str(TRAINING_PATH)


def test_training_recorder_writes_energy_gradient_and_force(tmp_path: Path) -> None:
    class Array:
        def __init__(self, value: list[list[float]]) -> None:
            self.value = value

        def tolist(self) -> list[list[float]]:
            return self.value

    class Molecule:
        natm = 2
        charge = 1
        spin = 0
        nelectron = 14

        @staticmethod
        def atom_symbol(index: int) -> str:
            return ("C", "N")[index]

        @staticmethod
        def atom_coords(*, unit: str) -> Array:
            assert unit == "Bohr"
            return Array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]])

    class Scanner:
        converged = True

    recorder = training.TrainingFrameRecorder(
        root=tmp_path / "training", candidate="AAAAAAAAAAAAAA-BBBBBBBBBB-C", source_sha256="a" * 64
    )
    receipt = recorder.capture(
        {
            "g_scanner": Scanner(),
            "mol": Molecule(),
            "energy": -10.0,
            "gradients": Array([[0.1, 0.2, 0.3], [-0.1, -0.2, -0.3]]),
        },
        endpoint="cation",
    )
    payload = json.loads((tmp_path / "training/cation/frame_0000.json").read_text())
    assert receipt["frame_index"] == 0
    assert payload["energy_hartree"] == -10.0
    assert payload["gradient_hartree_per_bohr"][0] == [0.1, 0.2, 0.3]
    assert payload["forces_hartree_per_bohr"][0] == [-0.1, -0.2, -0.3]
    assert payload["total_energy_includes_two_body_d3_bj"] is True


def test_parent_geometric_callback_records_after_convergence_check() -> None:
    calls: list[str] = []

    class OriginalD3:
        @staticmethod
        def DFTD3Dispersion(*_: object, **__: object) -> object:
            return object()

    class OriginalSolver:
        @staticmethod
        def kernel(method: object, *positional: object, **kwargs: object) -> object:
            del method, positional
            callback = kwargs["callback"]
            assert callable(callback)
            callback({"frame": 1})
            return "complete"

    @dataclasses.dataclass(frozen=True)
    class Modules:
        dftd3: object
        geometric_solver: object

    class Base:
        def __init__(self) -> None:
            self._pilot_context: tuple[str, str, str] | None = None

        @staticmethod
        def _load_modules() -> Modules:
            return Modules(OriginalD3, OriginalSolver)

    class Factory:
        @staticmethod
        def build(module: object) -> Base:
            del module
            return Base()

    class Pilot:
        _SciencePilotPySCFBackend = Factory

    class Recorder:
        @staticmethod
        def capture(environment: dict[str, object], *, endpoint: str) -> None:
            assert environment == {"frame": 1}
            assert endpoint == "cation"
            calls.append("recorded")

    backend = benchmark.build_parent_backend(
        pilot=Pilot(), module=object(), training_recorder=Recorder()
    )
    backend._pilot_context = ("cation", "optimization", "standard")
    modules = backend._load_modules()

    def convergence_check(environment: dict[str, object]) -> None:
        assert environment == {"frame": 1}
        calls.append("checked")

    assert modules.geometric_solver.kernel(object(), callback=convergence_check) == "complete"
    assert calls == ["checked", "recorded"]


def test_finetune_split_is_molecule_disjoint_and_final_test_is_locked() -> None:
    payload = json.loads(SPLIT_PATH.read_text())
    by_split = {
        name: {item["candidate"] for item in payload[name]}
        for name in ("train", "validation", "final_test")
    }
    identities = [candidate for candidates in by_split.values() for candidate in candidates]
    assert len(identities) == len(set(identities))
    assert all(by_split.values())
    assert not (by_split["train"] & by_split["validation"])
    assert not (by_split["train"] & by_split["final_test"])
    assert not (by_split["validation"] & by_split["final_test"])
    assert payload["leakage_rules"]["final_test_excluded_from_training_and_model_selection"]
    rejected = json.loads(REJECTED_SPLIT_PATH.read_text())
    assert rejected["classification"] == "rejected_before_launch"
    assert rejected["candidate_launched"] is False


def test_no_disallowed_rescue_program_or_batch_framework() -> None:
    source = (AUDIT_PATH.read_text() + BENCHMARK_PATH.read_text()).lower()
    forbidden = ("x" + "tb", "g" + "fn", "sub" + "mit", "sl" + "urm")
    assert all(word not in source for word in forbidden)
    assert "second_pure_pyscf_candidate" in source


def test_parent_files_are_outside_production_source() -> None:
    assert AUDIT_PATH.parent.name == "scripts"
    assert BENCHMARK_PATH.parent.name == "scripts"
    assert "src/nhc_deprot_ranker/quantum" not in AUDIT_PATH.as_posix()
    assert "src/nhc_deprot_ranker/quantum" not in BENCHMARK_PATH.as_posix()


def test_group_b_worker_requires_full_optimization_call() -> None:
    source = BENCHMARK_PATH.read_text()
    assert 'if args.route == "assisted"' in source
    assert "two_endpoint._call_optimize(" in source
    assert "single_point.run_single_point(" in source
    assert "geometry_steps_definition" in source


def test_assisted_worker_also_requires_full_optimization_before_single_point() -> None:
    source = BENCHMARK_PATH.read_text()
    assert 'worker.add_argument("--route", choices=("assisted", "pure_pyscf")' in source
    assert "two_endpoint._call_optimize(" in source
    assert "final_parent_state(" in source
    assert '"first_parent_observation"' in source
    assert '"profile": "GAU"' in source


def test_extension_is_not_implemented_as_automatic_batch() -> None:
    source = BENCHMARK_PATH.read_text()
    assert '"candidate_count": 0' in source
    assert '"status": "not_run"' in source
    assert "extension_assisted" not in source
