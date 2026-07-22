"""Electronic deprotonation-energy formula and protocol validation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nhc_deprot_ranker.constants import (
    GAS_PROTON_KCAL_MOL,
    HARTREE_TO_KCAL_MOL,
    LABEL_FORMULA_ATOL_KCAL_MOL,
)


class LabelFormulaMismatchError(ValueError):
    """Stored label disagrees with endpoint electronic energies."""


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def electronic_difference_kcal(e_neutral_hartree: float, e_cation_hartree: float) -> float:
    """Return `(E_neutral - E_cation)` in kcal/mol, without the proton term."""

    neutral = _finite(float(e_neutral_hartree), "e_neutral_hartree")
    cation = _finite(float(e_cation_hartree), "e_cation_hartree")
    return (neutral - cation) * HARTREE_TO_KCAL_MOL


def dft_deprot_electronic_kcal(
    e_neutral_hartree: float,
    e_cation_hartree: float,
) -> float:
    """Return the legacy-compatible DFT electronic deprotonation label."""

    return electronic_difference_kcal(e_neutral_hartree, e_cation_hartree) + GAS_PROTON_KCAL_MOL


@dataclass(frozen=True)
class LabelFormulaCheck:
    """Result of comparing a stored target with recomputed endpoint energy."""

    electronic_difference_kcal: float
    expected_target_kcal: float
    stored_target_kcal: float
    absolute_error_kcal: float
    tolerance_kcal: float

    @property
    def passed(self) -> bool:
        """Whether the absolute error is within tolerance."""

        return self.absolute_error_kcal <= self.tolerance_kcal


def check_stored_label(
    *,
    e_neutral_hartree: float,
    e_cation_hartree: float,
    stored_target_kcal: float,
    tolerance_kcal: float = LABEL_FORMULA_ATOL_KCAL_MOL,
) -> LabelFormulaCheck:
    """Recompute a label and raise on disagreement beyond tolerance."""

    if tolerance_kcal < 0 or not math.isfinite(tolerance_kcal):
        raise ValueError("tolerance_kcal must be finite and non-negative")
    stored = _finite(float(stored_target_kcal), "stored_target_kcal")
    difference = electronic_difference_kcal(e_neutral_hartree, e_cation_hartree)
    expected = difference + GAS_PROTON_KCAL_MOL
    result = LabelFormulaCheck(
        electronic_difference_kcal=difference,
        expected_target_kcal=expected,
        stored_target_kcal=stored,
        absolute_error_kcal=abs(expected - stored),
        tolerance_kcal=tolerance_kcal,
    )
    if not result.passed:
        raise LabelFormulaMismatchError(
            "stored label differs from endpoint formula: "
            f"expected={expected:.12g}, stored={stored:.12g}, "
            f"abs_error={result.absolute_error_kcal:.6g}, tolerance={tolerance_kcal:.6g}"
        )
    return result


def label_protocol_id(protocol: Mapping[str, Any]) -> str:
    """Hash a normalized protocol mapping deterministically."""

    encoded = json.dumps(
        dict(protocol),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
