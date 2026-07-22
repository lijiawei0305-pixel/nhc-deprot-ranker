"""Electronic target formula and protocol identity tests."""

import math

import pytest

from nhc_deprot_ranker.constants import GAS_PROTON_KCAL_MOL, HARTREE_TO_KCAL_MOL
from nhc_deprot_ranker.data.labels import (
    LabelFormulaMismatchError,
    check_stored_label,
    dft_deprot_electronic_kcal,
    electronic_difference_kcal,
    label_protocol_id,
)


def test_hartree_conversion_and_proton_constant() -> None:
    difference = electronic_difference_kcal(-9.5, -10.0)
    assert difference == pytest.approx(0.5 * HARTREE_TO_KCAL_MOL)
    assert dft_deprot_electronic_kcal(-9.5, -10.0) == pytest.approx(
        difference + GAS_PROTON_KCAL_MOL
    )


def test_stored_label_is_revalidated() -> None:
    expected = dft_deprot_electronic_kcal(-9.5, -10.0)
    result = check_stored_label(
        e_neutral_hartree=-9.5,
        e_cation_hartree=-10.0,
        stored_target_kcal=expected + 0.01,
    )
    assert result.passed
    assert result.absolute_error_kcal == pytest.approx(0.01)


def test_formula_conflict_is_hard_reject() -> None:
    expected = dft_deprot_electronic_kcal(-9.5, -10.0)
    with pytest.raises(LabelFormulaMismatchError):
        check_stored_label(
            e_neutral_hartree=-9.5,
            e_cation_hartree=-10.0,
            stored_target_kcal=expected + 0.021,
        )


def test_nonfinite_endpoint_is_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        electronic_difference_kcal(math.nan, -10.0)


def test_protocol_id_is_deterministic_and_protocol_sensitive() -> None:
    left = {"method": "B3LYP", "basis": "def2-SVP", "proton_constant": -6.28}
    reordered = {"proton_constant": -6.28, "basis": "def2-SVP", "method": "B3LYP"}
    changed = {"method": "B3LYP", "basis": "def2-TZVP", "proton_constant": -6.28}
    assert label_protocol_id(left) == label_protocol_id(reordered)
    assert label_protocol_id(left) != label_protocol_id(changed)
