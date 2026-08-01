#!/usr/bin/env python3
"""Read-only method audit for the Phase 9B parent-level P01 pilot.

This module is intentionally outside the production runner.  It performs one
fixed-geometry PySCF implementation/grid audit and one independent AIMNet2 D3
evaluation.  It never performs geometry optimization or writes production
labels.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import math
import os
import platform
import resource
import stat
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final, cast

PARENT_XC: Final = "wb97m-d3bj"
PARENT_D3_METHOD: Final = "wb97m"
PARENT_BASIS: Final = "def2-tzvpp"
PARENT_DISPERSION: Final = "d3bj"
PARENT_D3_PARAMETERS: Final = {"s6": 1.0, "s8": 0.3908, "a1": 0.566, "a2": 3.128}
GRID_LEVELS: Final = (3, 4)
SCF_TOLERANCE: Final = 1.0e-9
SCF_MAX_CYCLES: Final = 100
THREADS: Final = 4
MEMORY_MB: Final = 12000
FINITE_DIFFERENCE_STEP_ANGSTROM: Final = 0.001
SCHEMA: Final = "nhc-phase9b-parent-level-protocol-audit-p01-v1"


class AuditError(RuntimeError):
    """The parent-level method identity or implementation did not close."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()


def read_regular(path: Path, *, maximum: int = 64 << 20) -> bytes:
    if path.is_symlink():
        raise AuditError(f"symlink is forbidden: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise AuditError(f"unsafe file identity: {path.name}")
        if before.st_size < 0 or before.st_size > maximum:
            raise AuditError(f"file size outside audit bound: {path.name}")
        raw = b""
        while len(raw) < before.st_size:
            block = os.read(descriptor, min(1 << 20, before.st_size - len(raw)))
            if not block:
                raise AuditError(f"short read: {path.name}")
            raw += block
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    def identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            stat.S_IMODE(value.st_mode),
            value.st_nlink,
        )

    if identity(before) != identity(after):
        raise AuditError(f"file changed during read: {path.name}")
    return raw


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_new(path: Path, raw: bytes) -> dict[str, object]:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)
    if read_regular(path) != raw:
        raise AuditError(f"evidence reread failed: {path.name}")
    return {"bytes": len(raw), "sha256": sha256_bytes(raw)}


def write_json_new(path: Path, payload: object) -> dict[str, object]:
    return write_new(path, canonical_json(payload))


def parse_xyz(raw: bytes) -> tuple[tuple[str, ...], list[list[float]]]:
    try:
        lines = raw.decode("ascii", errors="strict").splitlines()
        count = int(lines[0].strip())
    except (UnicodeDecodeError, ValueError, IndexError) as exc:
        raise AuditError("invalid XYZ header") from exc
    if len(lines) != count + 2:
        raise AuditError("XYZ line count drifted")
    elements: list[str] = []
    coordinates: list[list[float]] = []
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4:
            raise AuditError("invalid XYZ row")
        xyz = [float(value) for value in fields[1:]]
        if not all(math.isfinite(value) for value in xyz):
            raise AuditError("non-finite XYZ coordinate")
        elements.append(fields[0])
        coordinates.append(xyz)
    return tuple(elements), coordinates


def protocol_identity() -> dict[str, object]:
    return {
        "protocol_id": "phase9b-parent-level-p01",
        "phase": "gas",
        "mean_field": "closed-shell RKS",
        "functional_public_name": "omegaB97M-D3(BJ)",
        "pyscf_xc_alias": PARENT_XC,
        "pyscf_semilocal_libxc_id": 531,
        "pyscf_semilocal_libxc_name": "HYB_MGGA_XC_WB97M_V",
        "vv10_nonlocal_correlation": False,
        "dispersion": {
            "version": PARENT_DISPERSION,
            "damping": "Becke-Johnson rational",
            "parameters": PARENT_D3_PARAMETERS,
            "two_body": True,
            "atm_three_body": False,
        },
        "basis": PARENT_BASIS,
        "grid_level_selected_after_audit": 4,
        "grid_selection_reason": "no preregistered tolerance; select more robust level 4",
        "scf_conv_tol": SCF_TOLERANCE,
        "standard_max_cycles": SCF_MAX_CYCLES,
        "soscf_policy": "once_only_after_typed_scf_nonconvergence",
        "soscf_max_cycles": 200,
        "initial_guess": "minao",
        "dm0": False,
        "geometry_optimizer": "geomeTRIC",
        "geometry_max_steps": 100,
        "threads": THREADS,
        "cpu_affinity": [0, 1, 2, 3],
        "max_memory_mb": MEMORY_MB,
    }


def finite_float(value: object, *, label: str) -> float:
    if type(value) not in {int, float}:
        raise AuditError(f"{label} is not numeric")
    result = float(cast(float, value))
    if not math.isfinite(result):
        raise AuditError(f"{label} is non-finite")
    return result


def exact_int(value: object, *, label: str) -> int:
    if type(value) is not int:
        raise AuditError(f"{label} is not an integer")
    return value


def grid_difference(level3: dict[str, object], level4: dict[str, object]) -> dict[str, object]:
    energy3 = finite_float(level3["total_energy_hartree"], label="level3 energy")
    energy4 = finite_float(level4["total_energy_hartree"], label="level4 energy")
    d3_3 = finite_float(level3["d3_energy_hartree"], label="level3 D3")
    d3_4 = finite_float(level4["d3_energy_hartree"], label="level4 D3")
    return {
        "total_energy_level4_minus_level3_hartree": energy4 - energy3,
        "d3_level4_minus_level3_hartree": d3_4 - d3_3,
        "gradient_rms_level4_minus_level3_hartree_per_bohr": finite_float(
            level4["gradient_rms_hartree_per_bohr"], label="level4 gradient RMS"
        )
        - finite_float(level3["gradient_rms_hartree_per_bohr"], label="level3 gradient RMS"),
        "gradient_max_level4_minus_level3_hartree_per_bohr": finite_float(
            level4["gradient_max_hartree_per_bohr"], label="level4 gradient maximum"
        )
        - finite_float(level3["gradient_max_hartree_per_bohr"], label="level3 gradient maximum"),
        "scf_cycles_level4_minus_level3": exact_int(level4["scf_cycles"], label="level4 cycles")
        - exact_int(level3["scf_cycles"], label="level3 cycles"),
        "wall_level4_minus_level3_seconds": finite_float(
            level4["wall_seconds"], label="level4 wall"
        )
        - finite_float(level3["wall_seconds"], label="level3 wall"),
        "preregistered_numeric_threshold": False,
        "selected_grid_level": 4,
    }


def compare_d3(
    pyscf_payload: dict[str, object], aimnet_payload: dict[str, object]
) -> dict[str, object]:
    pyscf_energy = finite_float(pyscf_payload["d3_energy_hartree"], label="PySCF D3 energy")
    aimnet_energy = finite_float(aimnet_payload["d3_energy_hartree"], label="AIMNet D3 energy")
    pyscf_gradient = pyscf_payload["d3_gradient_hartree_per_bohr"]
    aimnet_gradient = aimnet_payload["d3_gradient_hartree_per_bohr"]
    if not isinstance(pyscf_gradient, list) or not isinstance(aimnet_gradient, list):
        raise AuditError("D3 gradient payload is not a list")
    if len(pyscf_gradient) != len(aimnet_gradient):
        raise AuditError("D3 gradient atom count differs")
    maximum = 0.0
    rms_accumulator = 0.0
    count = 0
    for left, right in zip(pyscf_gradient, aimnet_gradient, strict=True):
        if (
            not isinstance(left, list)
            or not isinstance(right, list)
            or len(left) != 3
            or len(right) != 3
        ):
            raise AuditError("D3 gradient shape differs")
        for lhs, rhs in zip(left, right, strict=True):
            delta = finite_float(lhs, label="PySCF D3 gradient") - finite_float(
                rhs, label="AIMNet D3 gradient"
            )
            maximum = max(maximum, abs(delta))
            rms_accumulator += delta * delta
            count += 1
    return {
        "energy_difference_hartree": pyscf_energy - aimnet_energy,
        "gradient_rms_difference_hartree_per_bohr": math.sqrt(rms_accumulator / count),
        "gradient_max_difference_hartree_per_bohr": maximum,
        "same_parameters": pyscf_payload["d3_parameters"] == aimnet_payload["d3_parameters"],
        "two_body_both": pyscf_payload["atm_three_body"] is False
        and aimnet_payload["atm_three_body"] is False,
    }


def _configure_runtime(root: Path) -> None:
    for name in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[name] = str(THREADS)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    temporary = root / "runtime_tmp"
    temporary.mkdir(mode=0o700, exist_ok=False)
    os.environ["TMPDIR"] = str(temporary)
    raw_setaffinity = getattr(os, "sched_setaffinity", None)
    raw_getaffinity = getattr(os, "sched_getaffinity", None)
    if raw_setaffinity is None or raw_getaffinity is None:
        raise AuditError("Linux affinity API unavailable")
    setaffinity = cast(Callable[[int, set[int]], None], raw_setaffinity)
    getaffinity = cast(Callable[[int], set[int]], raw_getaffinity)
    setaffinity(0, {0, 1, 2, 3})
    if set(getaffinity(0)) != {0, 1, 2, 3}:
        raise AuditError("CPU affinity drifted")


def _rks_result(
    *, raw_xyz: bytes, grid_level: int, displaced_x: float | None = None
) -> dict[str, object]:
    from pyscf import dft, gto, lib  # type: ignore[import-untyped]
    from pyscf.dft.rks import parse_dft  # type: ignore[import-untyped]
    from pyscf.dispersion.dftd3 import DFTD3Dispersion  # type: ignore[import-untyped]

    elements, coordinates = parse_xyz(raw_xyz)
    if displaced_x is not None:
        coordinates[14][0] += displaced_x
    molecule = gto.M(
        atom=list(zip(elements, coordinates, strict=True)),
        unit="Angstrom",
        basis=PARENT_BASIS,
        charge=1,
        spin=0,
        max_memory=MEMORY_MB,
        verbose=4,
    )
    if (
        molecule.nelectron != 160
        or tuple(molecule.atom_symbol(i) for i in range(molecule.natm)) != elements
    ):
        raise AuditError("PySCF molecule identity drifted")
    if lib.num_threads(THREADS) != THREADS:
        raise AuditError("PySCF thread count drifted")
    mean_field = dft.RKS(molecule)
    mean_field.xc = PARENT_XC
    mean_field.grids.level = grid_level
    mean_field.conv_tol = SCF_TOLERANCE
    mean_field.max_cycle = SCF_MAX_CYCLES
    started = time.monotonic()
    user_before = resource.getrusage(resource.RUSAGE_SELF)
    energy = float(mean_field.kernel())
    if not mean_field.converged or not math.isfinite(energy):
        raise AuditError(f"grid {grid_level} parent-level SCF did not converge")
    if displaced_x is not None:
        return {"energy_hartree": energy, "scf_cycles": int(mean_field.cycles)}
    gradient = mean_field.nuc_grad_method().kernel()
    if gradient.shape != (26, 3) or not bool(__import__("numpy").isfinite(gradient).all()):
        raise AuditError("parent-level analytic gradient is invalid")
    summary = mean_field.scf_summary
    components = {key: float(summary[key]) for key in ("nuc", "e1", "coul", "exc", "dispersion")}
    reconstructed = sum(components.values())
    if abs(reconstructed - energy) > 1.0e-12:
        raise AuditError("parent-level SCF summary does not reconstruct total energy")
    d3 = DFTD3Dispersion(molecule, xc=PARENT_D3_METHOD, version=PARENT_DISPERSION, atm=False)
    d3_audit = d3.get_dispersion(grad=True)
    d3_energy = float(d3_audit["energy"])
    d3_gradient = __import__("numpy").asarray(d3_audit["gradient"], dtype=float)
    if abs(d3_energy - components["dispersion"]) > 1.0e-12:
        raise AuditError("independent D3 energy does not match SCF summary")
    if d3_gradient.shape != (26, 3) or not bool(__import__("numpy").isfinite(d3_gradient).all()):
        raise AuditError("independent D3 gradient is invalid")
    elapsed = time.monotonic() - started
    user_after = resource.getrusage(resource.RUSAGE_SELF)
    parsed_xc, parsed_nlc, parsed_disp = parse_dft(PARENT_XC)
    return {
        "grid_level": grid_level,
        "total_energy_hartree": energy,
        "components_hartree": components,
        "reconstructed_energy_hartree": reconstructed,
        "reconstruction_error_hartree": abs(reconstructed - energy),
        "d3_energy_hartree": d3_energy,
        "d3_gradient_hartree_per_bohr": d3_gradient.tolist(),
        "total_gradient_hartree_per_bohr": gradient.tolist(),
        "gradient_rms_hartree_per_bohr": float(
            __import__("numpy").sqrt(__import__("numpy").mean(gradient**2))
        ),
        "gradient_max_hartree_per_bohr": float(
            __import__("numpy").max(__import__("numpy").abs(gradient))
        ),
        "gradient_finite": True,
        "scf_cycles": int(mean_field.cycles),
        "scf_converged": True,
        "wall_seconds": elapsed,
        "process_user_cpu_seconds": user_after.ru_utime - user_before.ru_utime,
        "process_system_cpu_seconds": user_after.ru_stime - user_before.ru_stime,
        "maximum_rss": int(user_after.ru_maxrss),
        "parsed_xc": parsed_xc,
        "parsed_nlc": parsed_nlc,
        "parsed_dispersion": parsed_disp,
        "do_nlc": bool(mean_field.do_nlc()),
        "d3_parameters": PARENT_D3_PARAMETERS,
        "atm_three_body": False,
        "basis": PARENT_BASIS,
    }


def pyscf_audit(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(strict=True)
    _configure_runtime(root)
    raw = read_regular(Path(args.xyz).resolve(strict=True))
    if sha256_bytes(raw) != args.xyz_sha256:
        raise AuditError("implementation-audit XYZ identity drifted")
    levels = {str(level): _rks_result(raw_xyz=raw, grid_level=level) for level in GRID_LEVELS}
    plus = _rks_result(raw_xyz=raw, grid_level=4, displaced_x=FINITE_DIFFERENCE_STEP_ANGSTROM)
    minus = _rks_result(raw_xyz=raw, grid_level=4, displaced_x=-FINITE_DIFFERENCE_STEP_ANGSTROM)
    finite_difference_hartree_per_angstrom = (
        finite_float(plus["energy_hartree"], label="positive displacement energy")
        - finite_float(minus["energy_hartree"], label="negative displacement energy")
    ) / (2.0 * FINITE_DIFFERENCE_STEP_ANGSTROM)
    gradient_payload = levels["4"]["total_gradient_hartree_per_bohr"]
    if not isinstance(gradient_payload, list) or not isinstance(gradient_payload[14], list):
        raise AuditError("level4 total gradient shape is invalid")
    analytic_hartree_per_bohr = finite_float(
        gradient_payload[14][0], label="analytic total gradient component"
    )
    finite_difference_hartree_per_bohr = finite_difference_hartree_per_angstrom * 0.529177210903
    payload = {
        "schema_version": SCHEMA,
        "kind": "pyscf_parent_implementation_audit",
        "xyz_sha256": sha256_bytes(raw),
        "xyz_bytes": len(raw),
        "python": platform.python_version(),
        "pyscf": metadata.version("pyscf"),
        "pyscf_dispersion": metadata.version("pyscf-dispersion"),
        "geometric": metadata.version("geometric"),
        "libxc": __import__("pyscf.dft.libxc", fromlist=["__version__"]).__version__,
        "protocol": protocol_identity(),
        "grid_results": levels,
        "grid_difference": grid_difference(levels["3"], levels["4"]),
        "finite_difference_spot_check": {
            "atom_index": 14,
            "coordinate": "x",
            "step_angstrom": FINITE_DIFFERENCE_STEP_ANGSTROM,
            "plus_energy_hartree": plus["energy_hartree"],
            "minus_energy_hartree": minus["energy_hartree"],
            "total_energy_derivative_hartree_per_angstrom": finite_difference_hartree_per_angstrom,
            "finite_difference_hartree_per_bohr": finite_difference_hartree_per_bohr,
            "analytic_total_gradient_hartree_per_bohr": analytic_hartree_per_bohr,
            "absolute_difference_hartree_per_bohr": abs(
                finite_difference_hartree_per_bohr - analytic_hartree_per_bohr
            ),
            "note": "raw diagnostic; no post-hoc acceptance tolerance introduced",
        },
        "orca_cross_check": "not_available_usr_bin_orca_is_screen_reader_46_1",
        "final_grid_level": 4,
        "status": "PASS",
    }
    write_json_new(root / "pyscf_parent_method_identity.json", payload)
    return 0


def aimnet_d3_audit(args: argparse.Namespace) -> int:
    import numpy as np
    import torch  # type: ignore[import-not-found]
    from aimnet.modules import DFTD3  # type: ignore[import-not-found]
    from ase.data import atomic_numbers
    from nvalchemiops.torch.interactions.dispersion import dftd3  # type: ignore[import-not-found]

    root = Path(args.root).resolve(strict=True)
    raw = read_regular(Path(args.xyz).resolve(strict=True))
    if sha256_bytes(raw) != args.xyz_sha256:
        raise AuditError("AIMNet D3 audit XYZ identity drifted")
    elements, coordinates = parse_xyz(raw)
    numbers = torch.tensor([atomic_numbers[element] for element in elements], dtype=torch.int32)
    positions = torch.tensor(coordinates, dtype=torch.float64) / 0.529177210903
    natm = len(elements)
    neighbors = torch.tensor(
        [[j for j in range(natm) if j != i] for i in range(natm)], dtype=torch.int32
    )
    model = DFTD3(**PARENT_D3_PARAMETERS, cutoff=100.0, smoothing_fraction=0.0).cpu()
    energy, forces, _ = dftd3(
        positions=positions,
        numbers=numbers,
        a1=PARENT_D3_PARAMETERS["a1"],
        a2=PARENT_D3_PARAMETERS["a2"],
        s8=PARENT_D3_PARAMETERS["s8"],
        s6=PARENT_D3_PARAMETERS["s6"],
        covalent_radii=model.rcov,
        r4r2=model.r4r2,
        c6_reference=model.c6ab,
        coord_num_ref=model.cn_ref,
        neighbor_matrix=neighbors,
        fill_value=natm,
        num_systems=1,
        device="cpu",
    )
    energy_value = float(energy.reshape(-1)[0])
    gradient = -forces.detach().cpu().numpy()
    if (
        not math.isfinite(energy_value)
        or gradient.shape != (natm, 3)
        or not np.isfinite(gradient).all()
    ):
        raise AuditError("AIMNet D3 audit returned invalid values")
    payload = {
        "schema_version": SCHEMA,
        "kind": "aimnet_external_d3_audit",
        "xyz_sha256": sha256_bytes(raw),
        "xyz_bytes": len(raw),
        "aimnet": metadata.version("aimnet"),
        "torch": torch.__version__,
        "d3_energy_hartree": energy_value,
        "d3_gradient_hartree_per_bohr": gradient.tolist(),
        "d3_parameters": PARENT_D3_PARAMETERS,
        "damping": "Becke-Johnson rational",
        "two_body": True,
        "atm_three_body": False,
        "status": "PASS",
    }
    write_json_new(root / "aimnet_model_identity.json", payload)
    return 0


def finalize(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(strict=True)
    pyscf_payload = json.loads(read_regular(root / "pyscf_parent_method_identity.json"))
    aimnet_payload = json.loads(read_regular(root / "aimnet_model_identity.json"))
    level4 = pyscf_payload["grid_results"]["4"]
    comparison = compare_d3(level4, aimnet_payload)
    if comparison["same_parameters"] is not True or comparison["two_body_both"] is not True:
        raise AuditError("AIMNet/PySCF D3 identities differ")
    payload = {
        "schema_version": SCHEMA,
        "status": "PASS",
        "parent_method_identity_established": True,
        "aimnet_short_range_reference": "omegaB97M short-range labels with D3 removed",
        "reference_basis": "def2-TZVPP",
        "dispersion_training_and_inference": (
            "D3 removed from training labels; external two-body D3(BJ) at inference"
        ),
        "dispersion_comparison": comparison,
        "protocol": protocol_identity(),
        "grid_difference": pyscf_payload["grid_difference"],
        "implementation_smoke_sha256": sha256_bytes(canonical_json(pyscf_payload)),
        "aimnet_d3_audit_sha256": sha256_bytes(canonical_json(aimnet_payload)),
        "no_chemistry_optimization": True,
        "production_accepted": False,
    }
    write_json_new(root / "final_protocol.json", payload)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("pyscf-audit", "aimnet-d3-audit"):
        item = sub.add_parser(name)
        item.add_argument("--root", required=True)
        item.add_argument("--xyz", required=True)
        item.add_argument("--xyz-sha256", required=True)
    final = sub.add_parser("finalize")
    final.add_argument("--root", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "pyscf-audit":
        return pyscf_audit(args)
    if args.command == "aimnet-d3-audit":
        return aimnet_d3_audit(args)
    if args.command == "finalize":
        return finalize(args)
    raise AuditError("unknown command")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise
