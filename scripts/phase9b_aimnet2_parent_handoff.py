#!/usr/bin/env python3
"""Pure GAU_LOOSE and first-parent-gradient handoff adjudication.

This module performs no chemistry and starts no process.  It turns already
measured AIMNet2 trajectory values and the first successful parent-level
energy/analytic gradient from the continuing geomeTRIC optimization into
structured evidence.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, cast

import yaml

HARTREE_PER_EV: Final = 1.0 / 27.211386245988
BOHR_PER_ANGSTROM: Final = 1.8897261254578281
EV_PER_ANGSTROM_TO_HARTREE_PER_BOHR: Final = HARTREE_PER_EV * BOHR_PER_ANGSTROM

HANDOFF_CALIBRATION_PASS: Final = "HANDOFF_CALIBRATION_PASS"
HANDOFF_CALIBRATION_MISS: Final = "HANDOFF_CALIBRATION_MISS"
FAILED_PARENT_HANDOFF: Final = "FAILED_PARENT_HANDOFF"
FINAL_PARENT_GAU_CONVERGED: Final = "FINAL_PARENT_GAU_CONVERGED"


class HandoffContractError(ValueError):
    """The frozen profile or supplied measurement is malformed."""


class GAULooseTerminal(StrEnum):
    CONVERGED = "converged"
    LIMIT_REACHED = "limit_reached"
    TIMEOUT = "timeout"
    FAILED = "failed"


@dataclass(frozen=True)
class GAULooseProfile:
    energy_change_eh: float
    gradient_rms_eh_bohr: float
    gradient_max_eh_bohr: float
    displacement_rms_angstrom: float
    displacement_max_angstrom: float
    ase_fmax_ev_angstrom: float
    maximum_steps: int


@dataclass(frozen=True)
class GAULooseFrame:
    frame_index: int
    optimizer_step: int
    elapsed_seconds: float
    coordinates: tuple[tuple[float, float, float], ...]
    energy_ev: float
    forces_ev_angstrom: tuple[tuple[float, float, float], ...]
    metrics: dict[str, object]
    is_initial: bool
    is_terminal: bool


@dataclass(frozen=True)
class GAULooseOutcome:
    coordinates: tuple[tuple[float, float, float], ...]
    converged: bool
    steps: int
    energy_evaluations: int
    force_evaluations: int
    calculator_invocations: int
    initial_energy_ev: float
    final_energy_ev: float
    initial_max_force: float
    final_max_force: float
    elapsed_seconds: float
    terminal_state: GAULooseTerminal
    failure_reason: str | None
    trajectory: tuple[GAULooseFrame, ...]


def load_gau_loose_profile(path: Path) -> GAULooseProfile:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("profile") != "GAU_LOOSE":
        raise HandoffContractError("GAU_LOOSE profile identity is invalid")
    convergence = payload.get("aimnet2_surface_convergence")
    ase = payload.get("ase_lbfgs")
    parent = payload.get("parent_first_gradient_check")
    if not isinstance(convergence, dict) or convergence.get("require_all_five") is not True:
        raise HandoffContractError("GAU_LOOSE must require all five convergence criteria")
    if not isinstance(ase, dict) or not isinstance(parent, dict):
        raise HandoffContractError("GAU_LOOSE contract sections are missing")
    expansion = parent.get("internal_fixed_expansion")
    if not isinstance(expansion, dict) or expansion.get("require_both") is not True:
        raise HandoffContractError("parent gradient profile must require GRMS and Gmax")
    profile = GAULooseProfile(
        energy_change_eh=float(convergence["energy_change"]["maximum_absolute_Eh"]),
        gradient_rms_eh_bohr=float(convergence["gradient_rms"]["maximum_Eh_Bohr"]),
        gradient_max_eh_bohr=float(convergence["gradient_max"]["maximum_Eh_Bohr"]),
        displacement_rms_angstrom=float(convergence["displacement_rms"]["maximum_Angstrom"]),
        displacement_max_angstrom=float(convergence["displacement_max"]["maximum_Angstrom"]),
        ase_fmax_ev_angstrom=float(ase["maximum_force_eV_A"]),
        maximum_steps=int(ase["maximum_steps"]),
    )
    if (
        float(expansion.get("gradient_rms_Eh_Bohr", math.nan)) != profile.gradient_rms_eh_bohr
        or float(expansion.get("gradient_max_Eh_Bohr", math.nan)) != profile.gradient_max_eh_bohr
    ):
        raise HandoffContractError("parent gradient profile drifted from GAU_LOOSE")
    if (
        not all(
            math.isfinite(value) and value > 0
            for value in (
                profile.energy_change_eh,
                profile.gradient_rms_eh_bohr,
                profile.gradient_max_eh_bohr,
                profile.displacement_rms_angstrom,
                profile.displacement_max_angstrom,
                profile.ase_fmax_ev_angstrom,
            )
        )
        or profile.maximum_steps <= 0
    ):
        raise HandoffContractError("GAU_LOOSE profile contains invalid limits")
    return profile


def _rows(
    values: Sequence[Sequence[float]], *, label: str
) -> tuple[tuple[float, float, float], ...]:
    rows: list[tuple[float, float, float]] = []
    for value in values:
        if len(value) != 3:
            raise HandoffContractError(f"{label} must have three Cartesian components")
        row = (float(value[0]), float(value[1]), float(value[2]))
        if not all(math.isfinite(component) for component in row):
            raise HandoffContractError(f"{label} contains a non-finite value")
        rows.append(row)
    if not rows:
        raise HandoffContractError(f"{label} is empty")
    return tuple(rows)


def cartesian_rms_and_max(values: Sequence[Sequence[float]], *, label: str) -> tuple[float, float]:
    rows = _rows(values, label=label)
    components = [component for row in rows for component in row]
    return (
        math.sqrt(sum(component * component for component in components) / len(components)),
        max(abs(component) for component in components),
    )


def maximum_vector_norm(values: Sequence[Sequence[float]], *, label: str) -> float:
    rows = _rows(values, label=label)
    return max(math.sqrt(sum(component * component for component in row)) for row in rows)


def aimnet2_gau_loose_metrics(
    *,
    profile: GAULooseProfile,
    step_index: int,
    energy_ev: float,
    forces_ev_angstrom: Sequence[Sequence[float]],
    coordinates_angstrom: Sequence[Sequence[float]],
    previous_energy_ev: float | None,
    previous_coordinates_angstrom: Sequence[Sequence[float]] | None,
) -> dict[str, object]:
    if step_index < 0 or step_index > profile.maximum_steps:
        raise HandoffContractError("accepted step index is outside the frozen budget")
    if not math.isfinite(energy_ev):
        raise HandoffContractError("AIMNet2 energy is non-finite")
    forces = _rows(forces_ev_angstrom, label="AIMNet2 forces")
    force_max_ev_a = maximum_vector_norm(forces, label="AIMNet2 forces")
    coordinates = _rows(coordinates_angstrom, label="AIMNet2 coordinates")
    complete = previous_energy_ev is not None and previous_coordinates_angstrom is not None
    if complete:
        assert previous_energy_ev is not None
        assert previous_coordinates_angstrom is not None
        if not math.isfinite(previous_energy_ev):
            raise HandoffContractError("previous AIMNet2 energy is non-finite")
        previous = _rows(previous_coordinates_angstrom, label="previous AIMNet2 coordinates")
        if len(previous) != len(coordinates):
            raise HandoffContractError("AIMNet2 coordinate row count changed")
        displacement = tuple(
            tuple(current[axis] - old[axis] for axis in range(3))
            for current, old in zip(coordinates, previous, strict=True)
        )
        displacement_rms, displacement_max = cartesian_rms_and_max(
            displacement, label="AIMNet2 displacement"
        )
        energy_change_eh: float | None = abs(energy_ev - previous_energy_ev) * HARTREE_PER_EV
    else:
        displacement_rms = None
        displacement_max = None
        energy_change_eh = None
    gradient_rows = tuple(
        tuple(component * EV_PER_ANGSTROM_TO_HARTREE_PER_BOHR for component in row)
        for row in forces
    )
    gradient_rms, gradient_max = cartesian_rms_and_max(gradient_rows, label="AIMNet2 gradients")
    gates = {
        "energy_change": complete
        and energy_change_eh is not None
        and energy_change_eh <= profile.energy_change_eh,
        "gradient_rms": gradient_rms <= profile.gradient_rms_eh_bohr,
        "gradient_max": gradient_max <= profile.gradient_max_eh_bohr,
        "displacement_rms": complete
        and displacement_rms is not None
        and displacement_rms <= profile.displacement_rms_angstrom,
        "displacement_max": complete
        and displacement_max is not None
        and displacement_max <= profile.displacement_max_angstrom,
        "ase_fmax": force_max_ev_a <= profile.ase_fmax_ev_angstrom,
    }
    return {
        "profile": "GAU_LOOSE",
        "step_index": step_index,
        "energy_eV": energy_ev,
        "energy_change_Eh": (
            energy_change_eh if energy_change_eh is not None else "unavailable_first_frame"
        ),
        "gradient_rms_Eh_Bohr": gradient_rms,
        "gradient_max_Eh_Bohr": gradient_max,
        "displacement_rms_Angstrom": (
            displacement_rms if displacement_rms is not None else "unavailable_first_frame"
        ),
        "displacement_max_Angstrom": (
            displacement_max if displacement_max is not None else "unavailable_first_frame"
        ),
        "force_max_eV_A": force_max_ev_a,
        "five_criteria_available": complete,
        "gates": gates,
        "aimnet2_gau_loose_converged": complete and all(gates.values()),
    }


def optimize_aimnet2_gau_loose(
    *,
    calculator: Any,
    elements: Sequence[str],
    coordinates: Sequence[Sequence[float]],
    profile: GAULooseProfile,
    deadline_monotonic: float,
    read_energy_and_forces: Callable[[Any, int], tuple[float, Sequence[Sequence[float]]]],
    logfile: Any = "-",
    monotonic: Callable[[], float] = time.monotonic,
    lbfgs_factory: Any | None = None,
) -> GAULooseOutcome:
    """Run one ASE LBFGS trajectory until the complete AIMNet2 GAU_LOOSE profile.

    ASE's own force convergence is disabled for the iterator because the active
    profile owns five joint criteria.  The same LBFGS object and Hessian history
    continue until all criteria pass or the frozen limit is reached.
    """

    if len(elements) == 0 or len(elements) != len(coordinates):
        raise HandoffContractError("AIMNet2 optimizer input identity is invalid")
    started = monotonic()
    if started >= deadline_monotonic:
        raise HandoffContractError("AIMNet2 GAU_LOOSE deadline expired before start")
    if lbfgs_factory is None:
        from ase.optimize import LBFGS

        lbfgs_factory = LBFGS
    atoms = calculator.new_atoms(elements=elements, coordinates=coordinates)
    optimizer = lbfgs_factory(atoms, restart=None, trajectory=None, logfile=logfile)
    frames: list[GAULooseFrame] = []
    terminal = GAULooseTerminal.LIMIT_REACHED
    failure: str | None = "the optimizer reached the frozen GAU_LOOSE step limit"
    try:
        for _ase_force_converged in optimizer.irun(fmax=0.0, steps=profile.maximum_steps):
            now = monotonic()
            if now >= deadline_monotonic:
                terminal = GAULooseTerminal.TIMEOUT
                failure = "the AIMNet2 GAU_LOOSE deadline expired"
                break
            step_index = int(optimizer.get_number_of_steps())
            if step_index > profile.maximum_steps:
                break
            energy_ev, raw_forces = read_energy_and_forces(atoms, len(elements))
            forces = _rows(raw_forces, label="AIMNet2 forces")
            current_coordinates = _rows(atoms.get_positions(), label="AIMNet2 coordinates")
            previous = frames[-1] if frames else None
            metrics = aimnet2_gau_loose_metrics(
                profile=profile,
                step_index=step_index,
                energy_ev=float(energy_ev),
                forces_ev_angstrom=forces,
                coordinates_angstrom=current_coordinates,
                previous_energy_ev=previous.energy_ev if previous is not None else None,
                previous_coordinates_angstrom=(
                    previous.coordinates if previous is not None else None
                ),
            )
            frames.append(
                GAULooseFrame(
                    frame_index=len(frames),
                    optimizer_step=step_index,
                    elapsed_seconds=now - started,
                    coordinates=current_coordinates,
                    energy_ev=float(energy_ev),
                    forces_ev_angstrom=forces,
                    metrics=metrics,
                    is_initial=not frames,
                    is_terminal=False,
                )
            )
            if metrics["aimnet2_gau_loose_converged"] is True:
                terminal = GAULooseTerminal.CONVERGED
                failure = None
                break
    except Exception as exc:
        terminal = GAULooseTerminal.FAILED
        failure = f"{type(exc).__name__}: {exc}"
    if not frames:
        raise HandoffContractError("AIMNet2 GAU_LOOSE optimizer recorded no frame")
    frames[-1] = replace(frames[-1], is_terminal=True)
    final = frames[-1]
    initial = frames[0]
    energy_reads, force_reads, calculator_invocations = calculator.evaluation_counts()
    return GAULooseOutcome(
        coordinates=final.coordinates,
        converged=terminal is GAULooseTerminal.CONVERGED,
        steps=int(optimizer.get_number_of_steps()),
        energy_evaluations=int(energy_reads),
        force_evaluations=int(force_reads),
        calculator_invocations=int(calculator_invocations),
        initial_energy_ev=initial.energy_ev,
        final_energy_ev=final.energy_ev,
        initial_max_force=float(cast(float, initial.metrics["force_max_eV_A"])),
        final_max_force=float(cast(float, final.metrics["force_max_eV_A"])),
        elapsed_seconds=monotonic() - started,
        terminal_state=terminal,
        failure_reason=failure,
        trajectory=tuple(frames),
    )


def classify_first_parent_gradient(
    *,
    profile: GAULooseProfile,
    scf_converged: bool,
    energy_hartree: float | None,
    gradient_hartree_bohr: Sequence[Sequence[float]] | None,
    coordinates_finite: bool,
    atom_identity_preserved: bool,
    charge_multiplicity_preserved: bool,
    topology_valid: bool,
    failure_detail: str | None = None,
) -> dict[str, object]:
    failures: list[str] = []
    if not scf_converged:
        failures.append("SCF_NOT_CONVERGED")
    if energy_hartree is None or not math.isfinite(energy_hartree):
        failures.append("NON_FINITE_PARENT_ENERGY")
    if gradient_hartree_bohr is None:
        failures.append("ANALYTIC_GRADIENT_UNAVAILABLE")
    if not coordinates_finite:
        failures.append("NON_FINITE_PARENT_COORDINATES")
    if not atom_identity_preserved:
        failures.append("ATOM_IDENTITY_CHANGED")
    if not charge_multiplicity_preserved:
        failures.append("CHARGE_MULTIPLICITY_MISMATCH")
    if not topology_valid:
        failures.append("TOPOLOGY_INVALID")
    gradient_rms: float | None = None
    gradient_max: float | None = None
    if gradient_hartree_bohr is not None:
        try:
            gradient_rms, gradient_max = cartesian_rms_and_max(
                gradient_hartree_bohr, label="parent analytic gradient"
            )
        except HandoffContractError:
            failures.append("NON_FINITE_PARENT_GRADIENT")
    if failures:
        return {
            "check": "PARENT_GAU_LOOSE_GRADIENT_CHECK",
            "profile": "GAU_LOOSE",
            "classification": FAILED_PARENT_HANDOFF,
            "failure_types": failures,
            "failure_detail": failure_detail,
            "first_parent_scf_converged": scf_converged,
            "first_parent_analytic_gradient_available": gradient_hartree_bohr is not None,
            "first_parent_energy_Eh": energy_hartree,
            "first_parent_gradient_rms_Eh_Bohr": gradient_rms,
            "first_parent_gradient_max_Eh_Bohr": gradient_max,
            "full_gau_loose_convergence_claimed": False,
            "continue_same_parent_optimization": False,
        }
    assert gradient_rms is not None and gradient_max is not None
    classification = (
        HANDOFF_CALIBRATION_PASS
        if gradient_rms <= profile.gradient_rms_eh_bohr
        and gradient_max <= profile.gradient_max_eh_bohr
        else HANDOFF_CALIBRATION_MISS
    )
    return {
        "check": "PARENT_GAU_LOOSE_GRADIENT_CHECK",
        "profile": "GAU_LOOSE",
        "classification": classification,
        "failure_types": [],
        "failure_detail": None,
        "first_parent_scf_converged": True,
        "first_parent_analytic_gradient_available": True,
        "first_parent_energy_Eh": energy_hartree,
        "first_parent_gradient_rms_Eh_Bohr": gradient_rms,
        "first_parent_gradient_max_Eh_Bohr": gradient_max,
        "full_gau_loose_convergence_claimed": False,
        "continue_same_parent_optimization": True,
    }


def gradient_reduction(initial: float, handoff: float) -> dict[str, float]:
    if not all(math.isfinite(value) and value >= 0 for value in (initial, handoff)):
        raise HandoffContractError("gradient reduction inputs are invalid")
    if initial == 0:
        raise HandoffContractError("zero initial gradient has no reduction ratio")
    return {
        "initial": initial,
        "handoff": handoff,
        "signed_reduction": initial - handoff,
        "reduction_fraction": (initial - handoff) / initial,
    }


def final_parent_state(*, geometry_converged: bool, final_single_point_converged: bool) -> str:
    if not geometry_converged or not final_single_point_converged:
        raise HandoffContractError("final parent GAU route is incomplete")
    return FINAL_PARENT_GAU_CONVERGED


def active_vocabulary() -> tuple[str, ...]:
    return (
        HANDOFF_CALIBRATION_PASS,
        HANDOFF_CALIBRATION_MISS,
        FAILED_PARENT_HANDOFF,
        FINAL_PARENT_GAU_CONVERGED,
    )
