"""Phase 9A-I no-model regressions.

Every test uses a mock calculator and fixture geometry.  Nothing here imports
torch, aimnet, ASE, RDKit, or PySCF, loads a weight, touches a GPU, or reaches
the network.  The tests assert fail-closed behaviour rather than happy paths.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
from collections.abc import Sequence
from pathlib import Path

import pytest

from nhc_deprot_ranker.preparation import phase9a_i_inference as inference
from nhc_deprot_ranker.preparation.phase9a_i_inference import (
    CATION_XYZ_SHA256,
    NEUTRAL_XYZ_SHA256,
    EndpointInput,
    Phase9AIError,
    Phase9AINotAuthorizedError,
    assess_determinism,
    evaluate_once,
    validate_atom_map,
    validate_endpoint,
    validate_endpoint_pair,
    verify_weight_identity,
)

_WEIGHT_SHA = inference.WEIGHT_SHA256


class _MockCalculator:
    """Deterministic stand-in.  Records what it was asked, computes nothing real."""

    def __init__(self, *, energy: float = -1.5, jitter: float = 0.0) -> None:
        self.energy = energy
        self.jitter = jitter
        self.calls: list[tuple[int, int]] = []
        self._n = 0

    def compute(
        self,
        *,
        elements: Sequence[str],
        coordinates: Sequence[Sequence[float]],
        charge: int,
        multiplicity: int,
    ) -> tuple[float, Sequence[Sequence[float]]]:
        self.calls.append((charge, multiplicity))
        self._n += 1
        offset = self.jitter * self._n
        forces = [[0.01 + offset, -0.02, 0.03] for _ in elements]
        return self.energy + offset, forces


def _elements(hydrogens: int) -> tuple[str, ...]:
    # Heavy sequence is fixed; only the trailing protium count varies, and the
    # atom map indices 8 / 14 / 15 must land on N / C / N.
    heavy = ["C"] * 8 + ["N"] + ["C"] * 5 + ["C", "N"] + ["N"] + ["F"] * 9
    return tuple(heavy + ["H"] * hydrogens)


def _endpoint(name: str, *, hydrogens: int, charge: int, sha: str) -> EndpointInput:
    elements = _elements(hydrogens)
    return EndpointInput(
        endpoint=name,
        elements=elements,
        coordinates=tuple((float(i), 0.0, 0.0) for i in range(len(elements))),
        charge=charge,
        multiplicity=1,
        xyz_sha256=sha,
    )


def _cation() -> EndpointInput:
    return _endpoint("cation", hydrogens=5, charge=1, sha=CATION_XYZ_SHA256)


def _neutral() -> EndpointInput:
    return _endpoint("neutral", hydrogens=4, charge=0, sha=NEUTRAL_XYZ_SHA256)


def test_source_gate_is_closed_and_production_construction_refuses() -> None:
    assert inference.EXECUTION_AUTHORIZED is False
    source = Path(inference.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source
    with pytest.raises(Phase9AINotAuthorizedError, match="not authorized"):
        inference.build_production_calculator()


def test_cation_and_neutral_charges_are_passed_explicitly() -> None:
    calculator = _MockCalculator()
    evaluate_once(calculator, _cation(), repeat_index=1, model_weight_sha256=_WEIGHT_SHA)
    evaluate_once(calculator, _neutral(), repeat_index=1, model_weight_sha256=_WEIGHT_SHA)
    assert calculator.calls == [(1, 1), (0, 1)]


def test_endpoint_charge_mismatch_fails_closed() -> None:
    wrong = _endpoint("cation", hydrogens=5, charge=0, sha=CATION_XYZ_SHA256)
    with pytest.raises(Phase9AIError, match="charge must be 1"):
        validate_endpoint(wrong, expected_xyz_sha256=CATION_XYZ_SHA256)


def test_nonsinglet_multiplicity_fails_closed() -> None:
    bad = EndpointInput(
        endpoint="neutral",
        elements=_elements(4),
        coordinates=tuple((0.0, 0.0, 0.0) for _ in _elements(4)),
        charge=0,
        multiplicity=3,
        xyz_sha256=NEUTRAL_XYZ_SHA256,
    )
    with pytest.raises(Phase9AIError, match="multiplicity must be 1"):
        validate_endpoint(bad, expected_xyz_sha256=NEUTRAL_XYZ_SHA256)


def test_xyz_hash_drift_fails_closed() -> None:
    drifted = _endpoint("cation", hydrogens=5, charge=1, sha="a" * 64)
    with pytest.raises(Phase9AIError, match="SHA256 drifted"):
        validate_endpoint(drifted, expected_xyz_sha256=CATION_XYZ_SHA256)


def test_unsupported_element_fails_closed() -> None:
    elements = (*_elements(5)[:-1], "S")
    bad = EndpointInput(
        endpoint="cation",
        elements=elements,
        coordinates=tuple((0.0, 0.0, 0.0) for _ in elements),
        charge=1,
        multiplicity=1,
        xyz_sha256=CATION_XYZ_SHA256,
    )
    with pytest.raises(Phase9AIError, match="unsupported element"):
        validate_endpoint(bad, expected_xyz_sha256=CATION_XYZ_SHA256)


def test_valid_endpoints_and_pair_pass() -> None:
    cation, neutral = _cation(), _neutral()
    validate_endpoint(cation, expected_xyz_sha256=CATION_XYZ_SHA256)
    validate_endpoint(neutral, expected_xyz_sha256=NEUTRAL_XYZ_SHA256)
    validate_endpoint_pair(cation, neutral)
    validate_atom_map(cation.elements)


def test_pair_without_one_proton_difference_fails_closed() -> None:
    with pytest.raises(Phase9AIError, match="exactly one more atom"):
        validate_endpoint_pair(
            _cation(), _endpoint("neutral", hydrogens=2, charge=0, sha=NEUTRAL_XYZ_SHA256)
        )


def test_atom_map_indices_must_carry_the_right_elements() -> None:
    swapped = list(_elements(5))
    swapped[14] = "N"
    with pytest.raises(Phase9AIError, match="atom map element mismatch"):
        validate_atom_map(tuple(swapped))


def test_atom_order_change_changes_the_order_hash() -> None:
    original = _elements(5)
    # Swap two atoms of DIFFERENT elements; swapping identical ones is a no-op
    # and would make this assertion vacuous.
    first_c = original.index("C")
    first_f = original.index("F")
    assert original[first_c] != original[first_f]
    swapped = list(original)
    swapped[first_c], swapped[first_f] = swapped[first_f], swapped[first_c]
    assert inference.atom_order_sha256(original) != inference.atom_order_sha256(tuple(swapped))


def test_nonfinite_energy_fails_closed() -> None:
    class NanEnergy(_MockCalculator):
        def compute(self, **kwargs: object) -> tuple[float, Sequence[Sequence[float]]]:
            del kwargs
            return float("nan"), [[0.0, 0.0, 0.0]] * len(_elements(5))

    with pytest.raises(Phase9AIError, match="finite scalar"):
        evaluate_once(NanEnergy(), _cation(), repeat_index=1, model_weight_sha256=_WEIGHT_SHA)


def test_nonfinite_force_fails_closed() -> None:
    class NanForce(_MockCalculator):
        def compute(self, **kwargs: object) -> tuple[float, Sequence[Sequence[float]]]:
            del kwargs
            rows = [[0.0, 0.0, 0.0] for _ in _elements(5)]
            rows[3][1] = float("inf")
            return -1.0, rows

    with pytest.raises(Phase9AIError, match="non-finite"):
        evaluate_once(NanForce(), _cation(), repeat_index=1, model_weight_sha256=_WEIGHT_SHA)


def test_wrong_forces_shape_fails_closed() -> None:
    class BadShape(_MockCalculator):
        def compute(self, **kwargs: object) -> tuple[float, Sequence[Sequence[float]]]:
            del kwargs
            return -1.0, [[0.0, 0.0] for _ in _elements(5)]

    with pytest.raises(Phase9AIError, match=r"\(N, 3\)"):
        evaluate_once(BadShape(), _cation(), repeat_index=1, model_weight_sha256=_WEIGHT_SHA)


def test_forces_row_count_mismatch_fails_closed() -> None:
    class ShortRows(_MockCalculator):
        def compute(self, **kwargs: object) -> tuple[float, Sequence[Sequence[float]]]:
            del kwargs
            return -1.0, [[0.0, 0.0, 0.0]]

    with pytest.raises(Phase9AIError, match="row count"):
        evaluate_once(ShortRows(), _cation(), repeat_index=1, model_weight_sha256=_WEIGHT_SHA)


def test_units_are_recorded_as_ev_and_ev_per_angstrom() -> None:
    record = evaluate_once(
        _MockCalculator(), _cation(), repeat_index=1, model_weight_sha256=_WEIGHT_SHA
    )
    assert record.energy_unit == "eV"
    assert record.forces_unit == "eV/A"
    assert record.forces_shape == (len(_elements(5)), 3)
    assert record.coordinates_unchanged is True


def _six_records(jitter: float) -> list[inference.CallRecord]:
    calculator = _MockCalculator(jitter=jitter)
    records = []
    for index in (1, 2, 3):
        records.append(
            evaluate_once(
                calculator, _cation(), repeat_index=index, model_weight_sha256=_WEIGHT_SHA
            )
        )
    calculator2 = _MockCalculator(jitter=jitter)
    for index in (1, 2, 3):
        records.append(
            evaluate_once(
                calculator2, _neutral(), repeat_index=index, model_weight_sha256=_WEIGHT_SHA
            )
        )
    return records


def test_determinism_passes_within_preregistered_tolerance() -> None:
    report = assess_determinism(_six_records(jitter=0.0))
    assert report["determinism_pass"] is True
    assert report["bitwise_identity_required"] is False
    assert report["cation_energy_spread"] == 0.0
    assert report["neutral_energy_spread"] == 0.0


def test_determinism_fails_when_spread_exceeds_tolerance() -> None:
    report = assess_determinism(_six_records(jitter=1.0))
    assert report["determinism_pass"] is False
    cation_spread = report["cation_energy_spread"]
    assert isinstance(cation_spread, float)
    assert cation_spread > inference.ENERGY_SPREAD_TOLERANCE_EV


def test_determinism_requires_exactly_six_records() -> None:
    with pytest.raises(Phase9AIError, match="exactly 6 records"):
        assess_determinism(_six_records(jitter=0.0)[:5])


def test_determinism_rejects_mixed_input_identity() -> None:
    records = _six_records(jitter=0.0)
    tampered = [*records[:5], dataclasses.replace(records[5], atom_count=99)]
    with pytest.raises(Phase9AIError, match="one input identity"):
        assess_determinism(tampered)


def test_weight_identity_verification_fails_closed(tmp_path: Path) -> None:
    absent = tmp_path / "missing.pt"
    with pytest.raises(Phase9AIError, match="unavailable"):
        verify_weight_identity(absent)

    wrong_size = tmp_path / "wrong.pt"
    wrong_size.write_bytes(b"not the real weight")
    with pytest.raises(Phase9AIError, match="byte size drifted"):
        verify_weight_identity(wrong_size)


def test_weight_identity_rejects_correct_size_but_wrong_hash(tmp_path: Path) -> None:
    impostor = tmp_path / "impostor.pt"
    impostor.write_bytes(b"\x00" * inference.WEIGHT_BYTES)
    assert hashlib.sha256(impostor.read_bytes()).hexdigest() != _WEIGHT_SHA
    with pytest.raises(Phase9AIError, match="SHA256 drifted"):
        verify_weight_identity(impostor)


def test_no_label_field_exists_anywhere_in_the_module() -> None:
    """An AIMNet2 energy must have no route into a deprotonation label."""

    source = Path(inference.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("627.509474", "6.28", "deprot_electronic", "dft_deprot", "kcal"):
        assert forbidden not in source, forbidden
    assert not any(field.endswith("kcal") for field in inference.CallRecord.__dataclass_fields__)


def test_module_imports_no_chemistry_or_ml_stack() -> None:
    source = Path(inference.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "import torch",
        "import aimnet",
        "import ase",
        "import pyscf",
        "import rdkit",
    ):
        assert forbidden not in source, forbidden


def test_no_optimizer_or_download_path_exists() -> None:
    """Scan executable code, not prose.

    The module docstring legitimately says "no optimizer", so a raw substring
    scan matches the very sentence promising the absence. Parse instead and
    inspect identifiers and string literals in actual code.
    """

    tree = ast.parse(Path(inference.__file__).read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)

    identifiers: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.append(node.id.lower())
        elif isinstance(node, ast.Attribute):
            identifiers.append(node.attr.lower())
        elif isinstance(node, ast.keyword) and node.arg:
            identifiers.append(node.arg.lower())
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value not in docstrings
        ):
            identifiers.append(node.value.lower())

    blob = " ".join(identifiers)
    for forbidden in ("optimize", "lbfgs", "geometric", "hf_hub", "huggingface", "download"):
        assert forbidden not in blob, forbidden
