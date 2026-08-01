from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase9b_aimnet2_parent_handoff.py"
BENCHMARK = ROOT / "scripts" / "phase9b_parent_level_paired_benchmark.py"
CONTRACT = ROOT / "docs" / "PHASE9B_AIMNET2_GAU_LOOSE_V001.yaml"
SCHEMA = ROOT / "docs" / "schemas" / "phase9b_aimnet2_parent_handoff_v1.schema.json"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("phase9b_handoff_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


handoff = _load()
profile = handoff.load_gau_loose_profile(CONTRACT)


def _gradient_for_norm(norm: float) -> list[list[float]]:
    return [[norm, norm, norm], [norm, norm, norm]]


def _classification(*, grms: float, gmax: float | None = None) -> dict[str, object]:
    gradient = _gradient_for_norm(grms)
    if gmax is not None:
        gradient[0][0] = gmax
        remaining_squared = max(0.0, (6.0 * grms * grms - gmax * gmax) / 5.0)
        remaining = math.sqrt(remaining_squared)
        gradient = [[gmax, remaining, remaining], [remaining, remaining, remaining]]
    return cast(
        dict[str, object],
        handoff.classify_first_parent_gradient(
            profile=profile,
            scf_converged=True,
            energy_hartree=-100.0,
            gradient_hartree_bohr=gradient,
            coordinates_finite=True,
            atom_identity_preserved=True,
            charge_multiplicity_preserved=True,
            topology_valid=True,
        ),
    )


def test_gau_loose_yaml_has_five_joint_criteria() -> None:
    payload = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    criteria = payload["aimnet2_surface_convergence"]
    assert criteria["require_all_five"] is True
    assert set(criteria) == {
        "require_all_five",
        "energy_change",
        "gradient_rms",
        "gradient_max",
        "displacement_rms",
        "displacement_max",
    }
    assert profile.gradient_rms_eh_bohr == 1.7e-3
    assert profile.gradient_max_eh_bohr == 2.5e-3
    assert profile.ase_fmax_ev_angstrom == 0.10
    assert profile.maximum_steps == 100


def test_force_unit_conversion_is_physical() -> None:
    # 1 eV/Angstrom = (1/27.211386...) Eh per (1/1.889726...) Bohr.
    assert (
        pytest.approx(
            0.06944615420820195,
            rel=1e-12,
        )
        == handoff.EV_PER_ANGSTROM_TO_HARTREE_PER_BOHR
    )


def test_gau_metrics_use_cartesian_components_but_ase_fmax_uses_atom_norm() -> None:
    result = handoff.aimnet2_gau_loose_metrics(
        profile=profile,
        step_index=1,
        energy_ev=-10.0,
        forces_ev_angstrom=[[0.03, 0.04, 0.0]],
        coordinates_angstrom=[[0.0, 0.0, 0.0]],
        previous_energy_ev=-10.0,
        previous_coordinates_angstrom=[[0.0, 0.0, 0.0]],
    )
    conversion = handoff.EV_PER_ANGSTROM_TO_HARTREE_PER_BOHR
    assert result["force_max_eV_A"] == pytest.approx(0.05)
    assert result["gradient_rms_Eh_Bohr"] == pytest.approx(
        math.sqrt((0.03**2 + 0.04**2) / 3.0) * conversion
    )
    assert result["gradient_max_Eh_Bohr"] == pytest.approx(0.04 * conversion)


def test_first_aimnet2_frame_cannot_claim_full_gau_loose() -> None:
    result = handoff.aimnet2_gau_loose_metrics(
        profile=profile,
        step_index=0,
        energy_ev=-10.0,
        forces_ev_angstrom=[[0.01, 0.0, 0.0]],
        coordinates_angstrom=[[0.0, 0.0, 0.0]],
        previous_energy_ev=None,
        previous_coordinates_angstrom=None,
    )
    assert result["five_criteria_available"] is False
    assert result["aimnet2_gau_loose_converged"] is False
    assert result["energy_change_Eh"] == "unavailable_first_frame"


def test_ase_lbfgs_driver_stops_only_after_all_five_aimnet2_metrics_pass() -> None:
    class Atoms:
        index = 0
        positions = (
            [[0.0, 0.0, 0.0]],
            [[0.020, 0.0, 0.0]],
            [[0.025, 0.0, 0.0]],
        )

        def get_positions(self) -> list[list[float]]:
            return self.positions[self.index]

    atoms = Atoms()

    class Calculator:
        reads = 0

        @staticmethod
        def new_atoms(*, elements: object, coordinates: object) -> Atoms:
            assert elements == ("C",)
            assert coordinates == ((0.0, 0.0, 0.0),)
            return atoms

        def evaluation_counts(self) -> tuple[int, int, int]:
            return self.reads, self.reads, self.reads

    calculator = Calculator()

    class Optimizer:
        nsteps = 0

        def __init__(self, received: Atoms, **kwargs: object) -> None:
            assert received is atoms
            assert kwargs["restart"] is None
            assert kwargs["trajectory"] is None

        def irun(self, *, fmax: float, steps: int) -> Iterator[bool]:
            assert fmax == 0.0
            assert steps == 100
            for index in range(3):
                self.nsteps = index
                atoms.index = index
                yield False

        def get_number_of_steps(self) -> int:
            return self.nsteps

    energies = (-10.0, -10.0001, -10.00011)

    def reader(_atoms: object, _count: int) -> tuple[float, list[list[float]]]:
        calculator.reads += 1
        return energies[atoms.index], [[0.01, 0.0, 0.0]]

    ticks = iter((0.0, 0.1, 0.2, 0.3, 0.4))
    outcome = handoff.optimize_aimnet2_gau_loose(
        calculator=calculator,
        elements=("C",),
        coordinates=((0.0, 0.0, 0.0),),
        profile=profile,
        deadline_monotonic=10.0,
        read_energy_and_forces=reader,
        monotonic=lambda: next(ticks),
        lbfgs_factory=Optimizer,
    )
    assert outcome.converged is True
    assert outcome.steps == 2
    assert len(outcome.trajectory) == 3
    assert outcome.trajectory[0].metrics["aimnet2_gau_loose_converged"] is False
    assert outcome.trajectory[1].metrics["aimnet2_gau_loose_converged"] is False
    assert outcome.trajectory[2].metrics["aimnet2_gau_loose_converged"] is True


def test_parent_first_gradient_is_not_complete_gau_loose() -> None:
    result = _classification(grms=1.0e-3)
    assert result["check"] == "PARENT_GAU_LOOSE_GRADIENT_CHECK"
    assert result["profile"] == "GAU_LOOSE"
    assert result["full_gau_loose_convergence_claimed"] is False
    assert result["first_parent_scf_converged"] is True
    assert result["first_parent_analytic_gradient_available"] is True


def test_both_parent_gradient_components_must_pass() -> None:
    passed = _classification(grms=1.0e-3, gmax=1.2e-3)
    assert passed["classification"] == "HANDOFF_CALIBRATION_PASS"
    assert passed["continue_same_parent_optimization"] is True

    grms_miss = _classification(grms=1.8e-3)
    assert grms_miss["classification"] == "HANDOFF_CALIBRATION_MISS"
    assert grms_miss["continue_same_parent_optimization"] is True

    gmax_miss = _classification(grms=1.6e-3, gmax=2.6e-3)
    assert gmax_miss["classification"] == "HANDOFF_CALIBRATION_MISS"
    assert gmax_miss["continue_same_parent_optimization"] is True


def test_invalid_parent_gradient_is_failed_handoff() -> None:
    result = handoff.classify_first_parent_gradient(
        profile=profile,
        scf_converged=True,
        energy_hartree=-100.0,
        gradient_hartree_bohr=[[math.nan, 0.0, 0.0]],
        coordinates_finite=True,
        atom_identity_preserved=True,
        charge_multiplicity_preserved=True,
        topology_valid=True,
    )
    assert result["classification"] == "FAILED_PARENT_HANDOFF"
    assert "NON_FINITE_PARENT_GRADIENT" in result["failure_types"]
    assert result["continue_same_parent_optimization"] is False


@pytest.mark.parametrize(
    "invalid_field",
    ("scf_converged", "coordinates_finite", "atom_identity_preserved", "topology_valid"),
)
def test_invalid_parent_handoff_conditions_are_not_calibration_misses(
    invalid_field: str,
) -> None:
    values: dict[str, bool] = {
        "scf_converged": True,
        "coordinates_finite": True,
        "atom_identity_preserved": True,
        "charge_multiplicity_preserved": True,
        "topology_valid": True,
    }
    values[invalid_field] = False
    result = handoff.classify_first_parent_gradient(
        profile=profile,
        energy_hartree=-100.0,
        gradient_hartree_bohr=_gradient_for_norm(1.0e-3),
        **values,
    )
    assert result["classification"] == "FAILED_PARENT_HANDOFF"
    assert result["continue_same_parent_optimization"] is False


def test_pass_and_miss_both_continue_to_final_parent_gau() -> None:
    source = BENCHMARK.read_text(encoding="utf-8")
    assert "two_endpoint._call_optimize(" in source
    assert "single_point.run_single_point(" in source
    assert '"profile": "GAU"' in source
    assert 'kwargs["convergence_set"] = "GAU"' in source
    assert "final_parent_state(" in source
    assert (
        handoff.final_parent_state(geometry_converged=True, final_single_point_converged=True)
        == "FINAL_PARENT_GAU_CONVERGED"
    )


def test_exact_byte_handoff_and_single_point_only_false() -> None:
    payload = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert payload["handoff"] == {
        "exact_bytes": True,
        "next_stage": "full_parent_level_pyscf_geometric_optimization",
        "single_point_only": False,
    }
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"]["profile"]["const"] == "GAU_LOOSE"


def test_endpoint_evidence_contains_handoff_and_final_parent_fields() -> None:
    aimnet_source = (ROOT / "scripts" / "phase9b_science_pilot.py").read_text(encoding="utf-8")
    parent_source = BENCHMARK.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")
    for field in (
        "gau_loose_five_metrics",
        "final_xyz",
        "optimization_steps",
        "total_wall_seconds",
    ):
        assert field in aimnet_source
    for field in (
        "first_parent_observation",
        "cumulative_scf_cycles",
        "final_xyz_sha256",
        "FINAL_PARENT_GAU_CONVERGED",
        "parent_gradient_reduction",
    ):
        assert field in parent_source


def test_active_handoff_vocabulary_has_no_deprecated_names() -> None:
    active_paths = (
        CONTRACT,
        SCRIPT,
        BENCHMARK,
        ROOT / "docs" / "PHASE9B_AIMNET2_PRECONDITIONER_CONTRACT_V001.json",
        ROOT
        / ".codex"
        / "skills"
        / "plan-nhc-aimnet2-workflow"
        / "references"
        / "aimnet2-handoff-promotion.md",
        SCHEMA,
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in active_paths)
    deprecated = tuple(
        "".join(chr(value) for value in encoded)
        for encoded in (
            (116, 114, 117, 101, 95, 48, 112, 49, 95, 112, 97, 115, 115),
            (116, 114, 117, 101, 95, 48, 112, 49, 95, 102, 97, 105, 108),
            (112, 117, 114, 101, 95, 86, 65, 83, 80, 95, 99, 111, 110, 116, 105, 110, 117, 101),
            (
                80,
                121,
                115,
                99,
                102,
                95,
                98,
                101,
                108,
                111,
                119,
                95,
                71,
                65,
                85,
                95,
                76,
                79,
                79,
                83,
                69,
            ),
            (
                115,
                105,
                110,
                103,
                108,
                101,
                95,
                112,
                111,
                105,
                110,
                116,
                95,
                97,
                102,
                116,
                101,
                114,
                95,
                112,
                97,
                115,
                115,
            ),
        )
    )
    assert all(name not in source for name in deprecated)
    assert set(handoff.active_vocabulary()) == {
        "HANDOFF_CALIBRATION_PASS",
        "HANDOFF_CALIBRATION_MISS",
        "FAILED_PARENT_HANDOFF",
        "FINAL_PARENT_GAU_CONVERGED",
    }


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        (
            "docs/PHASE9B_SCIENCE_PILOT_V004_RESULT.json",
            "0eb8c016c5eb9836de77d58c209c4fd39bbba1229d24dabfcbbff1cfa61ee1d3",
        ),
        (
            "docs/PHASE9B_SCIENCE_PILOT_V005_RESULT.json",
            "2c79d8eab4a6b74a517ba95af7794290db1427c4a503e0455c939951a8b0fd02",
        ),
        (
            "docs/PHASE9B_SCIENCE_PILOT_V006_RESULT.json",
            "9007276bf090a5c6c39574a6ca93b8af9a46e4335ec25dce9ceb2abfa818432d",
        ),
        (
            "docs/PHASE9B_PARENT_LEVEL_P01_R3_RESULT.json",
            "b0abf53ae44c9195a932e2ff35fe81648e4b4b999795ad05c10748cd6f307077",
        ),
    ],
)
def test_historical_result_bytes_remain_unchanged(relative: str, expected: str) -> None:
    assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
