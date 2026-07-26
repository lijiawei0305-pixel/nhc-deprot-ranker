"""Phase 9A-I minimal AIMNet2 inference characterization.

This module has no chemistry, torch, or aimnet import at any level.  The
calculator is injected through a Protocol so every test runs with a mock and
never loads a model or touches a GPU.

It deliberately lives outside the two-endpoint runner source closure.  Adding it
to that closure would change ``runner_source_sha256`` and invalidate the permit
chain on every edit, and would make a machine-learning stack part of the guarded
quantum worker's identity.

Scope is six single-point energy-and-force evaluations on one frozen candidate:
three repeats of the cation and three of the neutral.  There is no optimizer, no
PySCF, and no deprotonation label.  No AIMNet2 energy may reach a label.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

# Real inference is a separate authorization.  This is a source-level gate, not
# a caller-provided option.
EXECUTION_AUTHORIZED: Final[bool] = False

WEIGHT_FILENAME: Final = "aimnet2_wb97m_d3_0.pt"
WEIGHT_BYTES: Final = 8836941
WEIGHT_SHA256: Final = "f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28"

CANDIDATE_INCHIKEY: Final = "LBNPGYISTSLAHY-UHFFFAOYSA-N"
CATION_XYZ_SHA256: Final = "543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286"
NEUTRAL_XYZ_SHA256: Final = "af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8"

ATOM_MAP: Final[dict[str, int]] = {"C2_carbene": 14, "N1": 8, "N3": 15}
REQUIRED_ELEMENTS: Final = frozenset({"C", "F", "H", "N"})

ENDPOINT_CHARGE: Final[dict[str, int]] = {"cation": 1, "neutral": 0}
MULTIPLICITY: Final = 1
REPEATS: Final = 3

ENERGY_UNIT: Final = "eV"
FORCES_UNIT: Final = "eV/A"

# Preregistered in docs/PHASE9A_I_DETERMINISM_CONTRACT.md before any measurement.
ENERGY_SPREAD_TOLERANCE_EV: Final = 1e-4
FORCE_SPREAD_TOLERANCE_EV_PER_A: Final = 1e-4

_ELECTRONS: Final[dict[str, int]] = {"H": 1, "C": 6, "N": 7, "F": 9}


class Phase9AIError(RuntimeError):
    """The minimal inference characterization could not prove its closed scope."""


class Phase9AINotAuthorizedError(Phase9AIError):
    """Real inference was attempted while the source gate is closed."""


@dataclass(frozen=True, slots=True)
class EndpointInput:
    """One frozen endpoint.  Coordinates are Angstrom and are never modified."""

    endpoint: str
    elements: tuple[str, ...]
    coordinates: tuple[tuple[float, float, float], ...]
    charge: int
    multiplicity: int
    xyz_sha256: str


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One evaluation.  Carries its own full identity; nothing is inferred later."""

    endpoint: str
    repeat_index: int
    xyz_sha256: str
    atom_order_sha256: str
    atom_count: int
    charge: int
    multiplicity: int
    model_weight_sha256: str
    energy_value: float
    energy_unit: str
    forces_shape: tuple[int, int]
    forces_unit: str
    max_abs_force_component: float
    max_atomic_force_norm: float
    coordinates_unchanged: bool


class InferenceCalculator(Protocol):
    """Injectable seam.  Production supplies AIMNet2; tests supply a mock."""

    def compute(
        self,
        *,
        elements: Sequence[str],
        coordinates: Sequence[Sequence[float]],
        charge: int,
        multiplicity: int,
    ) -> tuple[float, Sequence[Sequence[float]]]:
        """Return one energy in eV and forces in eV/A shaped (N, 3)."""


def atom_order_sha256(elements: Sequence[str]) -> str:
    """Hash the element sequence so any reordering is detectable."""

    digest = hashlib.sha256()
    for element in elements:
        digest.update(element.encode("ascii"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _require_sha256(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise Phase9AIError(f"{label} must be a lowercase 64-character SHA256")
    return value


def verify_weight_identity(path: Path) -> dict[str, object]:
    """Prove the weight before it is opened.  A mismatch never triggers a search."""

    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise Phase9AIError("AIMNet2 weight is unavailable") from exc
    if not file_stat.st_mode & 0o100000 or path.is_symlink():
        raise Phase9AIError("AIMNet2 weight must be a regular non-symlink file")
    if file_stat.st_size != WEIGHT_BYTES:
        raise Phase9AIError("AIMNet2 weight byte size drifted")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != WEIGHT_SHA256:
        raise Phase9AIError("AIMNet2 weight SHA256 drifted")
    return {"filename": path.name, "bytes": file_stat.st_size, "sha256": actual}


def electron_count(elements: Sequence[str], *, charge: int) -> int:
    """Chemistry-free electron count from an internal table."""

    total = 0
    for element in elements:
        if element not in _ELECTRONS:
            raise Phase9AIError(f"element outside the frozen candidate set: {element}")
        total += _ELECTRONS[element]
    return total - charge


def validate_endpoint(endpoint_input: EndpointInput, *, expected_xyz_sha256: str) -> None:
    """Every check that must pass before a calculator is called."""

    if endpoint_input.endpoint not in ENDPOINT_CHARGE:
        raise Phase9AIError(f"unknown endpoint: {endpoint_input.endpoint}")
    expected_charge = ENDPOINT_CHARGE[endpoint_input.endpoint]
    if type(endpoint_input.charge) is not int or endpoint_input.charge != expected_charge:
        raise Phase9AIError(f"{endpoint_input.endpoint} charge must be {expected_charge}")
    if type(endpoint_input.multiplicity) is not int or endpoint_input.multiplicity != MULTIPLICITY:
        raise Phase9AIError("multiplicity must be 1")
    _require_sha256(endpoint_input.xyz_sha256, label="endpoint xyz_sha256")
    if endpoint_input.xyz_sha256 != expected_xyz_sha256:
        raise Phase9AIError(f"{endpoint_input.endpoint} XYZ SHA256 drifted")
    if not endpoint_input.elements:
        raise Phase9AIError("endpoint has no atoms")
    if len(endpoint_input.elements) != len(endpoint_input.coordinates):
        raise Phase9AIError("element and coordinate counts disagree")
    unsupported = sorted(set(endpoint_input.elements) - REQUIRED_ELEMENTS)
    if unsupported:
        raise Phase9AIError(f"unsupported element for this candidate: {unsupported[0]}")
    for row in endpoint_input.coordinates:
        if len(row) != 3 or any(not math.isfinite(value) for value in row):
            raise Phase9AIError("endpoint coordinates must be three finite values")
    electrons = electron_count(endpoint_input.elements, charge=endpoint_input.charge)
    if electrons % 2 != 0:
        raise Phase9AIError("endpoint is not a closed-shell singlet electron count")


def validate_endpoint_pair(cation: EndpointInput, neutral: EndpointInput) -> None:
    """The two endpoints must differ by exactly one protium and nothing else."""

    if len(cation.elements) != len(neutral.elements) + 1:
        raise Phase9AIError("cation must have exactly one more atom than neutral")
    cation_heavy = tuple(e for e in cation.elements if e != "H")
    neutral_heavy = tuple(e for e in neutral.elements if e != "H")
    if cation_heavy != neutral_heavy:
        raise Phase9AIError("endpoint ordered heavy-element sequences differ")
    cation_h = sum(1 for e in cation.elements if e == "H")
    neutral_h = sum(1 for e in neutral.elements if e == "H")
    if cation_h != neutral_h + 1:
        raise Phase9AIError("endpoints do not differ by exactly one proton")
    if electron_count(cation.elements, charge=cation.charge) != electron_count(
        neutral.elements, charge=neutral.charge
    ):
        raise Phase9AIError("endpoint electron counts differ")


def validate_atom_map(elements: Sequence[str]) -> None:
    """The mapped indices must exist and carry the right elements for THIS candidate."""

    expected = {"C2_carbene": "C", "N1": "N", "N3": "N"}
    for name, index in ATOM_MAP.items():
        if not 0 <= index < len(elements):
            raise Phase9AIError(f"atom map index out of range: {name}")
        if elements[index] != expected[name]:
            raise Phase9AIError(f"atom map element mismatch at {name}")
    if len(set(ATOM_MAP.values())) != len(ATOM_MAP):
        raise Phase9AIError("atom map indices must be distinct")


def evaluate_once(
    calculator: InferenceCalculator,
    endpoint_input: EndpointInput,
    *,
    repeat_index: int,
    model_weight_sha256: str,
) -> CallRecord:
    """One single-point call, fully validated.  No optimization ever occurs."""

    _require_sha256(model_weight_sha256, label="model_weight_sha256")
    before = tuple(tuple(row) for row in endpoint_input.coordinates)
    energy, forces = calculator.compute(
        elements=endpoint_input.elements,
        coordinates=endpoint_input.coordinates,
        charge=endpoint_input.charge,
        multiplicity=endpoint_input.multiplicity,
    )
    if not isinstance(energy, float) or not math.isfinite(energy):
        raise Phase9AIError("energy must be a finite scalar")
    rows = [tuple(row) for row in forces]
    if len(rows) != len(endpoint_input.elements):
        raise Phase9AIError("forces row count does not match atom count")
    for row in rows:
        if len(row) != 3:
            raise Phase9AIError("forces must be shaped (N, 3)")
        if any(not math.isfinite(value) for value in row):
            raise Phase9AIError("forces contain a non-finite value")
    after = tuple(tuple(row) for row in endpoint_input.coordinates)
    if before != after:
        raise Phase9AIError("calculator mutated the input coordinates")
    max_component = max(abs(value) for row in rows for value in row)
    max_norm = max(math.sqrt(sum(value * value for value in row)) for row in rows)
    return CallRecord(
        endpoint=endpoint_input.endpoint,
        repeat_index=repeat_index,
        xyz_sha256=endpoint_input.xyz_sha256,
        atom_order_sha256=atom_order_sha256(endpoint_input.elements),
        atom_count=len(endpoint_input.elements),
        charge=endpoint_input.charge,
        multiplicity=endpoint_input.multiplicity,
        model_weight_sha256=model_weight_sha256,
        energy_value=energy,
        energy_unit=ENERGY_UNIT,
        forces_shape=(len(rows), 3),
        forces_unit=FORCES_UNIT,
        max_abs_force_component=max_component,
        max_atomic_force_norm=max_norm,
        coordinates_unchanged=True,
    )


def spread(values: Sequence[float]) -> float:
    """Max minus min.  Outliers are never discarded before this is computed."""

    if not values:
        raise Phase9AIError("spread requires at least one value")
    return max(values) - min(values)


def assess_determinism(records: Sequence[CallRecord]) -> dict[str, object]:
    """Report cation and neutral spreads separately; never pool them."""

    if len(records) != 2 * REPEATS:
        raise Phase9AIError(f"determinism assessment requires exactly {2 * REPEATS} records")
    report: dict[str, object] = {}
    passed = True
    for endpoint in ("cation", "neutral"):
        subset = [record for record in records if record.endpoint == endpoint]
        if len(subset) != REPEATS:
            raise Phase9AIError(f"{endpoint} must have exactly {REPEATS} repeats")
        identities = {
            (r.xyz_sha256, r.atom_order_sha256, r.charge, r.multiplicity, r.atom_count)
            for r in subset
        }
        if len(identities) != 1:
            raise Phase9AIError(f"{endpoint} repeats do not share one input identity")
        energy_spread = spread([r.energy_value for r in subset])
        force_spread = spread([r.max_abs_force_component for r in subset])
        report[f"{endpoint}_energy_spread"] = energy_spread
        report[f"{endpoint}_max_force_component_spread"] = force_spread
        if energy_spread > ENERGY_SPREAD_TOLERANCE_EV:
            passed = False
        if force_spread > FORCE_SPREAD_TOLERANCE_EV_PER_A:
            passed = False
    report["tolerances_preregistered"] = True
    report["energy_spread_tolerance_ev"] = ENERGY_SPREAD_TOLERANCE_EV
    report["force_spread_tolerance_ev_per_a"] = FORCE_SPREAD_TOLERANCE_EV_PER_A
    report["bitwise_identity_required"] = False
    report["determinism_pass"] = passed
    return report


def build_production_calculator(*_args: object, **_kwargs: object) -> InferenceCalculator:
    """Production construction is a separate authorization and stays closed."""

    if EXECUTION_AUTHORIZED is not True:
        raise Phase9AINotAuthorizedError(
            "Phase 9A-I real inference is not authorized; the six-call run needs "
            "explicit user authorization"
        )
    raise Phase9AINotAuthorizedError("no production calculator construction path exists yet")


__all__ = [
    "ATOM_MAP",
    "CANDIDATE_INCHIKEY",
    "CATION_XYZ_SHA256",
    "ENDPOINT_CHARGE",
    "EXECUTION_AUTHORIZED",
    "NEUTRAL_XYZ_SHA256",
    "REPEATS",
    "WEIGHT_SHA256",
    "CallRecord",
    "EndpointInput",
    "InferenceCalculator",
    "Phase9AIError",
    "Phase9AINotAuthorizedError",
    "assess_determinism",
    "atom_order_sha256",
    "build_production_calculator",
    "electron_count",
    "evaluate_once",
    "spread",
    "validate_atom_map",
    "validate_endpoint",
    "validate_endpoint_pair",
    "verify_weight_identity",
]
