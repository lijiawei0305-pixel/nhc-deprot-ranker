"""Phase 9B AIMNet2 geometry preoptimization runner.

Deliberately outside the runner source closure.  The guarded quantum worker must
never take the machine-learning stack as a dependency, so this module lives under
``preparation/`` and hands geometry across a hash-closed file boundary.

It imports no chemistry, torch, ASE, or aimnet package at any level.  The
optimizer arrives through a Protocol so every test runs against a mock and never
loads a model or touches a GPU.

Scope is one endpoint per call: relax a frozen Phase 7 force-field geometry on the
AIMNet2 surface, prove the molecule is still the same molecule, and stop.  It
produces no energy that may enter a label, and no label field exists here.

Because only one ensemble member exists, per-atom disagreement is unavailable.
The deterministic structural checks below replace that lost signal and are
stricter than an ensemble run would have needed.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

# Real preoptimization is a separate authorization.  Source-level gate.
EXECUTION_AUTHORIZED: Final[bool] = False

OPTIMIZER: Final = "LBFGS"
ENERGY_UNIT: Final = "eV"
FORCES_UNIT: Final = "eV/A"

# --- Preregistered stopping and displacement bounds -------------------------
#
# fmax is a moderate preoptimization criterion, not extreme convergence on the
# AIMNet2 surface.  The geomeTRIC threshold is roughly 0.015-0.023 eV/A and the
# legacy fine-tuned model's near-minimum force error was about 0.088 eV/A, so
# tightening below the model's own error would refine toward a minimum of the
# wrong surface.  0.05 sits under that error while staying above the DFT
# threshold, which is where the remaining force stops being force-field artifact
# and starts being theory-level difference.
FMAX_EV_PER_A: Final = 0.05

# Phase 9A-I measured starting max force of 2.23 eV/A (cation) and 5.73 eV/A
# (neutral) on the MMFF geometry.  200 steps is ample for a 26-atom molecule to
# cross that gap while staying bounded.
MAX_STEPS: Final = 200

# Mirrors the frozen AIMNET2_STAGE_BUDGET ceiling.
MAX_WALLTIME_SECONDS: Final = 900

# A force-field to quantum relaxation of this size typically moves 0.1-0.5 A RMSD.
# Beyond 1.0 A the optimizer is more likely finding a different conformer than
# fixing the starting one, and with no ensemble signal we cannot tell which, so we
# refuse to travel that far instead of guessing.
MAX_TOTAL_RMSD_ANGSTROM: Final = 1.0

# A single atom may legitimately move further than the whole-structure RMSD, for
# example a rotating CF3 fluorine.
MAX_SINGLE_ATOM_DISPLACEMENT_ANGSTROM: Final = 2.5

# C2-N ring bonds sit near 1.33-1.37 A; a change beyond this is distortion of the
# bond that defines the reaction, not relaxation.
MAX_C2_N_BOND_CHANGE_ANGSTROM: Final = 0.15

# The N1-C2-N3 angle sits near 101-104 degrees.
MAX_RING_ANGLE_CHANGE_DEGREES: Final = 10.0

# Covalent radii in Angstrom for the candidate's element set, with the usual
# tolerance factor for inferring a bond from a distance.
_COVALENT_RADII: Final[Mapping[str, float]] = {
    "H": 0.31,
    "C": 0.76,
    "N": 0.71,
    "F": 0.57,
}
_BOND_TOLERANCE: Final = 1.30

_Coordinates = tuple[tuple[float, float, float], ...]


class Phase9BPreoptError(RuntimeError):
    """The preoptimization could not prove it preserved the molecule."""


class Phase9BPreoptNotAuthorizedError(Phase9BPreoptError):
    """Real preoptimization was attempted while the source gate is closed."""


@dataclass(frozen=True, slots=True)
class PreoptStep:
    """One optimizer step: coordinates in Angstrom, energy eV, max force eV/A."""

    coordinates: _Coordinates
    energy_ev: float
    max_force_ev_per_a: float


@dataclass(frozen=True, slots=True)
class PreoptResult:
    """Everything the output contract requires, and no label field."""

    endpoint: str
    charge: int
    multiplicity: int
    converged: bool
    steps: int
    initial_coordinates: _Coordinates
    final_coordinates: _Coordinates
    initial_max_force_ev_per_a: float
    final_max_force_ev_per_a: float
    initial_energy_ev: float
    final_energy_ev: float
    energy_unit: str
    forces_unit: str
    total_rmsd_angstrom: float
    max_single_atom_displacement_angstrom: float
    c2_n1_bond_before: float
    c2_n1_bond_after: float
    c2_n3_bond_before: float
    c2_n3_bond_after: float
    ring_angle_before_degrees: float
    ring_angle_after_degrees: float
    atom_order_sha256: str
    final_xyz_sha256: str
    ensemble_members: int
    ensemble_uncertainty_available: bool


class PreoptOptimizer(Protocol):
    """Injectable seam.  Production supplies AIMNet2 + ASE; tests supply a mock."""

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
        """Return the trajectory, first entry the input, last the final state."""


def _require_coordinates(rows: Sequence[Sequence[float]], *, label: str) -> _Coordinates:
    out: list[tuple[float, float, float]] = []
    for row in rows:
        if len(row) != 3:
            raise Phase9BPreoptError(f"{label} must be three coordinates per atom")
        if any(not math.isfinite(value) for value in row):
            raise Phase9BPreoptError(f"{label} contains a non-finite coordinate")
        out.append((float(row[0]), float(row[1]), float(row[2])))
    return tuple(out)


def atom_order_sha256(elements: Sequence[str]) -> str:
    """Hash the element sequence so any reordering is detectable."""

    digest = hashlib.sha256()
    for element in elements:
        digest.update(element.encode("ascii"))
        digest.update(b"\x00")
    return digest.hexdigest()


def render_xyz(elements: Sequence[str], coordinates: _Coordinates, *, comment: str) -> bytes:
    """Serialize deterministically in Angstrom without changing atom order."""

    if len(elements) != len(coordinates):
        raise Phase9BPreoptError("element and coordinate counts disagree")
    if "\n" in comment:
        raise Phase9BPreoptError("xyz comment must be one line")
    lines = [str(len(elements)), comment]
    lines.extend(
        f"{element:<2} {x: .12f} {y: .12f} {z: .12f}"
        for element, (x, y, z) in zip(elements, coordinates, strict=True)
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def distance(coordinates: _Coordinates, i: int, j: int) -> float:
    ax, ay, az = coordinates[i]
    bx, by, bz = coordinates[j]
    return math.dist((ax, ay, az), (bx, by, bz))


def angle_degrees(coordinates: _Coordinates, i: int, j: int, k: int) -> float:
    """Angle i-j-k in degrees, with j the vertex."""

    jx, jy, jz = coordinates[j]
    a = tuple(coordinates[i][axis] - (jx, jy, jz)[axis] for axis in range(3))
    b = tuple(coordinates[k][axis] - (jx, jy, jz)[axis] for axis in range(3))
    na = math.sqrt(sum(value * value for value in a))
    nb = math.sqrt(sum(value * value for value in b))
    if na == 0.0 or nb == 0.0:
        raise Phase9BPreoptError("cannot measure an angle through a coincident atom")
    cosine = sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def rmsd(before: _Coordinates, after: _Coordinates) -> float:
    """Positional RMSD without superposition: atom order is fixed, so alignment
    would hide exactly the drift we want to bound."""

    if len(before) != len(after):
        raise Phase9BPreoptError("cannot compare geometries of different atom counts")
    total = sum(math.dist(a, b) ** 2 for a, b in zip(before, after, strict=True))
    return math.sqrt(total / len(before))


def max_atom_displacement(before: _Coordinates, after: _Coordinates) -> float:
    if len(before) != len(after):
        raise Phase9BPreoptError("cannot compare geometries of different atom counts")
    return max(math.dist(a, b) for a, b in zip(before, after, strict=True))


def infer_connectivity(
    elements: Sequence[str], coordinates: _Coordinates
) -> frozenset[tuple[int, int]]:
    """Covalent-radius connectivity as an index-keyed edge set."""

    edges: set[tuple[int, int]] = set()
    for i, element_i in enumerate(elements):
        radius_i = _COVALENT_RADII.get(element_i)
        if radius_i is None:
            raise Phase9BPreoptError(f"no covalent radius for element: {element_i}")
        for j in range(i + 1, len(elements)):
            radius_j = _COVALENT_RADII.get(elements[j])
            if radius_j is None:
                raise Phase9BPreoptError(f"no covalent radius for element: {elements[j]}")
            if distance(coordinates, i, j) <= (radius_i + radius_j) * _BOND_TOLERANCE:
                edges.add((i, j))
    return frozenset(edges)


def validate_connectivity_preserved(
    elements: Sequence[str], before: _Coordinates, after: _Coordinates
) -> None:
    """Compare under the identity permutation, not up to isomorphism.

    An isomorphic-but-relabelled structure would silently break the atom map, the
    handoff hash closure, and the endpoint ordering invariant while passing any
    check that only asks whether it is still the same molecule.
    """

    initial = infer_connectivity(elements, before)
    final = infer_connectivity(elements, after)
    formed = sorted(final - initial)
    broken = sorted(initial - final)
    if formed:
        raise Phase9BPreoptError(f"bond formed during preoptimization: {formed[0]}")
    if broken:
        raise Phase9BPreoptError(f"bond broken during preoptimization: {broken[0]}")


def validate_proton_identity(
    elements: Sequence[str],
    before: _Coordinates,
    after: _Coordinates,
    *,
    proton_index: int,
) -> None:
    """The acidic proton must stay bonded to the same heavy atom, by index.

    Counting hydrogens is insufficient: a migration preserves the count and
    yields a tautomer that looks clean and converged, which PySCF would then
    optimize honestly into a well-formed energy for a different reaction.
    """

    if not 0 <= proton_index < len(elements):
        raise Phase9BPreoptError("proton index out of range")
    if elements[proton_index] != "H":
        raise Phase9BPreoptError("the declared proton index is not a hydrogen")

    def host(coordinates: _Coordinates) -> int:
        best: int | None = None
        best_distance = math.inf
        for index, element in enumerate(elements):
            if index == proton_index or element == "H":
                continue
            separation = distance(coordinates, proton_index, index)
            if separation < best_distance:
                best, best_distance = index, separation
        if best is None:
            raise Phase9BPreoptError("no heavy atom available to host the proton")
        return best

    if host(before) != host(after):
        raise Phase9BPreoptError("the acidic proton migrated to a different heavy atom")


def validate_carbene_centre(
    elements: Sequence[str],
    coordinates: _Coordinates,
    *,
    atom_map: Mapping[str, int],
    expected_c2_hydrogens: int,
) -> None:
    """C2 must keep its element, and its hydrogen count must match the endpoint.

    The neutral endpoint's C2 is a divalent singlet carbene, the least certain
    region of the AIMNet2 surface for this chemistry and the atom the reaction is
    defined on, so it is measured directly rather than inferred from a global
    metric that a local distortion could hide.
    """

    c2 = atom_map["C2_carbene"]
    if elements[c2] != "C":
        raise Phase9BPreoptError("the mapped C2 index is not a carbon")
    attached = 0
    radius_c = _COVALENT_RADII["C"]
    for index, element in enumerate(elements):
        if index == c2 or element != "H":
            continue
        limit = (radius_c + _COVALENT_RADII["H"]) * _BOND_TOLERANCE
        if distance(coordinates, c2, index) <= limit:
            attached += 1
    if attached != expected_c2_hydrogens:
        raise Phase9BPreoptError(
            f"C2 carries {attached} hydrogens, expected {expected_c2_hydrogens}"
        )


def build_production_optimizer(*_args: object, **_kwargs: object) -> PreoptOptimizer:
    """Production construction is a separate authorization and stays closed."""

    if EXECUTION_AUTHORIZED is not True:
        raise Phase9BPreoptNotAuthorizedError(
            "Phase 9B preoptimization is not authorized; the run needs explicit user authorization"
        )
    raise Phase9BPreoptNotAuthorizedError("no production optimizer construction path exists yet")


def run_preoptimization(
    optimizer: PreoptOptimizer,
    *,
    endpoint: str,
    elements: Sequence[str],
    coordinates: Sequence[Sequence[float]],
    charge: int,
    multiplicity: int,
    atom_map: Mapping[str, int],
    proton_index: int | None,
) -> PreoptResult:
    """Relax one endpoint and prove the molecule survived, or fail closed."""

    if endpoint not in {"cation", "neutral"}:
        raise Phase9BPreoptError(f"unknown endpoint: {endpoint}")
    expected_charge = 1 if endpoint == "cation" else 0
    if type(charge) is not int or charge != expected_charge:
        raise Phase9BPreoptError(f"{endpoint} charge must be {expected_charge}")
    if type(multiplicity) is not int or multiplicity != 1:
        raise Phase9BPreoptError("multiplicity must be 1")
    if endpoint == "cation" and proton_index is None:
        raise Phase9BPreoptError("the cation endpoint requires an acidic proton index")
    if endpoint == "neutral" and proton_index is not None:
        raise Phase9BPreoptError("the neutral endpoint has no acidic proton to track")

    before = _require_coordinates(coordinates, label="input coordinates")
    if len(before) != len(elements):
        raise Phase9BPreoptError("element and coordinate counts disagree")
    order_hash = atom_order_sha256(elements)

    trajectory = optimizer.relax(
        elements=elements,
        coordinates=before,
        charge=charge,
        multiplicity=multiplicity,
        fmax=FMAX_EV_PER_A,
        max_steps=MAX_STEPS,
    )
    if not trajectory:
        raise Phase9BPreoptError("optimizer returned an empty trajectory")
    if len(trajectory) - 1 > MAX_STEPS:
        raise Phase9BPreoptError("optimizer exceeded the frozen step limit")

    first, last = trajectory[0], trajectory[-1]
    for step in trajectory:
        if not math.isfinite(step.energy_ev) or not math.isfinite(step.max_force_ev_per_a):
            raise Phase9BPreoptError("trajectory contains a non-finite energy or force")
        if len(step.coordinates) != len(before):
            raise Phase9BPreoptError("trajectory changed the atom count")
    after = _require_coordinates(last.coordinates, label="final coordinates")

    if atom_order_sha256(elements) != order_hash:
        raise Phase9BPreoptError("atom order changed during preoptimization")
    converged = last.max_force_ev_per_a <= FMAX_EV_PER_A
    if not converged:
        raise Phase9BPreoptError(
            "preoptimization did not reach the frozen fmax; an unconverged "
            "structure is never handed to PySCF"
        )

    total_rmsd = rmsd(before, after)
    if total_rmsd > MAX_TOTAL_RMSD_ANGSTROM:
        raise Phase9BPreoptError("preoptimization exceeded the frozen total RMSD bound")
    worst = max_atom_displacement(before, after)
    if worst > MAX_SINGLE_ATOM_DISPLACEMENT_ANGSTROM:
        raise Phase9BPreoptError("preoptimization exceeded the frozen single-atom bound")

    validate_connectivity_preserved(elements, before, after)
    expected_c2_hydrogens = 1 if endpoint == "cation" else 0
    for coords in (before, after):
        validate_carbene_centre(
            elements,
            coords,
            atom_map=atom_map,
            expected_c2_hydrogens=expected_c2_hydrogens,
        )
    if proton_index is not None:
        validate_proton_identity(elements, before, after, proton_index=proton_index)

    c2, n1, n3 = atom_map["C2_carbene"], atom_map["N1"], atom_map["N3"]
    bonds = {
        "c2_n1_before": distance(before, c2, n1),
        "c2_n1_after": distance(after, c2, n1),
        "c2_n3_before": distance(before, c2, n3),
        "c2_n3_after": distance(after, c2, n3),
    }
    if abs(bonds["c2_n1_after"] - bonds["c2_n1_before"]) > MAX_C2_N_BOND_CHANGE_ANGSTROM:
        raise Phase9BPreoptError("C2-N1 bond length change exceeded the frozen bound")
    if abs(bonds["c2_n3_after"] - bonds["c2_n3_before"]) > MAX_C2_N_BOND_CHANGE_ANGSTROM:
        raise Phase9BPreoptError("C2-N3 bond length change exceeded the frozen bound")
    angle_before = angle_degrees(before, n1, c2, n3)
    angle_after = angle_degrees(after, n1, c2, n3)
    if abs(angle_after - angle_before) > MAX_RING_ANGLE_CHANGE_DEGREES:
        raise Phase9BPreoptError("N1-C2-N3 angle change exceeded the frozen bound")

    final_xyz = render_xyz(
        elements,
        after,
        comment=f"phase9b aimnet2 preoptimized {endpoint}; not a validated minimum",
    )
    return PreoptResult(
        endpoint=endpoint,
        charge=charge,
        multiplicity=multiplicity,
        converged=True,
        steps=len(trajectory) - 1,
        initial_coordinates=before,
        final_coordinates=after,
        initial_max_force_ev_per_a=first.max_force_ev_per_a,
        final_max_force_ev_per_a=last.max_force_ev_per_a,
        initial_energy_ev=first.energy_ev,
        final_energy_ev=last.energy_ev,
        energy_unit=ENERGY_UNIT,
        forces_unit=FORCES_UNIT,
        total_rmsd_angstrom=total_rmsd,
        max_single_atom_displacement_angstrom=worst,
        c2_n1_bond_before=bonds["c2_n1_before"],
        c2_n1_bond_after=bonds["c2_n1_after"],
        c2_n3_bond_before=bonds["c2_n3_before"],
        c2_n3_bond_after=bonds["c2_n3_after"],
        ring_angle_before_degrees=angle_before,
        ring_angle_after_degrees=angle_after,
        atom_order_sha256=order_hash,
        final_xyz_sha256=hashlib.sha256(final_xyz).hexdigest(),
        ensemble_members=1,
        ensemble_uncertainty_available=False,
    )


__all__ = [
    "EXECUTION_AUTHORIZED",
    "FMAX_EV_PER_A",
    "MAX_C2_N_BOND_CHANGE_ANGSTROM",
    "MAX_RING_ANGLE_CHANGE_DEGREES",
    "MAX_SINGLE_ATOM_DISPLACEMENT_ANGSTROM",
    "MAX_STEPS",
    "MAX_TOTAL_RMSD_ANGSTROM",
    "MAX_WALLTIME_SECONDS",
    "OPTIMIZER",
    "Phase9BPreoptError",
    "Phase9BPreoptNotAuthorizedError",
    "PreoptOptimizer",
    "PreoptResult",
    "PreoptStep",
    "angle_degrees",
    "atom_order_sha256",
    "build_production_optimizer",
    "distance",
    "infer_connectivity",
    "max_atom_displacement",
    "render_xyz",
    "rmsd",
    "run_preoptimization",
    "validate_carbene_centre",
    "validate_connectivity_preserved",
    "validate_proton_identity",
]
