#!/usr/bin/env python3
"""One-candidate parent-level P01 paired science benchmark.

The script reuses the existing AIMNet2 pilot, geometry review, typed PySCF
backend, and V006 evidence utilities.  It changes only the science-pilot DFT
profile to the audited parent level; no production authority is imported.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import math
import os
import resource
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

CANDIDATE: Final = "LBNPGYISTSLAHY-UHFFFAOYSA-N"
ENDPOINTS: Final = ("cation", "neutral")
CHARGES: Final = {"cation": 1, "neutral": 0}
MULTIPLICITIES: Final = {"cation": 1, "neutral": 1}
ATOM_COUNTS: Final = {"cation": 26, "neutral": 25}
ELECTRONS: Final = 160
INPUT_SHA256: Final = {
    "cation": "543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286",
    "neutral": "af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8",
}
WEIGHT_SHA256: Final = "f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28"
PARENT_XC: Final = "wb97m-d3bj"
PARENT_D3_METHOD: Final = "wb97m"
PARENT_BASIS: Final = "def2-tzvpp"
GRID_LEVEL: Final = 4
HARTREE_TO_KCAL: Final = 627.509474
PROTON_CORRECTION: Final = 6.28
GROUP_A_LIMIT_SECONDS: Final = 21600
GROUP_B_LIMIT_SECONDS: Final = 86400
SHORT_TEMP_CONTROL: Final = "NHC_P01R2_SHORT_TMP_ROOT"
SHORT_TEMP_VARIABLES: Final = (
    "TMPDIR",
    "TMP",
    "TEMP",
    "CUDA_CACHE_PATH",
    "TORCH_EXTENSIONS_DIR",
    "TORCHINDUCTOR_CACHE_DIR",
    "TRITON_CACHE_DIR",
    "XDG_CACHE_HOME",
    "NUMBA_CACHE_DIR",
    "TORCH_HOME",
    "HF_HOME",
)
SCHEMA: Final = "nhc-phase9b-parent-level-paired-benchmark-p01-v1"


class BenchmarkError(RuntimeError):
    """The non-production parent-level benchmark could not close."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BenchmarkError(f"cannot load helper {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def deprotonation(cation: float, neutral: float) -> dict[str, object]:
    if not all(math.isfinite(value) for value in (cation, neutral)):
        raise BenchmarkError("non-finite endpoint energy")
    difference = neutral - cation
    electronic = difference * HARTREE_TO_KCAL
    return {
        "cation_energy_hartree": cation,
        "neutral_energy_hartree": neutral,
        "hartree_difference": difference,
        "conversion_factor_kcal_per_hartree": HARTREE_TO_KCAL,
        "electronic_difference_kcal_per_mol": electronic,
        "proton_correction_kcal_per_mol": PROTON_CORRECTION,
        "value_kcal_per_mol": electronic - PROTON_CORRECTION,
        "formula": "((E_neutral_PySCF - E_cation_PySCF) * 627.509474) - 6.28",
        "aimnet2_energy_used": False,
        "lower_is_better": True,
    }


def timing_comparison(group_a: float, group_b: float) -> dict[str, float]:
    if group_a <= 0 or group_b <= 0:
        raise BenchmarkError("route walls must be positive")
    saved = group_b - group_a
    return {
        "group_a_total_seconds": group_a,
        "group_b_total_seconds": group_b,
        "time_saved_seconds": saved,
        "speedup_group_b_over_group_a": group_b / group_a,
        "percent_saved": saved / group_b * 100.0,
    }


def timeout_lower_bound(group_a: float, observed_group_b: float) -> dict[str, float]:
    if group_a <= 0 or observed_group_b <= 0:
        raise BenchmarkError("route walls must be positive")
    saved = observed_group_b - group_a
    return {
        "group_a_total_seconds": group_a,
        "group_b_observed_seconds": observed_group_b,
        "minimum_time_saved_seconds": saved,
        "minimum_speedup_lower_bound": observed_group_b / group_a,
        "minimum_percent_saved_lower_bound": saved / observed_group_b * 100.0,
    }


def protocol(
    *,
    threads: int = 4,
    cpu_affinity: Sequence[int] = (0, 1, 2, 3),
    max_memory_mb: int = 12000,
) -> dict[str, object]:
    return {
        "protocol_id": "phase9b-parent-level-p01",
        "phase": "gas",
        "mean_field": "RKS",
        "functional": "omegaB97M-D3(BJ)",
        "pyscf_xc_alias": PARENT_XC,
        "vv10": False,
        "dispersion": "two-body D3(BJ)",
        "atm": False,
        "basis": "def2-TZVPP",
        "grid_level": GRID_LEVEL,
        "conv_tol": 1.0e-9,
        "standard_max_cycles": 100,
        "soscf_policy": "once_only_after_typed_scf_nonconvergence",
        "soscf_max_cycles": 200,
        "initial_guess": "minao",
        "dm0": False,
        "geometry_optimizer": "geomeTRIC",
        "aimnet2_handoff_profile": "GAU_LOOSE",
        "parent_first_observation": "PARENT_GAU_LOOSE_GRADIENT_CHECK",
        "parent_first_observation_is_full_gau_loose": False,
        "parent_final_convergence_profile": "GAU",
        "single_point_only": False,
        "geometry_max_steps": 100,
        "threads": threads,
        "cpu_affinity": list(cpu_affinity),
        "max_memory_mb": max_memory_mb,
    }


def protocols_equal(left: dict[str, object], right: dict[str, object]) -> bool:
    return left == right == protocol()


def _clean_environment() -> dict[str, str]:
    result = dict(os.environ)
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        result.pop(name, None)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["HF_HUB_OFFLINE"] = "1"
    result["TRANSFORMERS_OFFLINE"] = "1"
    return result


def _validate_short_temp_environment(environment: dict[str, str]) -> None:
    root_text = environment.get(SHORT_TEMP_CONTROL)
    if not root_text:
        return
    root = Path(root_text).resolve(strict=True)
    for name in SHORT_TEMP_VARIABLES:
        value = environment.get(name)
        if not value:
            raise BenchmarkError(f"short temporary environment omitted {name}")
        destination = Path(value).resolve(strict=True)
        try:
            destination.relative_to(root)
        except ValueError as exc:
            raise BenchmarkError(f"short temporary environment escaped root: {name}") from exc


def _request(
    module: Any,
    helper: Any,
    endpoint: str,
    path: Path,
    route: str,
    *,
    expected_sha256: str,
    expected_atom_count: int,
    expected_electron_count: int,
) -> tuple[Any, dict[str, object]]:
    raw = helper.read_regular(path)
    if route == "pure_pyscf" and sha256_bytes(raw) != expected_sha256:
        raise BenchmarkError(f"{endpoint} frozen input bytes drifted")
    geometry = module._parse_xyz(raw, label=f"P01 {route} {endpoint}")
    elements = tuple(atom.element for atom in geometry.atoms)
    if len(elements) != expected_atom_count:
        raise BenchmarkError(f"{endpoint} atom count drifted")
    if (
        module._electron_count_for_geometry(geometry, charge=CHARGES[endpoint])
        != expected_electron_count
    ):
        raise BenchmarkError(f"{endpoint} electron count drifted")
    request = module.EndpointRequest(
        name=cast(Any, endpoint),
        xyz_relative_path=path.name,
        xyz_path=path,
        xyz_sha256=sha256_bytes(raw),
        charge=CHARGES[endpoint],
        multiplicity=MULTIPLICITIES[endpoint],
        electron_count=expected_electron_count,
        geometry=geometry,
    )
    return request, {
        "source_sha256": sha256_bytes(raw),
        "source_bytes": len(raw),
        "parser_sha256": sha256_bytes(raw),
        "parser_bytes": len(raw),
        "atom_order_sha256": sha256_bytes(" ".join(elements).encode()),
        "charge": CHARGES[endpoint],
        "multiplicity": MULTIPLICITIES[endpoint],
        "spin": 0,
        "atom_count": len(elements),
        "electron_count": expected_electron_count,
        "exact_bytes": True,
        "units": "Angstrom",
    }


def build_parent_backend(
    *,
    pilot: Any,
    module: Any,
    threads: int = 4,
    memory_mb: int = 12000,
    expected_electron_count: int = ELECTRONS,
    training_recorder: Any | None = None,
    first_parent_observation: Callable[[Mapping[str, object], str], None] | None = None,
) -> Any:
    """Adapt the audited pilot backend without changing production source."""

    base = pilot._SciencePilotPySCFBackend.build(module)
    base_type = type(base)

    class ParentBackend(base_type):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__()
            self._parent_modules: Any = None
            self.parent_identity: dict[str, object] = {}
            self.parent_optimization_metrics: dict[str, dict[str, object]] = {}

        def _load_modules(self) -> object:
            if self._parent_modules is not None:
                return self._parent_modules
            modules = super()._load_modules()
            original_dftd3 = modules.dftd3
            original_geometric_solver = modules.geometric_solver
            backend = self

            class ParentD3Audit:
                @staticmethod
                def DFTD3Dispersion(
                    molecule: object, *, xc: str, version: str, atm: bool
                ) -> object:
                    del xc
                    return original_dftd3.DFTD3Dispersion(
                        molecule,
                        xc=PARENT_D3_METHOD,
                        version=version,
                        atm=atm,
                    )

            class ParentGeometricSolver:
                @staticmethod
                def kernel(method: object, *positional: object, **kwargs: object) -> object:
                    original_callback = kwargs.get("callback")

                    def callback(environment: dict[str, object]) -> None:
                        context = backend._pilot_context
                        if context is None or context[1] != "optimization":
                            raise BenchmarkError("parent callback context drifted")
                        endpoint = context[0]
                        record = backend.parent_optimization_metrics.setdefault(
                            endpoint,
                            {
                                "parent_energy_evaluations": 0,
                                "parent_gradient_evaluations": 0,
                                "cumulative_scf_cycles": 0,
                                "scf_cycle_measurement_complete": True,
                            },
                        )
                        record["parent_energy_evaluations"] = (
                            cast(int, record["parent_energy_evaluations"]) + 1
                        )
                        record["parent_gradient_evaluations"] = (
                            cast(int, record["parent_gradient_evaluations"]) + 1
                        )
                        scanner = environment.get("g_scanner")
                        raw_cycles = getattr(scanner, "cycles", None)
                        if type(raw_cycles) is int and raw_cycles >= 0:
                            record["cumulative_scf_cycles"] = (
                                cast(int, record["cumulative_scf_cycles"]) + raw_cycles
                            )
                        else:
                            record["scf_cycle_measurement_complete"] = False
                        if first_parent_observation is not None:
                            first_parent_observation(environment, endpoint)
                        if callable(original_callback):
                            original_callback(environment)
                        if training_recorder is not None:
                            training_recorder.capture(environment, endpoint=endpoint)

                    kwargs["callback"] = callback
                    requested_profile = kwargs.get("convergence_set")
                    if requested_profile not in {None, "GAU"}:
                        raise BenchmarkError("parent geometry convergence profile drifted")
                    kwargs["convergence_set"] = "GAU"
                    return original_geometric_solver.kernel(method, *positional, **kwargs)

            self._parent_modules = dataclasses.replace(
                modules,
                dftd3=ParentD3Audit,
                geometric_solver=ParentGeometricSolver,
            )
            return self._parent_modules

        def _mean_field(self, **kwargs: object) -> tuple[object, object, object]:
            geometry = cast(Any, kwargs["geometry"])
            charge = int(cast(int, kwargs["charge"]))
            multiplicity = int(cast(int, kwargs["multiplicity"]))
            strategy = str(kwargs["strategy"])
            modules = cast(Any, self._load_modules())
            if multiplicity != 1 or charge not in {0, 1}:
                raise BenchmarkError("parent backend endpoint identity drifted")
            electron_count = module._electron_count_for_geometry(geometry, charge=charge)
            if electron_count != expected_electron_count:
                raise BenchmarkError("parent backend electron count drifted")
            atom_spec = [(atom.element, (atom.x, atom.y, atom.z)) for atom in geometry.atoms]
            molecule = modules.gto.M(
                atom=atom_spec,
                unit="Angstrom",
                basis=PARENT_BASIS,
                charge=charge,
                spin=0,
                max_memory=memory_mb,
                verbose=0,
            )
            if tuple(molecule.atom_symbol(i) for i in range(molecule.natm)) != tuple(
                atom.element for atom in geometry.atoms
            ):
                raise BenchmarkError("parent backend atom order drifted")
            if int(molecule.nelectron) != electron_count or int(molecule.spin) != 0:
                raise BenchmarkError("parent backend electron or spin identity drifted")
            mean_field = modules.dft.RKS(molecule)
            if modules.lib.num_threads(threads) != threads or modules.lib.num_threads() != threads:
                raise BenchmarkError("parent PySCF thread binding drifted")
            mean_field.xc = PARENT_XC
            mean_field.grids.level = GRID_LEVEL
            mean_field.conv_tol = 1.0e-9
            mean_field.max_cycle = 100 if strategy == "standard" else 200
            mean_field.disp = "d3bj"
            self._require_exact_d3bj_owner(mean_field, label="parent mean field")
            if mean_field.do_nlc():
                raise BenchmarkError("parent method silently enabled VV10")
            if strategy == "soscf":
                mean_field = mean_field.newton()
                mean_field.max_cycle = 200
                self._energy_owner(mean_field, strategy=strategy, label="parent SOSCF")
            runtime = module._runtime_evidence(
                modules=modules,
                molecule=molecule,
                mean_field=mean_field,
                electron_count=electron_count,
                charge=charge,
            )
            self._pilot_last_mean_field = mean_field
            self.parent_identity = {
                "xc": PARENT_XC,
                "basis": PARENT_BASIS,
                "grid_level": GRID_LEVEL,
                "dispersion": "d3bj",
                "atm": False,
                "vv10": False,
                "init_guess": getattr(mean_field, "init_guess", None),
                "dm0_passed": False,
                "threads": threads,
                "max_memory_mb": memory_mb,
            }
            return mean_field, runtime, modules

    return ParentBackend()


def _rusage() -> tuple[float, float, int | str]:
    observed = resource.getrusage(resource.RUSAGE_SELF)
    maximum_rss: int | str = int(observed.ru_maxrss) if observed.ru_maxrss >= 0 else "unavailable"
    return float(observed.ru_utime), float(observed.ru_stime), maximum_rss


def _parse_cpu_list(value: str) -> tuple[int, ...]:
    result: set[int] = set()
    for item in value.split(","):
        if "-" in item:
            left, right = item.split("-", 1)
            result.update(range(int(left), int(right) + 1))
        else:
            result.add(int(item))
    if not result:
        raise BenchmarkError("empty CPU list")
    return tuple(sorted(result))


def _configure_parent_resources(
    *, module: Any, root: Path, threads: int, cpu_list: tuple[int, ...], memory_mb: int
) -> None:
    if threads <= 0 or threads > len(cpu_list):
        raise BenchmarkError("thread count exceeds CPU affinity")
    environment = {
        "BLIS_NUM_THREADS": str(threads),
        "GOTO_NUM_THREADS": str(threads),
        "MKL_DYNAMIC": "FALSE",
        "MKL_NUM_THREADS": str(threads),
        "NUMEXPR_NUM_THREADS": str(threads),
        "OMP_DYNAMIC": "FALSE",
        "OMP_MAX_ACTIVE_LEVELS": "1",
        "OMP_NESTED": "FALSE",
        "OMP_NUM_THREADS": str(threads),
        "OMP_THREAD_LIMIT": str(threads),
        "OMP_WAIT_POLICY": "PASSIVE",
        "OMP_PROC_BIND": "close",
        "OMP_PLACES": "cores",
        "OPENBLAS_NUM_THREADS": str(threads),
        "VECLIB_MAXIMUM_THREADS": str(threads),
    }
    os.environ.update(environment)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    if os.environ.get(SHORT_TEMP_CONTROL):
        _validate_short_temp_environment(dict(os.environ))
    else:
        os.environ["TMPDIR"] = str(root / "runtime_tmp")
    module.COMPUTE_THREADS = threads
    module.PYSCF_MAX_MEMORY_MB = memory_mb
    module.THREAD_ENVIRONMENT = environment
    module._CANONICAL_THREAD_ENVIRONMENT = tuple(sorted(environment.items()))
    linux_os = cast(Any, os)
    linux_os.sched_setaffinity(0, set(cpu_list))
    if tuple(sorted(linux_os.sched_getaffinity(0))) != cpu_list:
        raise BenchmarkError("parent CPU affinity drifted")
    if not os.environ.get(SHORT_TEMP_CONTROL):
        (root / "runtime_tmp").mkdir(mode=0o700, exist_ok=False)


def _array_rows(value: object, *, label: str) -> list[list[float]]:
    projected = value.tolist() if hasattr(value, "tolist") else value
    if not isinstance(projected, (list, tuple)):
        raise BenchmarkError(f"{label} is not an array")
    rows: list[list[float]] = []
    for raw_row in projected:
        if not isinstance(raw_row, (list, tuple)) or len(raw_row) != 3:
            raise BenchmarkError(f"{label} shape drifted")
        rows.append([float(component) for component in raw_row])
    if not rows:
        raise BenchmarkError(f"{label} is empty")
    return rows


def _first_parent_payload(
    *,
    handoff_module: Any,
    environment: Mapping[str, object],
    candidate: str,
    endpoint: str,
    route: str,
    expected_elements: tuple[str, ...],
    topology_valid: bool,
    profile: Any,
) -> dict[str, object]:
    scanner = environment.get("g_scanner")
    molecule = environment.get("mol")
    energy_raw = environment.get("energy")
    gradient_raw = environment.get("gradients")
    energy = float(energy_raw) if isinstance(energy_raw, (int, float)) else None
    gradients: list[list[float]] | None
    try:
        gradients = _array_rows(gradient_raw, label="first parent analytic gradient")
    except (BenchmarkError, TypeError, ValueError):
        gradients = None
    elements: tuple[str, ...] = ()
    coordinates_finite = False
    charge_multiplicity_preserved = False
    if molecule is not None:
        try:
            molecule_any = cast(Any, molecule)
            natm = int(molecule_any.natm)
            elements = tuple(str(molecule_any.atom_symbol(index)) for index in range(natm))
            coordinates = _array_rows(
                molecule_any.atom_coords(unit="Angstrom"), label="first parent coordinates"
            )
            coordinates_finite = all(
                math.isfinite(component) for row in coordinates for component in row
            )
            charge_multiplicity_preserved = (
                int(molecule_any.charge) == CHARGES[endpoint]
                and int(molecule_any.spin) == MULTIPLICITIES[endpoint] - 1
            )
        except (AttributeError, BenchmarkError, TypeError, ValueError):
            coordinates_finite = False
    classification = handoff_module.classify_first_parent_gradient(
        profile=profile,
        scf_converged=getattr(scanner, "converged", None) is True,
        energy_hartree=energy,
        gradient_hartree_bohr=gradients,
        coordinates_finite=coordinates_finite,
        atom_identity_preserved=elements == expected_elements,
        charge_multiplicity_preserved=charge_multiplicity_preserved,
        topology_valid=topology_valid,
    )
    classification.update(
        {
            "candidate": candidate,
            "endpoint": endpoint,
            "route": route,
            "atom_count": len(elements),
            "element_order_sha256": sha256_bytes(" ".join(elements).encode()),
        }
    )
    if route == "pure_pyscf" and classification["classification"] != "FAILED_PARENT_HANDOFF":
        classification["role"] = "FROZEN_INITIAL_PARENT_GRADIENT_BASELINE"
        classification["handoff_calibration_not_applicable"] = True
    return cast(dict[str, object], classification)


def parent_worker(args: argparse.Namespace) -> int:
    helper = load_module(Path(args.v006_helper).resolve(strict=True), "p01_v006_helper")
    pilot = load_module(Path(args.pilot_helper).resolve(strict=True), "p01_pilot_helper")
    single_point = load_module(Path(args.sp_helper).resolve(strict=True), "p01_sp_helper")
    handoff_helper_path = Path(args.handoff_helper).resolve(strict=True)
    gau_loose_contract_path = Path(args.gau_loose_contract).resolve(strict=True)
    handoff_module = load_module(handoff_helper_path, "p01_parent_handoff_helper")
    profile = handoff_module.load_gau_loose_profile(gau_loose_contract_path)
    source_root = Path(args.source_root).resolve(strict=True)
    pilot._add_source_root(source_root)
    from nhc_deprot_ranker.quantum import two_endpoint

    handoff_contract_identity = {
        "profile": "GAU_LOOSE",
        "contract_sha256": sha256_bytes(helper.read_regular(gau_loose_contract_path)),
        "helper_sha256": sha256_bytes(helper.read_regular(handoff_helper_path)),
    }

    root = Path(args.root).resolve(strict=True)
    training_recorder: Any | None = None
    if args.record_training_frames:
        if args.route != "pure_pyscf" or not args.training_data_helper:
            raise BenchmarkError("training frames require pure PySCF and an explicit helper")
        training_module = load_module(
            Path(args.training_data_helper).resolve(strict=True), "p01_training_data_helper"
        )
        training_recorder = training_module.TrainingFrameRecorder(
            root=root / "training_data",
            candidate=args.candidate,
            source_sha256=sha256_bytes(Path(__file__).resolve(strict=True).read_bytes()),
        )
    cpu_list = _parse_cpu_list(args.cpu_list)
    _configure_parent_resources(
        module=two_endpoint,
        root=root,
        threads=args.threads,
        cpu_list=cpu_list,
        memory_mb=args.max_memory_mb,
    )
    started = time.monotonic()
    deadline = started + float(args.route_limit_seconds)
    for name in ("input", "handoff", "optimization", "final_single_point"):
        helper.make_directory(root / name)
    for endpoint in ENDPOINTS:
        helper.make_directory(root / "optimization" / endpoint)
        helper.make_directory(root / "final_single_point" / endpoint)

    requests: dict[str, Any] = {}
    handoffs: dict[str, object] = {}
    expected_elements: dict[str, tuple[str, ...]] = {}
    for endpoint in ENDPOINTS:
        source = Path(getattr(args, f"{endpoint}_input")).resolve(strict=True)
        raw = helper.read_regular(source)
        destination = (
            root
            / "input"
            / f"{endpoint}_{'aimnet2_final' if args.route == 'assisted' else 'initial'}.xyz"
        )
        helper.write_new(destination, raw)
        request, handoff = _request(
            two_endpoint,
            helper,
            endpoint,
            destination,
            args.route,
            expected_sha256=getattr(args, f"{endpoint}_sha256"),
            expected_atom_count=getattr(args, f"{endpoint}_atom_count"),
            expected_electron_count=args.electron_count,
        )
        requests[endpoint] = request
        handoffs[endpoint] = handoff
        expected_elements[endpoint] = tuple(atom.element for atom in request.geometry.atoms)
        helper.write_json_new(root / "handoff" / f"{endpoint}.json", handoff)

    topology_valid = args.route == "pure_pyscf"
    if args.route == "assisted":
        if not args.structure_review_path:
            raise BenchmarkError("assisted route omitted the frozen structure review")
        review = json.loads(
            helper.read_regular(Path(args.structure_review_path).resolve(strict=True))
        )
        topology_valid = review.get("classification") == "SAME_BASIN_LIKELY"
        if not topology_valid:
            raise BenchmarkError("assisted structure review did not pass")

    first_parent_observations: dict[str, dict[str, object]] = {}

    def record_first_parent(environment: Mapping[str, object], endpoint: str) -> None:
        if endpoint in first_parent_observations:
            return
        payload = _first_parent_payload(
            handoff_module=handoff_module,
            environment=environment,
            candidate=args.candidate,
            endpoint=endpoint,
            route=args.route,
            expected_elements=expected_elements[endpoint],
            topology_valid=topology_valid,
            profile=profile,
        )
        first_parent_observations[endpoint] = payload
        destination = (
            root / "handoff" / f"{endpoint}_parent_gradient_check.json"
            if args.route == "assisted"
            else root / "optimization" / endpoint / "initial_parent_gradient.json"
        )
        helper.write_json_new(destination, payload)
        if payload["classification"] == "FAILED_PARENT_HANDOFF":
            raise BenchmarkError(f"{endpoint} failed parent handoff validation")

    backend = build_parent_backend(
        pilot=pilot,
        module=two_endpoint,
        threads=args.threads,
        memory_mb=args.max_memory_mb,
        expected_electron_count=args.electron_count,
        training_recorder=training_recorder,
        first_parent_observation=record_first_parent,
    )
    energies: dict[str, float] = {}
    endpoint_results: dict[str, object] = {}
    for endpoint in ENDPOINTS:
        if endpoint == "neutral" and "cation" not in energies:
            break
        endpoint_started = time.monotonic()
        before_user, before_system, _ = _rusage()
        output_root = root / "optimization" / endpoint
        with (
            helper._capture(output_root / "stdout", output_root / "stderr"),
            helper._cwd(output_root),
        ):
            optimization = two_endpoint._call_optimize(
                backend=backend,
                endpoint=requests[endpoint],
                strategy="standard",
                deadline=deadline,
            )
        if endpoint not in first_parent_observations:
            raise BenchmarkError(f"{endpoint} optimization omitted its first parent gradient")
        optimized_raw = optimization.geometry.to_xyz_bytes(
            comment=f"P01 {args.route} optimized {endpoint}"
        )
        helper.write_new(output_root / "final.xyz", optimized_raw)
        final_root = root / "final_single_point" / endpoint
        optimized_request = dataclasses.replace(
            requests[endpoint],
            xyz_relative_path="final.xyz",
            xyz_path=output_root / "final.xyz",
            xyz_sha256=sha256_bytes(optimized_raw),
            geometry=optimization.geometry,
        )
        with (
            helper._capture(final_root / "stdout", final_root / "stderr"),
            helper._cwd(final_root),
        ):
            result, strategy, attempts = single_point.run_single_point(
                module=two_endpoint,
                backend=backend,
                endpoint=optimized_request,
                deadline=deadline,
            )
        after_user, after_system, maximum_rss = _rusage()
        metrics = cast(dict[str, object], backend.pilot_metrics.get(endpoint, {}))
        optimization_metrics = cast(
            dict[str, object], backend.parent_optimization_metrics.get(endpoint, {})
        )
        payload: dict[str, object] = {
            "schema_version": SCHEMA,
            "candidate": args.candidate,
            "endpoint": endpoint,
            "route": args.route,
            "charge": CHARGES[endpoint],
            "multiplicity": 1,
            "spin": 0,
            "electron_count": args.electron_count,
            "protocol": protocol(
                threads=args.threads,
                cpu_affinity=cpu_list,
                max_memory_mb=args.max_memory_mb,
            ),
            "input": handoffs[endpoint],
            "parent_backend_identity": backend.parent_identity,
            "selected_strategy": strategy,
            "attempts": attempts,
            "scf_converged": bool(result.converged),
            "scf_cycles": metrics.get("final_scf_cycles", "unavailable"),
            "energy_hartree": float(result.energy_hartree),
            "d3": two_endpoint._final_dispersion_payload(result.dispersion),
            "runtime": two_endpoint._runtime_evidence_payload(result.runtime),
            "endpoint_wall_seconds": time.monotonic() - endpoint_started,
            "process_user_cpu_seconds": after_user - before_user,
            "process_system_cpu_seconds": after_system - before_system,
            "maximum_rss": maximum_rss,
            "geometry_optimization": None,
            "first_parent_observation": first_parent_observations[endpoint],
            "handoff_calibration_contract": handoff_contract_identity,
            "retry": False,
            "production_accepted": False,
        }
        training_endpoint_manifest: object = None
        if training_recorder is not None:
            training_endpoint_manifest = training_recorder.finalize_endpoint(endpoint)
        payload["geometry_optimization"] = {
            "converged": bool(optimization.geometry_converged),
            "final_state": handoff_module.final_parent_state(
                geometry_converged=bool(optimization.geometry_converged),
                final_single_point_converged=bool(result.converged),
            ),
            "profile": "GAU",
            "last_energy_hartree": float(optimization.last_energy_hartree),
            "wall_seconds": metrics.get("optimization_standard_wall_seconds", "unavailable"),
            "geometry_steps": optimization.dispersion.gradient_hook_calls,
            "geometry_steps_definition": "observed D3 gradient-hook evaluations",
            "d3_energy_calls": optimization.dispersion.energy_hook_calls,
            "d3_gradient_calls": optimization.dispersion.gradient_hook_calls,
            "parent_energy_evaluations": optimization_metrics.get(
                "parent_energy_evaluations", "unavailable"
            ),
            "parent_gradient_evaluations": optimization_metrics.get(
                "parent_gradient_evaluations", "unavailable"
            ),
            "cumulative_scf_cycles": (
                optimization_metrics.get("cumulative_scf_cycles", "unavailable")
                if optimization_metrics.get("scf_cycle_measurement_complete") is True
                else "unavailable"
            ),
            "final_xyz_sha256": sha256_bytes(optimized_raw),
            "final_xyz_bytes": len(optimized_raw),
            "training_endpoint_manifest": training_endpoint_manifest,
        }
        result_root = root / "final_single_point" / endpoint
        helper.write_json_new(result_root / "endpoint_result.json", payload)
        endpoint_results[endpoint] = payload
        energies[endpoint] = float(result.energy_hartree)

    if set(energies) != set(ENDPOINTS):
        raise BenchmarkError("route did not produce both endpoint energies")
    training_dataset_manifest: object = None
    if training_recorder is not None:
        training_dataset_manifest = training_recorder.finalize_dataset()
    terminal = {
        "schema_version": SCHEMA,
        "science_pilot_only": True,
        "production_accepted": False,
        "production_label_inserted": False,
        "candidate": args.candidate,
        "route": args.route,
        "single_candidate": True,
        "second_pure_pyscf_candidate": args.candidate != CANDIDATE,
        "batch": False,
        "retry": False,
        "training_data": training_dataset_manifest,
        "protocol": protocol(
            threads=args.threads,
            cpu_affinity=cpu_list,
            max_memory_mb=args.max_memory_mb,
        ),
        "handoff_calibration_contract": handoff_contract_identity,
        "endpoint_results": endpoint_results,
        "deprotonation": deprotonation(energies["cation"], energies["neutral"]),
        "internal_wall_seconds": time.monotonic() - started,
        "final_outcome": "PASS",
    }
    helper.write_json_new(root / "result.json", terminal)
    return 0


def assisted_controller(args: argparse.Namespace) -> int:
    helper = load_module(Path(args.v006_helper).resolve(strict=True), "p01_controller_helper")
    root = Path(args.root).resolve(strict=True)
    aimnet_root = Path(args.aimnet_root).resolve(strict=True)
    repo = Path(args.repo).resolve(strict=True)
    environment = _clean_environment()
    _validate_short_temp_environment(environment)
    with (
        (root / "aimnet_driver_stdout").open("xb", buffering=0) as stdout,
        (root / "aimnet_driver_stderr").open("xb", buffering=0) as stderr,
    ):
        result = subprocess.run(
            [
                args.mlff_python,
                "-I",
                "-B",
                str(repo / "scripts/phase9b_science_pilot.py"),
                "aimnet2",
                "--pilot-root",
                str(aimnet_root),
                "--source-root",
                str(repo / "src"),
                "--source-commit",
                args.source_commit,
                "--weight",
                args.weight,
                "--physical-gpu-index",
                str(args.gpu_index),
                "--physical-gpu-uuid",
                args.gpu_uuid,
                "--gau-loose-helper",
                str(repo / "scripts/phase9b_aimnet2_parent_handoff.py"),
                "--gau-loose-contract",
                str(repo / "docs/PHASE9B_AIMNET2_GAU_LOOSE_V001.yaml"),
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            timeout=1000,
            check=False,
        )
    summary = json.loads(helper.read_regular(aimnet_root / "aimnet2" / "summary.json"))
    if summary.get("model_load_count") != 1 or summary.get("endpoint_wrapper_count") != 2:
        raise BenchmarkError("AIMNet2 metrology drifted")
    if result.returncode != 0:
        failure = summary.get("failure")
        if not isinstance(failure, dict) or failure.get("exception_class") != "ScientificFailure":
            raise BenchmarkError("AIMNet2 route failed before a reviewable geometry was written")
    for endpoint in ENDPOINTS:
        if not (aimnet_root / "aimnet2" / endpoint / "final.xyz").is_file():
            raise BenchmarkError(f"AIMNet2 omitted the {endpoint} review geometry")
    with (
        (root / "review_stdout").open("xb") as stdout,
        (root / "review_stderr").open("xb") as stderr,
    ):
        subprocess.run(
            [
                args.gpupyscf_python,
                "-I",
                "-B",
                str(repo / "scripts/phase9b_science_pilot_geometry_review.py"),
                "--pilot-root",
                str(aimnet_root),
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            timeout=120,
            check=True,
        )
    review = json.loads(helper.read_regular(aimnet_root / "review_v004" / "review_result.json"))
    if review.get("classification") != "SAME_BASIN_LIKELY":
        raise BenchmarkError("fresh AIMNet2 geometry review did not pass")
    with (
        (root / "parent_driver_stdout").open("xb") as stdout,
        (root / "parent_driver_stderr").open("xb") as stderr,
    ):
        subprocess.run(
            [
                "taskset",
                "-c",
                args.cpu_list,
                args.gpupyscf_python,
                "-I",
                "-B",
                str(Path(__file__).resolve(strict=True)),
                "parent-worker",
                "--route",
                "assisted",
                "--route-limit-seconds",
                str(GROUP_A_LIMIT_SECONDS),
                "--threads",
                str(args.threads),
                "--cpu-list",
                args.cpu_list,
                "--max-memory-mb",
                str(args.max_memory_mb),
                "--root",
                str(root),
                "--source-root",
                str(repo / "src"),
                "--pilot-helper",
                str(repo / "scripts/phase9b_science_pilot.py"),
                "--sp-helper",
                str(repo / "scripts/phase9b_science_pilot_pyscf_continuation.py"),
                "--v006-helper",
                str(repo / "scripts/phase9b_science_pilot_timing_benchmark.py"),
                "--handoff-helper",
                str(repo / "scripts/phase9b_aimnet2_parent_handoff.py"),
                "--gau-loose-contract",
                str(repo / "docs/PHASE9B_AIMNET2_GAU_LOOSE_V001.yaml"),
                "--structure-review-path",
                str(aimnet_root / "review_v004" / "review_result.json"),
                "--cation-input",
                str(aimnet_root / "aimnet2" / "cation" / "final.xyz"),
                "--neutral-input",
                str(aimnet_root / "aimnet2" / "neutral" / "final.xyz"),
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            timeout=GROUP_A_LIMIT_SECONDS,
            check=True,
        )
    return 0


def final_result(args: argparse.Namespace) -> int:
    helper = load_module(Path(args.v006_helper).resolve(strict=True), "p01_final_helper")
    root = Path(args.root).resolve(strict=True)
    group_a = json.loads(helper.read_regular(root / "paired_anchor/group_a_assisted/result.json"))
    group_a_wall = helper.read_external_elapsed(
        root / "paired_anchor/group_a_assisted/route_elapsed_seconds"
    )
    group_b_elapsed = helper.read_external_elapsed(
        root / "paired_anchor/group_b_pure_pyscf/route_elapsed_seconds"
    )
    group_b_result_path = root / "paired_anchor/group_b_pure_pyscf/result.json"
    group_b_complete = group_b_result_path.exists()
    if group_b_complete:
        group_b = json.loads(helper.read_regular(group_b_result_path))
        comparison = timing_comparison(group_a_wall, group_b_elapsed)
        outcome = "PAIRED_PASS"
        conclusion = (
            "PAIRED_PASS — AIMNet2-assisted与Pure PySCF parent-level完整时间和准确度对照已完成"
        )
        label_b: object = group_b["deprotonation"]
        label_delta: object = float(group_a["deprotonation"]["value_kcal_per_mol"]) - float(
            group_b["deprotonation"]["value_kcal_per_mol"]
        )
        handoff_module = load_module(
            Path(args.handoff_helper).resolve(strict=True), "p01_final_handoff_helper"
        )
        parent_gradient_reduction: object = {
            endpoint: {
                "gradient_rms": handoff_module.gradient_reduction(
                    float(
                        group_b["endpoint_results"][endpoint]["first_parent_observation"][
                            "first_parent_gradient_rms_Eh_Bohr"
                        ]
                    ),
                    float(
                        group_a["endpoint_results"][endpoint]["first_parent_observation"][
                            "first_parent_gradient_rms_Eh_Bohr"
                        ]
                    ),
                ),
                "gradient_max": handoff_module.gradient_reduction(
                    float(
                        group_b["endpoint_results"][endpoint]["first_parent_observation"][
                            "first_parent_gradient_max_Eh_Bohr"
                        ]
                    ),
                    float(
                        group_a["endpoint_results"][endpoint]["first_parent_observation"][
                            "first_parent_gradient_max_Eh_Bohr"
                        ]
                    ),
                ),
            }
            for endpoint in ENDPOINTS
        }
    else:
        group_b = {
            "status": "TIMEOUT",
            "observed_wall_seconds": group_b_elapsed,
            "last_observation": helper.last_geometric_observation(
                helper.read_regular(
                    root / "paired_anchor/group_b_pure_pyscf/optimization/neutral/stderr",
                    maximum=512 << 20,
                )
            ),
        }
        comparison = timeout_lower_bound(group_a_wall, group_b_elapsed)
        outcome = "PARTIAL_PASS"
        conclusion = (
            "PARTIAL_PASS - AIMNet2-assisted parent-level route completed; "
            "Pure PySCF incomplete; speed lower bound available, accuracy comparison incomplete"
        )
        label_b = "unavailable_group_b_timeout"
        label_delta = "unavailable_group_b_timeout"
        parent_gradient_reduction = "unavailable_group_b_timeout"
    old = json.loads(helper.read_regular(Path(args.old_assisted_result).resolve(strict=True)))
    old_label = float(old["deprotonation"]["value_kcal_per_mol"])
    label_a = float(group_a["deprotonation"]["value_kcal_per_mol"])
    terminal = {
        "schema_version": SCHEMA,
        "science_pilot_only": True,
        "production_accepted": False,
        "production_label_inserted": False,
        "candidate": CANDIDATE,
        "protocol": group_a["protocol"],
        "group_a": group_a,
        "group_b": group_b,
        "timing": comparison,
        "label_a_kcal_per_mol": label_a,
        "label_b_kcal_per_mol": label_b,
        "label_a_minus_label_b_kcal_per_mol": label_delta,
        "parent_gradient_reduction": parent_gradient_reduction,
        "old_b3lyp_svp_assisted_label_kcal_per_mol": old_label,
        "parent_minus_old_method_label_kcal_per_mol": label_a - old_label,
        "extension": {
            "status": "not_run",
            "candidate_count": 0,
            "reason": "insufficient remaining authorized resources after paired anchor",
        },
        "single_candidate": True,
        "second_pure_pyscf_candidate": False,
        "batch": False,
        "retry": False,
        "final_outcome": outcome,
        "final_conclusion": conclusion,
    }
    helper.write_json_new(root / "result.json", terminal)
    helper.write_json_new(root / "paired_anchor/comparison/final_paired_result.json", terminal)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    controller = sub.add_parser("assisted-controller")
    for name in (
        "root",
        "aimnet-root",
        "repo",
        "source-commit",
        "mlff-python",
        "gpupyscf-python",
        "weight",
        "gpu-uuid",
        "v006-helper",
    ):
        controller.add_argument(f"--{name}", required=True)
    controller.add_argument("--gpu-index", type=int, required=True)
    controller.add_argument("--threads", type=int, required=True)
    controller.add_argument("--cpu-list", required=True)
    controller.add_argument("--max-memory-mb", type=int, required=True)
    worker = sub.add_parser("parent-worker")
    worker.add_argument("--route", choices=("assisted", "pure_pyscf"), required=True)
    worker.add_argument("--route-limit-seconds", type=float, required=True)
    worker.add_argument("--threads", type=int, required=True)
    worker.add_argument("--cpu-list", required=True)
    worker.add_argument("--max-memory-mb", type=int, required=True)
    worker.add_argument("--candidate", default=CANDIDATE)
    worker.add_argument("--electron-count", type=int, default=ELECTRONS)
    worker.add_argument("--cation-atom-count", type=int, default=ATOM_COUNTS["cation"])
    worker.add_argument("--neutral-atom-count", type=int, default=ATOM_COUNTS["neutral"])
    worker.add_argument("--cation-sha256", default=INPUT_SHA256["cation"])
    worker.add_argument("--neutral-sha256", default=INPUT_SHA256["neutral"])
    worker.add_argument("--record-training-frames", action="store_true")
    worker.add_argument("--training-data-helper")
    worker.add_argument(
        "--handoff-helper",
        default=str(Path(__file__).resolve().with_name("phase9b_aimnet2_parent_handoff.py")),
    )
    worker.add_argument(
        "--gau-loose-contract",
        default=str(
            Path(__file__).resolve().parents[1] / "docs" / "PHASE9B_AIMNET2_GAU_LOOSE_V001.yaml"
        ),
    )
    worker.add_argument("--structure-review-path")
    for name in (
        "root",
        "source-root",
        "pilot-helper",
        "sp-helper",
        "v006-helper",
        "cation-input",
        "neutral-input",
    ):
        worker.add_argument(f"--{name}", required=True)
    final = sub.add_parser("finalize")
    for name in ("root", "v006-helper", "old-assisted-result", "handoff-helper"):
        final.add_argument(f"--{name}", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "assisted-controller":
        return assisted_controller(args)
    if args.command == "parent-worker":
        return parent_worker(args)
    if args.command == "finalize":
        return final_result(args)
    raise BenchmarkError("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
