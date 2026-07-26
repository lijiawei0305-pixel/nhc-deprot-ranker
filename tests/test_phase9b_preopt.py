"""Phase 9B preoptimization runner regressions.

No chemistry, no server, no compute, no model. A mock optimizer stands in for
AIMNet2, so nothing here loads a weight or touches a GPU. Every test asserts
fail-closed behaviour or a preregistered bound.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

from nhc_deprot_ranker.preparation import phase9b_preopt as preopt
from nhc_deprot_ranker.preparation.phase9b_preopt import (
    FMAX_EV_PER_A,
    MAX_SINGLE_ATOM_DISPLACEMENT_ANGSTROM,
    MAX_TOTAL_RMSD_ANGSTROM,
    Phase9BPreoptError,
    Phase9BPreoptNotAuthorizedError,
    PreoptStep,
    run_preoptimization,
)

# A small planar-ish NHC-like fixture: a five-membered ring N1-C2-N3-C4-C5 with
# one H on C2 (cation) plus two spectator F atoms.
_ATOM_MAP = {"N1": 0, "C2_carbene": 1, "N3": 2}

_Coords = tuple[tuple[float, float, float], ...]


def _as_coords(rows: Sequence[Sequence[float]]) -> _Coords:
    """Restore the fixed 3-tuple shape a generic comprehension erases."""

    return tuple((float(r[0]), float(r[1]), float(r[2])) for r in rows)


def _ring(hydrogen_on_c2: bool) -> tuple[list[str], list[tuple[float, float, float]]]:
    elements = ["N", "C", "N", "C", "C", "F", "F"]
    coords: list[tuple[float, float, float]] = [
        (0.000, 1.100, 0.0),  # 0 N1
        (0.000, 0.000, 0.0),  # 1 C2
        (1.100, -0.300, 0.0),  # 2 N3
        (0.900, -1.600, 0.0),  # 3 C4
        (-0.500, -1.800, 0.0),  # 4 C5
        (1.900, -2.400, 0.0),  # 5 F on C4
        (-1.200, -2.900, 0.0),  # 6 F on C5
    ]
    if hydrogen_on_c2:
        elements.append("H")
        coords.append((0.000, -1.080, 0.0))  # 7 H bonded to C2
    return elements, coords


def _cation() -> tuple[list[str], list[tuple[float, float, float]]]:
    return _ring(hydrogen_on_c2=True)


def _neutral() -> tuple[list[str], list[tuple[float, float, float]]]:
    return _ring(hydrogen_on_c2=False)


class _MockOptimizer:
    """Returns a trajectory that converges by construction."""

    def __init__(
        self,
        *,
        shift: tuple[float, float, float] = (0.0, 0.0, 0.0),
        atom: int | None = None,
        final_force: float = 0.01,
        steps: int = 3,
    ) -> None:
        self.shift = shift
        self.atom = atom
        self.final_force = final_force
        self.steps = steps
        self.calls: list[tuple[int, int]] = []

    def relax(
        self,
        *,
        elements: Sequence[str],
        coordinates: Sequence[Sequence[float]],
        charge: int,
        multiplicity: int,
        fmax: float,
        max_steps: int,
    ) -> Sequence[PreoptStep]:
        del elements, fmax, max_steps
        self.calls.append((charge, multiplicity))
        start = _as_coords(coordinates)
        moved: list[tuple[float, float, float]] = list(start)
        if self.atom is not None:
            x, y, z = moved[self.atom]
            moved[self.atom] = (x + self.shift[0], y + self.shift[1], z + self.shift[2])
        trajectory = [PreoptStep(coordinates=start, energy_ev=-100.0, max_force_ev_per_a=3.5)]
        for index in range(1, self.steps):
            last = index == self.steps - 1
            trajectory.append(
                PreoptStep(
                    coordinates=tuple(moved) if last else start,
                    energy_ev=-100.0 - index,
                    max_force_ev_per_a=self.final_force if last else 1.0,
                )
            )
        return trajectory


def _run(
    endpoint: str = "cation",
    optimizer: _MockOptimizer | None = None,
    **kw: object,
) -> preopt.PreoptResult:
    elements, coords = _cation() if endpoint == "cation" else _neutral()
    params: dict[str, object] = {
        "endpoint": endpoint,
        "elements": elements,
        "coordinates": coords,
        "charge": 1 if endpoint == "cation" else 0,
        "multiplicity": 1,
        "atom_map": _ATOM_MAP,
        "proton_index": 7 if endpoint == "cation" else None,
    }
    params.update(kw)
    return run_preoptimization(optimizer or _MockOptimizer(), **params)  # type: ignore[arg-type]


def test_source_gate_is_closed_and_production_optimizer_refuses() -> None:
    assert preopt.EXECUTION_AUTHORIZED is False
    source = Path(preopt.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source
    with pytest.raises(Phase9BPreoptNotAuthorizedError, match="not authorized"):
        preopt.build_production_optimizer()


def test_module_imports_no_model_stack_and_declares_no_label() -> None:
    source = Path(preopt.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("import torch", "import aimnet", "from ase", "import pyscf", "import rdkit"):
        assert forbidden not in source, forbidden
    for forbidden in ("627.509474", "6.28", "dft_deprot", "kcal", "hartree"):
        assert forbidden not in source, forbidden
    assert not any(f.endswith("kcal") for f in preopt.PreoptResult.__dataclass_fields__)


def test_module_lives_outside_the_runner_source_closure() -> None:
    """The guarded worker must never depend on the machine-learning stack."""

    from nhc_deprot_ranker.quantum import two_endpoint

    closure = two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    assert not any("phase9b_preopt" in member for member in closure)


def test_both_endpoints_relax_and_report_the_contract_fields() -> None:
    for endpoint in ("cation", "neutral"):
        result = _run(endpoint)
        assert result.endpoint == endpoint
        assert result.converged is True
        assert result.energy_unit == "eV"
        assert result.forces_unit == "eV/A"
        assert result.ensemble_members == 1
        assert result.ensemble_uncertainty_available is False
        assert len(result.final_xyz_sha256) == 64


def test_charge_is_passed_explicitly_per_endpoint() -> None:
    cation_opt, neutral_opt = _MockOptimizer(), _MockOptimizer()
    _run("cation", cation_opt)
    _run("neutral", neutral_opt)
    assert cation_opt.calls == [(1, 1)]
    assert neutral_opt.calls == [(0, 1)]


def test_wrong_charge_for_the_endpoint_fails_closed() -> None:
    with pytest.raises(Phase9BPreoptError, match="charge must be 1"):
        _run("cation", charge=0)
    with pytest.raises(Phase9BPreoptError, match="charge must be 0"):
        _run("neutral", charge=1)


def test_nonsinglet_multiplicity_fails_closed() -> None:
    with pytest.raises(Phase9BPreoptError, match="multiplicity must be 1"):
        _run("cation", multiplicity=3)


def test_unknown_endpoint_fails_closed() -> None:
    with pytest.raises(Phase9BPreoptError, match="unknown endpoint"):
        _run("sideways")


def test_cation_requires_a_proton_index_and_neutral_forbids_one() -> None:
    with pytest.raises(Phase9BPreoptError, match="requires an acidic proton index"):
        _run("cation", proton_index=None)
    with pytest.raises(Phase9BPreoptError, match="no acidic proton to track"):
        _run("neutral", proton_index=7)


def test_unconverged_structure_is_never_handed_onward() -> None:
    loose = _MockOptimizer(final_force=FMAX_EV_PER_A * 10)
    with pytest.raises(Phase9BPreoptError, match="did not reach the frozen fmax"):
        _run("cation", loose)


def test_nonfinite_energy_in_the_trajectory_fails_closed() -> None:
    class NanEnergy(_MockOptimizer):
        def relax(self, **kwargs: object) -> Sequence[PreoptStep]:
            start = _as_coords(cast(Sequence[Sequence[float]], kwargs["coordinates"]))
            return [PreoptStep(coordinates=start, energy_ev=float("nan"), max_force_ev_per_a=0.01)]

    with pytest.raises(Phase9BPreoptError, match="non-finite energy or force"):
        _run("cation", NanEnergy())


def test_empty_trajectory_fails_closed() -> None:
    class Empty(_MockOptimizer):
        def relax(self, **kwargs: object) -> Sequence[PreoptStep]:
            del kwargs
            return []

    with pytest.raises(Phase9BPreoptError, match="empty trajectory"):
        _run("cation", Empty())


def test_atom_count_change_fails_closed() -> None:
    class Grows(_MockOptimizer):
        def relax(self, **kwargs: object) -> Sequence[PreoptStep]:
            start = _as_coords(cast(Sequence[Sequence[float]], kwargs["coordinates"]))
            return [
                PreoptStep(coordinates=start, energy_ev=-1.0, max_force_ev_per_a=3.0),
                PreoptStep(
                    coordinates=(*start, (9.0, 9.0, 9.0)),
                    energy_ev=-2.0,
                    max_force_ev_per_a=0.01,
                ),
            ]

    with pytest.raises(Phase9BPreoptError, match="changed the atom count"):
        _run("cation", Grows())


def test_total_rmsd_bound_is_enforced() -> None:
    """A whole-structure move that large is more likely a different conformer."""

    far = _MockOptimizer(atom=6, shift=(0.0, 0.0, MAX_TOTAL_RMSD_ANGSTROM * 8))
    with pytest.raises(Phase9BPreoptError, match="total RMSD bound"):
        _run("cation", far)


def test_single_atom_displacement_bound_is_enforced() -> None:
    nudge = MAX_SINGLE_ATOM_DISPLACEMENT_ANGSTROM + 0.2
    mover = _MockOptimizer(atom=6, shift=(0.0, 0.0, nudge))
    with pytest.raises(Phase9BPreoptError, match="single-atom bound"):
        _run("cation", mover)


def test_bond_breaking_fails_closed() -> None:
    """Pull a fluorine off its carbon, inside the displacement bound."""

    breaker = _MockOptimizer(atom=5, shift=(1.6, 0.0, 0.0))
    with pytest.raises(Phase9BPreoptError, match="bond broken"):
        _run("cation", breaker)


def test_proton_migration_fails_closed() -> None:
    """Move the acidic proton from C2 onto N3, preserving the hydrogen count."""

    _, coords = _cation()
    n3 = coords[_ATOM_MAP["N3"]]
    target = (n3[0] + 0.3, n3[1] - 0.9, n3[2])
    dx = tuple(target[axis] - coords[7][axis] for axis in range(3))
    migrator = _MockOptimizer(atom=7, shift=(dx[0], dx[1], dx[2]))
    # Connectivity fires first, which is correct: a proton acquiring a new host
    # necessarily forms a bond. Either refusal blocks the handoff.
    with pytest.raises(Phase9BPreoptError, match=r"bond formed|migrated to a different"):
        _run("cation", migrator)


def test_proton_identity_check_catches_migration_on_its_own() -> None:
    """Direct unit test: hydrogen count is preserved, so counting cannot catch it."""

    elements, before = _cation()
    frozen_before = _as_coords(before)
    n3 = frozen_before[_ATOM_MAP["N3"]]
    after = list(frozen_before)
    after[7] = (n3[0] + 0.3, n3[1] - 0.9, n3[2])
    assert sum(1 for e in elements if e == "H") == 1
    with pytest.raises(Phase9BPreoptError, match="migrated to a different heavy atom"):
        preopt.validate_proton_identity(elements, frozen_before, tuple(after), proton_index=7)


def test_carbene_hydrogen_count_is_endpoint_specific() -> None:
    """The neutral C2 must be hydrogen-free; the cation C2 must carry exactly one."""

    neutral_elements, neutral_coords = _neutral()
    preopt.validate_carbene_centre(
        neutral_elements, tuple(neutral_coords), atom_map=_ATOM_MAP, expected_c2_hydrogens=0
    )
    with pytest.raises(Phase9BPreoptError, match="C2 carries 0 hydrogens"):
        preopt.validate_carbene_centre(
            neutral_elements, tuple(neutral_coords), atom_map=_ATOM_MAP, expected_c2_hydrogens=1
        )

    cation_elements, cation_coords = _cation()
    preopt.validate_carbene_centre(
        cation_elements, tuple(cation_coords), atom_map=_ATOM_MAP, expected_c2_hydrogens=1
    )
    with pytest.raises(Phase9BPreoptError, match="C2 carries 1 hydrogens"):
        preopt.validate_carbene_centre(
            cation_elements, tuple(cation_coords), atom_map=_ATOM_MAP, expected_c2_hydrogens=0
        )


def test_atom_map_pointing_at_a_non_carbon_fails_closed() -> None:
    with pytest.raises(Phase9BPreoptError, match="mapped C2 index is not a carbon"):
        _run("cation", atom_map={"C2_carbene": 0, "N1": 1, "N3": 2})


def test_unknown_element_has_no_covalent_radius() -> None:
    elements, coords = _cation()
    elements[6] = "Xx"
    with pytest.raises(Phase9BPreoptError, match="no covalent radius"):
        run_preoptimization(
            _MockOptimizer(),
            endpoint="cation",
            elements=elements,
            coordinates=coords,
            charge=1,
            multiplicity=1,
            atom_map=_ATOM_MAP,
            proton_index=7,
        )


def test_declared_proton_index_must_be_a_hydrogen() -> None:
    with pytest.raises(Phase9BPreoptError, match="not a hydrogen"):
        _run("cation", proton_index=0)


def test_frozen_bounds_have_the_preregistered_values() -> None:
    """These are fixed before any measurement and must not drift silently."""

    assert preopt.OPTIMIZER == "LBFGS"
    assert preopt.FMAX_EV_PER_A == 0.05
    assert preopt.MAX_STEPS == 200
    assert preopt.MAX_TOTAL_RMSD_ANGSTROM == 1.0
    assert preopt.MAX_SINGLE_ATOM_DISPLACEMENT_ANGSTROM == 2.5
    assert preopt.MAX_C2_N_BOND_CHANGE_ANGSTROM == 0.15
    assert preopt.MAX_RING_ANGLE_CHANGE_DEGREES == 10.0


def test_fmax_sits_between_the_dft_threshold_and_the_model_error() -> None:
    """Tighter than the model's own error would refine toward the wrong surface."""

    geometric_threshold_upper = 0.023
    legacy_model_force_mae = 0.088
    assert geometric_threshold_upper < preopt.FMAX_EV_PER_A < legacy_model_force_mae


def test_walltime_bound_matches_the_frozen_stage_budget() -> None:
    from nhc_deprot_ranker.quantum.phase9b_resources import AIMNET2_STAGE_BUDGET

    assert AIMNET2_STAGE_BUDGET["max_preopt_walltime_seconds"] == preopt.MAX_WALLTIME_SECONDS


def test_rendered_xyz_is_angstrom_and_claims_no_minimum() -> None:
    result = _run("neutral")
    elements, _ = _neutral()
    raw = preopt.render_xyz(
        elements,
        result.final_coordinates,
        comment="phase9b aimnet2 preoptimized neutral; not a validated minimum",
    )
    text = raw.decode()
    assert text.splitlines()[0] == str(len(elements))
    assert "not a validated minimum" in text.splitlines()[1]
    assert len(text.splitlines()) == len(elements) + 2


def test_rmsd_is_unaligned_by_design() -> None:
    """Superposition would hide exactly the drift the bound exists to catch."""

    a = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    translated = ((5.0, 0.0, 0.0), (6.0, 0.0, 0.0))
    assert math.isclose(preopt.rmsd(a, translated), 5.0)


def test_connectivity_comparison_is_index_preserving() -> None:
    """A relabelling that keeps the molecule must still be rejected."""

    elements = ["C", "C", "H", "H"]
    before = ((0.0, 0.0, 0.0), (1.5, 0.0, 0.0), (-1.0, 0.0, 0.0), (2.5, 0.0, 0.0))
    swapped = ((0.0, 0.0, 0.0), (1.5, 0.0, 0.0), (2.5, 0.0, 0.0), (-1.0, 0.0, 0.0))
    with pytest.raises(Phase9BPreoptError, match=r"bond formed|bond broken"):
        preopt.validate_connectivity_preserved(elements, before, swapped)
