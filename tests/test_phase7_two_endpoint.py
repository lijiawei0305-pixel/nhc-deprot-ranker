from __future__ import annotations

import importlib
import json
import math
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from nhc_deprot_ranker.constants import GAS_PROTON_KCAL_MOL, HARTREE_TO_KCAL_MOL
from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.quantum import two_endpoint as runner


def _write_xyz(path: Path, atoms: list[tuple[str, float, float, float]]) -> None:
    lines = [str(len(atoms)), "synthetic Phase 7 fixture"]
    lines.extend(f"{element} {x} {y} {z}" for element, x, y, z in atoms)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_request(
    root: Path,
    *,
    execution_authorized: bool = True,
    extra: dict[str, object] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _write_xyz(root / "cation.xyz", [("C", 0.0, 0.0, 0.0), ("H", 0.0, 0.0, 1.0)])
    _write_xyz(root / "neutral.xyz", [("C", 0.0, 0.0, 0.1)])
    payload: dict[str, object] = {
        "schema_version": runner.REQUEST_SCHEMA_VERSION,
        "request_id": "phase7-smoke-001",
        "inchikey": "IJWCXRPLHNQISE-UHFFFAOYSA-N",
        "execution_authorized": execution_authorized,
        "timeout_seconds": 300,
        "runner_source_sha256": runner.current_runner_source_sha256(),
        "protocol": runner.LOCKED_PROTOCOL,
        "endpoints": {
            "cation": {
                "xyz_path": "cation.xyz",
                "xyz_sha256": sha256_file(root / "cation.xyz"),
                "charge": 1,
                "multiplicity": 1,
            },
            "neutral": {
                "xyz_path": "neutral.xyz",
                "xyz_sha256": sha256_file(root / "neutral.xyz"),
                "charge": 0,
                "multiplicity": 1,
            },
        },
    }
    if extra:
        payload.update(extra)
    path = root / "request.json"
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def _runtime_evidence(geometry: runner.XYZGeometry, *, charge: int) -> runner.RuntimeEvidence:
    return runner.RuntimeEvidence(
        compute_threads=runner.COMPUTE_THREADS,
        thread_environment=tuple(sorted(runner.THREAD_ENVIRONMENT.items())),
        pyscf_threads=runner.COMPUTE_THREADS,
        molecule_max_memory_mb=runner.PYSCF_MAX_MEMORY_MB,
        mean_field_max_memory_mb=runner.PYSCF_MAX_MEMORY_MB,
        electron_count=runner._electron_count_for_geometry(  # pyright: ignore[reportPrivateUsage]
            geometry, charge=charge
        ),
    )


def _set_frozen_thread_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in runner.THREAD_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


class _FakePySCFLib:
    def __init__(self) -> None:
        self.threads = runner.COMPUTE_THREADS

    def num_threads(self, value: int | None = None) -> int:
        if value is not None:
            self.threads = value
        return self.threads


def _optimization_d3(natm: int) -> runner.OptimizationD3Evidence:
    return runner.OptimizationD3Evidence(
        tag="d3bj",
        energy_hook_calls=1,
        gradient_hook_calls=1,
        gradient_shape=(natm, 3),
        energy_values_finite=True,
        gradient_values_finite=True,
    )


def _final_d3(energy: float, natm: int) -> runner.FinalD3Evidence:
    dispersion = -0.125
    one_electron = energy - dispersion
    return runner.FinalD3Evidence(
        tag="d3bj",
        energy_hook_calls=1,
        breakdown=runner.FinalEnergyBreakdown(
            nuclear_hartree=0.0,
            one_electron_hartree=one_electron,
            coulomb_hartree=0.0,
            exchange_correlation_hartree=0.0,
            dispersion_hartree=dispersion,
            reconstructed_hartree=energy,
            total_hartree=energy,
            absolute_error_hartree=0.0,
        ),
        audit_calls=1,
        audit_energy_hartree=dispersion,
        audit_gradient_shape=(natm, 3),
        audit_gradient_finite=True,
        audit_absolute_error_hartree=0.0,
        adapter_version=runner.PYSCF_DISPERSION_VERSION,
    )


class FakeBackend:
    def __init__(
        self,
        *,
        fail_standard_final_for: str | None = None,
        fail_standard_opt_for: str | None = None,
        geometry_converged: bool = True,
        nonfinite_final_for: str | None = None,
        timeout_for: str | None = None,
        optimization_error: type[runner.BackendError] | None = None,
        optimization_scf_converged: object = True,
        final_scf_converged: object = True,
    ) -> None:
        self.fail_standard_final_for = fail_standard_final_for
        self.fail_standard_opt_for = fail_standard_opt_for
        self.geometry_converged = geometry_converged
        self.nonfinite_final_for = nonfinite_final_for
        self.timeout_for = timeout_for
        self.optimization_error = optimization_error
        self.optimization_scf_converged = optimization_scf_converged
        self.final_scf_converged = final_scf_converged
        self.calls: list[tuple[str, str, str]] = []

    def optimize(
        self,
        *,
        endpoint: runner.EndpointName,
        geometry: runner.XYZGeometry,
        charge: int,
        multiplicity: int,
        strategy: runner.SCFStrategy,
        deadline_monotonic: float,
    ) -> runner.BackendOptimizationResult:
        del multiplicity, deadline_monotonic
        self.calls.append(("optimize", endpoint, strategy))
        if self.timeout_for == endpoint:
            raise runner.BackendTimeoutError("synthetic timeout")
        if self.optimization_error is not None and strategy == "standard":
            raise self.optimization_error("synthetic SCF-looking non-retryable failure")
        if self.fail_standard_opt_for == endpoint and strategy == "standard":
            raise runner.SCFNotConvergedError("synthetic SCF convergence failure")
        shifted = runner.XYZGeometry(
            tuple(replace(atom, x=atom.x + 0.01) for atom in geometry.atoms)
        )
        return runner.BackendOptimizationResult(
            geometry=shifted,
            geometry_converged=self.geometry_converged,
            scf_converged=cast(bool, self.optimization_scf_converged),
            last_energy_hartree=-100.0 if endpoint == "cation" else -99.0,
            runtime=_runtime_evidence(geometry, charge=charge),
            dispersion=_optimization_d3(len(geometry.atoms)),
        )

    def final_scf(
        self,
        *,
        endpoint: runner.EndpointName,
        geometry: runner.XYZGeometry,
        charge: int,
        multiplicity: int,
        strategy: runner.SCFStrategy,
        deadline_monotonic: float,
    ) -> runner.BackendSCFResult:
        del multiplicity, deadline_monotonic
        self.calls.append(("final_scf", endpoint, strategy))
        if self.timeout_for == endpoint:
            raise runner.BackendTimeoutError("synthetic timeout")
        if self.fail_standard_final_for == endpoint and strategy == "standard":
            return runner.BackendSCFResult(
                converged=False,
                energy_hartree=-1.0,
                runtime=_runtime_evidence(geometry, charge=charge),
                dispersion=_final_d3(-1.0, len(geometry.atoms)),
            )
        energy = -100.125 if endpoint == "cation" else -99.875
        if self.nonfinite_final_for == endpoint:
            energy = math.nan
        return runner.BackendSCFResult(
            converged=cast(bool, self.final_scf_converged),
            energy_hartree=energy,
            runtime=_runtime_evidence(geometry, charge=charge),
            dispersion=_final_d3(energy, len(geometry.atoms)),
        )


def _execute(
    request_path: Path,
    output: Path,
    backend: FakeBackend,
    *,
    attempt_id: str,
) -> runner.TwoEndpointRunResult:
    request = runner.load_two_endpoint_request(request_path)
    return runner._execute_validated_request(  # pyright: ignore[reportPrivateUsage]
        request, output, backend=backend, attempt_id=attempt_id
    )


def _resign_completed_output(output: Path) -> None:
    success_path = output / "success.json"
    success = cast(dict[str, object], json.loads(success_path.read_text(encoding="utf-8")))
    attempt_id = cast(str, success["attempt_id"])
    attempt = output / "attempts" / attempt_id
    result_path = attempt / "result.json"
    attempt_marker_path = attempt / "_ATTEMPT_SUCCESS"
    attempt_marker = cast(
        dict[str, object], json.loads(attempt_marker_path.read_text(encoding="utf-8"))
    )
    attempt_marker["result_sha256"] = sha256_file(result_path)
    attempt_marker_path.write_text(
        json.dumps(attempt_marker, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    success["output_sha256"] = {
        f"attempts/{attempt_id}/{path.name}": sha256_file(path)
        for path in sorted(attempt.iterdir())
        if path.is_file()
    }
    success_path.write_text(json.dumps(success, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (output / "_SUCCESS").write_text(
        json.dumps(
            {
                "schema_version": runner.SUCCESS_SCHEMA_VERSION,
                "success_sha256": sha256_file(success_path),
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_public_gate_rejects_before_request_read_or_lazy_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported: list[str] = []

    def forbidden_import(name: str, package: str | None = None) -> object:
        del package
        imported.append(name)
        raise AssertionError("compute dependency import must not occur")

    monkeypatch.setattr(importlib, "import_module", forbidden_import)
    assert runner.EXECUTION_AUTHORIZED is False
    with pytest.raises(runner.ExecutionNotAuthorizedError) as exc_info:
        runner.run_two_endpoint(tmp_path / "missing.json", tmp_path / "out")
    assert exc_info.value.exit_code != 0
    assert imported == []
    assert not (tmp_path / "out").exists()


def test_pyscf_adapter_construction_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    imported: list[str] = []
    monkeypatch.setattr(importlib, "import_module", lambda name: imported.append(name))
    runner.PySCFBackend(object())
    assert imported == []


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (True, True),
        (1, True),
        ("d3bj", True),
        ("d4", False),
        (False, False),
        (None, False),
    ],
)
def test_dispersion_activity_check_supports_pyscf_return_variants(
    state: object, expected: bool
) -> None:
    class MeanField:
        def do_disp(self) -> object:
            return state

    assert runner.PySCFBackend._d3bj_is_active(MeanField()) is expected


def test_standard_and_soscf_energy_owners_require_exact_active_d3bj() -> None:
    class Owner:
        def __init__(self, *, disp: str, active: bool) -> None:
            self.disp = disp
            self.active = active

        def do_disp(self) -> bool:
            return self.active

    standard = Owner(disp="d3bj", active=True)
    assert (
        runner.PySCFBackend._energy_owner(standard, strategy="standard", label="standard owner")
        is standard
    )

    inner = Owner(disp="d3bj", active=True)
    outer = Owner(disp="d3bj", active=True)
    outer._scf = inner  # type: ignore[attr-defined]
    assert runner.PySCFBackend._energy_owner(outer, strategy="soscf", label="SOSCF owner") is inner

    for strategy, drifted, message in (
        ("standard", Owner(disp="d4", active=True), "dropped"),
        ("standard", Owner(disp="d3bj", active=False), "active D3"),
        ("soscf", Owner(disp="d4", active=True), "dropped"),
        ("soscf", Owner(disp="d3bj", active=False), "active D3"),
    ):
        if strategy == "soscf":
            drifted._scf = inner  # type: ignore[attr-defined]
        with pytest.raises(runner.DispersionUnavailableError, match=message):
            runner.PySCFBackend._energy_owner(
                drifted,
                strategy=cast(runner.SCFStrategy, strategy),
                label="drifted owner",
            )

    for drifted_inner, message in (
        (Owner(disp="d4", active=True), "inner SCF dropped"),
        (Owner(disp="d3bj", active=False), "inner SCF did not retain active"),
    ):
        drifted_outer = Owner(disp="d3bj", active=True)
        drifted_outer._scf = drifted_inner  # type: ignore[attr-defined]
        with pytest.raises(runner.DispersionUnavailableError, match=message):
            runner.PySCFBackend._energy_owner(
                drifted_outer,
                strategy="soscf",
                label="synthetic Newton",
            )


@pytest.mark.parametrize(
    ("geometry_converged", "resource_drift"),
    [
        (True, None),
        (False, None),
        (True, "threads"),
        (True, "environment"),
        (True, "memory"),
        (True, "electrons"),
        (True, "charge"),
        (True, "spin"),
        (True, "convergence"),
        (True, "d3_after"),
    ],
)
def test_pyscf_adapter_uses_geometric_kernel_and_explicit_convergence_with_fake_modules(
    monkeypatch: pytest.MonkeyPatch,
    geometry_converged: bool,
    resource_drift: str | None,
) -> None:
    _set_frozen_thread_environment(monkeypatch)
    geometry = runner.XYZGeometry(
        (
            runner.XYZAtom("C", 0.0, 0.0, 0.0),
            runner.XYZAtom("H", 0.0, 0.0, 1.0),
        )
    )
    kernel_calls: list[dict[str, object]] = []
    fake_lib = _FakePySCFLib()

    class FakeMolecule:
        def __init__(
            self,
            *,
            symbols: tuple[str, ...] = ("C", "H"),
            max_memory: int = runner.PYSCF_MAX_MEMORY_MB,
            charge: int = 1,
            spin: int = 0,
            electron_count: int = 6,
        ) -> None:
            self.symbols = symbols
            self.natm = len(symbols)
            self.max_memory = max_memory
            self.nelectron = electron_count
            self.charge = charge
            self.spin = spin

        def atom_coords(self, *, unit: str) -> list[list[float]]:
            assert unit == "Angstrom"
            return [[0.01, 0.0, float(index)] for index in range(self.natm)]

        def atom_symbol(self, index: int) -> str:
            return self.symbols[index]

    class FakeGTO:
        @staticmethod
        def M(**kwargs: object) -> FakeMolecule:
            assert kwargs["basis"] == "def2-svp"
            assert kwargs["charge"] == 1
            assert kwargs["spin"] == 0
            assert kwargs["max_memory"] == runner.PYSCF_MAX_MEMORY_MB
            assert kwargs["unit"] == "Angstrom"
            atom_spec = cast(list[tuple[str, tuple[float, float, float]]], kwargs["atom"])
            return FakeMolecule(
                symbols=tuple(symbol for symbol, _ in atom_spec),
                charge=cast(int, kwargs["charge"]),
                spin=cast(int, kwargs["spin"]),
            )

    class FakeGrids:
        level = 0

    class FakeSCFScanner:
        def __init__(self, molecule: FakeMolecule) -> None:
            self.mol = molecule
            self.max_memory = molecule.max_memory
            self.disp = "d3bj"
            self.converged = True
            self.e_tot = -10.0

        def do_disp(self) -> bool:
            return True

        def get_dispersion(self) -> float:
            return -0.125

    class FakeGradientScanner:
        def __init__(self, molecule: FakeMolecule) -> None:
            self.base = FakeSCFScanner(molecule)
            self.converged = True
            self.e_tot = -10.0

        def get_dispersion(self) -> list[list[float]]:
            return [[0.0, 0.0, 0.0] for _ in range(self.base.mol.natm)]

    class FakeGradient:
        def __init__(self, molecule: FakeMolecule) -> None:
            self.molecule = molecule

        def as_scanner(self) -> FakeGradientScanner:
            return FakeGradientScanner(self.molecule)

    class FakeMeanField:
        def __init__(self, molecule: FakeMolecule) -> None:
            self.mol = molecule
            self.max_memory = molecule.max_memory
            self.xc = ""
            self.grids = FakeGrids()
            self.conv_tol = 0.0
            self.max_cycle = 0
            self.disp: str | None = None
            self.scf_summary: dict[str, float] = {}

        def do_disp(self) -> bool:
            return True

        def nuc_grad_method(self) -> FakeGradient:
            return FakeGradient(self.mol)

        def newton(self) -> FakeMeanField:
            return self

    mean_fields: list[FakeMeanField] = []

    class FakeDFT:
        @staticmethod
        def RKS(molecule: FakeMolecule) -> FakeMeanField:
            mean_field = FakeMeanField(molecule)
            mean_fields.append(mean_field)
            return mean_field

    class FakeGeometricSolver:
        @staticmethod
        def kernel(method: FakeGradientScanner, **kwargs: object) -> tuple[bool, FakeMolecule]:
            assert isinstance(method, FakeGradientScanner)
            method.base.get_dispersion()
            method.get_dispersion()
            callback = kwargs["callback"]
            assert callable(callback)
            kernel_calls.append({key: value for key, value in kwargs.items() if key != "callback"})
            if resource_drift == "convergence":
                method.converged = cast(bool, None)
            callback({"g_scanner": method})
            optimized_molecule = FakeMolecule()
            if resource_drift == "threads":
                fake_lib.threads = 2
            elif resource_drift == "environment":
                monkeypatch.setenv("OMP_NUM_THREADS", "8")
            elif resource_drift == "memory":
                method.base.max_memory = 6_000
            elif resource_drift == "electrons":
                optimized_molecule.nelectron = 5
            elif resource_drift == "charge":
                method.base.mol.charge = 0
            elif resource_drift == "spin":
                method.base.mol.spin = 2
            elif resource_drift == "d3_after":
                method.base.disp = "d4"
            return geometry_converged, optimized_molecule

    class FakeD3:
        pass

    backend = runner.PySCFBackend(object())
    monkeypatch.setattr(
        backend,
        "_load_modules",
        lambda: runner._PySCFModules(  # pyright: ignore[reportPrivateUsage]
            gto=FakeGTO(),
            dft=FakeDFT(),
            geometric_solver=FakeGeometricSolver(),
            lib=fake_lib,
            dftd3=FakeD3(),
            thread_environment=tuple(sorted(runner.THREAD_ENVIRONMENT.items())),
            pyscf_threads=runner.COMPUTE_THREADS,
            adapter_version=runner.PYSCF_DISPERSION_VERSION,
        ),
    )
    if resource_drift is not None:
        expected_error, expected_message = {
            "threads": (runner.ResourceConfigurationError, "four OpenMP threads"),
            "environment": (runner.ResourceConfigurationError, "OMP_NUM_THREADS"),
            "memory": (runner.ResourceConfigurationError, "max_memory"),
            "electrons": (runner.ResourceConfigurationError, "electron count"),
            "charge": (runner.ResourceConfigurationError, "charge"),
            "spin": (runner.ResourceConfigurationError, "spin"),
            "convergence": (runner.SCFConvergenceError, "literal boolean"),
            "d3_after": (runner.DispersionUnavailableError, "dropped"),
        }[resource_drift]
        with pytest.raises(expected_error, match=expected_message):
            backend.optimize(
                endpoint="cation",
                geometry=geometry,
                charge=1,
                multiplicity=1,
                strategy="standard",
                deadline_monotonic=math.inf,
            )
    elif geometry_converged:
        result = backend.optimize(
            endpoint="cation",
            geometry=geometry,
            charge=1,
            multiplicity=1,
            strategy="standard",
            deadline_monotonic=math.inf,
        )
        assert result.geometry_converged is True
        assert result.dispersion.energy_hook_calls == 1
        assert result.dispersion.gradient_hook_calls == 1
    else:
        with pytest.raises(runner.GeometryConvergenceError, match="explicitly converge"):
            backend.optimize(
                endpoint="cation",
                geometry=geometry,
                charge=1,
                multiplicity=1,
                strategy="standard",
                deadline_monotonic=math.inf,
            )
    assert kernel_calls == [{"assert_convergence": True, "maxsteps": 100}]
    assert len(mean_fields) == 1
    assert mean_fields[0].disp == "d3bj"
    assert mean_fields[0].xc == "B3LYP"
    assert mean_fields[0].grids.level == 3
    assert mean_fields[0].conv_tol == 1.0e-9
    assert mean_fields[0].max_cycle == 100


@pytest.mark.parametrize(
    "resource_drift",
    [
        None,
        "threads",
        "environment",
        "memory",
        "electrons",
        "charge",
        "spin",
        "convergence",
        "d3_after",
        "audit_threads",
        "audit_environment",
        "audit_memory",
        "audit_electrons",
        "audit_charge",
        "audit_spin",
        "audit_d3",
    ],
)
def test_final_scf_records_breakdown_and_one_zero_scf_d3_audit_with_fake_modules(
    monkeypatch: pytest.MonkeyPatch, resource_drift: str | None
) -> None:
    _set_frozen_thread_environment(monkeypatch)
    geometry = runner.XYZGeometry(
        (
            runner.XYZAtom("C", 0.0, 0.0, 0.0),
            runner.XYZAtom("H", 0.0, 0.0, 1.0),
        )
    )
    electronic_kernel_calls = 0
    audit_calls = 0
    fake_lib = _FakePySCFLib()

    class FakeMolecule:
        natm = 2
        nelectron = 6
        charge = 1
        spin = 0

        def __init__(self) -> None:
            self.max_memory = runner.PYSCF_MAX_MEMORY_MB

        def atom_symbol(self, index: int) -> str:
            return ("C", "H")[index]

    class FakeGTO:
        @staticmethod
        def M(**kwargs: object) -> FakeMolecule:
            assert kwargs["max_memory"] == runner.PYSCF_MAX_MEMORY_MB
            assert kwargs["basis"] == "def2-svp"
            assert kwargs["charge"] == 1
            assert kwargs["spin"] == 0
            return FakeMolecule()

    class FakeGrids:
        level = 0

    class FakeMeanField:
        def __init__(self, molecule: FakeMolecule) -> None:
            self.mol = molecule
            self.max_memory = molecule.max_memory
            self.xc = ""
            self.grids = FakeGrids()
            self.conv_tol = 0.0
            self.max_cycle = 0
            self.disp: str | None = None
            self.converged = False
            self.scf_summary: dict[str, float] = {}

        def do_disp(self) -> bool:
            return True

        def get_dispersion(self) -> float:
            return -0.125

        def kernel(self) -> float:
            nonlocal electronic_kernel_calls
            electronic_kernel_calls += 1
            dispersion = float(self.get_dispersion())
            self.scf_summary = {
                "nuc": 10.0,
                "e1": -120.0,
                "coul": 20.0,
                "exc": -10.0,
                "dispersion": dispersion,
            }
            self.converged = True
            if resource_drift == "threads":
                fake_lib.threads = 2
            elif resource_drift == "environment":
                monkeypatch.setenv("OMP_NUM_THREADS", "8")
            elif resource_drift == "memory":
                self.max_memory = 6_000
            elif resource_drift == "electrons":
                self.mol.nelectron = 5
            elif resource_drift == "charge":
                self.mol.charge = 0
            elif resource_drift == "spin":
                self.mol.spin = 2
            elif resource_drift == "convergence":
                self.converged = cast(bool, None)
            elif resource_drift == "d3_after":
                self.disp = "d4"
            return -100.125

        def newton(self) -> FakeMeanField:
            return self

    mean_fields: list[FakeMeanField] = []

    class FakeDFT:
        @staticmethod
        def RKS(molecule: FakeMolecule) -> FakeMeanField:
            mean_field = FakeMeanField(molecule)
            mean_fields.append(mean_field)
            return mean_field

    class FakeAdapter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            assert kwargs == {"xc": "B3LYP", "version": "d3bj", "atm": False}

        def get_dispersion(self, *, grad: bool) -> dict[str, object]:
            nonlocal audit_calls
            audit_calls += 1
            assert grad is True
            mean_field = mean_fields[-1]
            if resource_drift == "audit_threads":
                fake_lib.threads = 2
            elif resource_drift == "audit_environment":
                monkeypatch.setenv("OMP_NUM_THREADS", "8")
            elif resource_drift == "audit_memory":
                mean_field.max_memory = 6_000
            elif resource_drift == "audit_electrons":
                mean_field.mol.nelectron = 5
            elif resource_drift == "audit_charge":
                mean_field.mol.charge = 0
            elif resource_drift == "audit_spin":
                mean_field.mol.spin = 2
            elif resource_drift == "audit_d3":
                mean_field.disp = "d4"
            return {
                "energy": -0.125,
                "gradient": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            }

    class FakeD3:
        DFTD3Dispersion = FakeAdapter

    backend = runner.PySCFBackend(object())
    monkeypatch.setattr(
        backend,
        "_load_modules",
        lambda: runner._PySCFModules(  # pyright: ignore[reportPrivateUsage]
            gto=FakeGTO(),
            dft=FakeDFT(),
            geometric_solver=object(),
            lib=fake_lib,
            dftd3=FakeD3(),
            thread_environment=tuple(sorted(runner.THREAD_ENVIRONMENT.items())),
            pyscf_threads=runner.COMPUTE_THREADS,
            adapter_version=runner.PYSCF_DISPERSION_VERSION,
        ),
    )
    if resource_drift is not None:
        expected_error, expected_message = {
            "threads": (runner.ResourceConfigurationError, "four OpenMP threads"),
            "environment": (runner.ResourceConfigurationError, "OMP_NUM_THREADS"),
            "memory": (runner.ResourceConfigurationError, "max_memory"),
            "electrons": (runner.ResourceConfigurationError, "electron count"),
            "charge": (runner.ResourceConfigurationError, "charge"),
            "spin": (runner.ResourceConfigurationError, "spin"),
            "convergence": (runner.SCFConvergenceError, "literal boolean"),
            "d3_after": (runner.DispersionUnavailableError, "dropped"),
            "audit_threads": (runner.ResourceConfigurationError, "four OpenMP threads"),
            "audit_environment": (runner.ResourceConfigurationError, "OMP_NUM_THREADS"),
            "audit_memory": (runner.ResourceConfigurationError, "max_memory"),
            "audit_electrons": (runner.ResourceConfigurationError, "electron count"),
            "audit_charge": (runner.ResourceConfigurationError, "charge"),
            "audit_spin": (runner.ResourceConfigurationError, "spin"),
            "audit_d3": (runner.DispersionUnavailableError, "dropped"),
        }[resource_drift]
        with pytest.raises(expected_error, match=expected_message):
            backend.final_scf(
                endpoint="cation",
                geometry=geometry,
                charge=1,
                multiplicity=1,
                strategy="standard",
                deadline_monotonic=math.inf,
            )
        assert electronic_kernel_calls == 1
        assert audit_calls == int(resource_drift.startswith("audit_"))
        return
    result = backend.final_scf(
        endpoint="cation",
        geometry=geometry,
        charge=1,
        multiplicity=1,
        strategy="standard",
        deadline_monotonic=math.inf,
    )
    assert electronic_kernel_calls == 1
    assert audit_calls == 1
    assert result.dispersion.energy_hook_calls == 1
    assert result.dispersion.audit_calls == 1
    assert result.dispersion.breakdown.reconstructed_hartree == result.energy_hartree
    assert mean_fields[0].xc == "B3LYP"
    assert mean_fields[0].grids.level == 3
    assert mean_fields[0].conv_tol == 1.0e-9
    assert mean_fields[0].max_cycle == 100
    assert mean_fields[0].disp == "d3bj"


@pytest.mark.parametrize(
    "owner_drift",
    [
        None,
        "optimization_outer_d3",
        "optimization_inner_d3",
        "optimization_outer_memory",
        "optimization_inner_memory",
        "final_outer_d3",
        "final_inner_d3",
        "final_outer_memory",
        "final_inner_memory",
        "audit_outer_d3",
        "audit_inner_d3",
        "audit_outer_memory",
        "audit_inner_memory",
    ],
)
def test_soscf_observes_inner_scf_energy_owner_for_optimization_and_final(
    monkeypatch: pytest.MonkeyPatch, owner_drift: str | None
) -> None:
    _set_frozen_thread_environment(monkeypatch)
    geometry = runner.XYZGeometry(
        (
            runner.XYZAtom("C", 0.0, 0.0, 0.0),
            runner.XYZAtom("H", 0.0, 0.0, 1.0),
        )
    )
    inner_energy_calls = 0
    newton_fields: list[FakeNewton] = []
    inner_fields: list[FakeInner] = []

    class FakeMolecule:
        natm = 2
        nelectron = 6
        charge = 1
        spin = 0

        def __init__(self) -> None:
            self.max_memory = runner.PYSCF_MAX_MEMORY_MB

        def atom_symbol(self, index: int) -> str:
            return ("C", "H")[index]

        def atom_coords(self, *, unit: str) -> list[list[float]]:
            assert unit == "Angstrom"
            return [[0.01, 0.0, 0.0], [0.0, 0.0, 1.01]]

    class FakeInner:
        def __init__(self, molecule: FakeMolecule) -> None:
            self.mol = molecule
            self.max_memory = molecule.max_memory
            self.xc = ""
            self.grids = type("FakeGrids", (), {"level": 0})()
            self.conv_tol = 0.0
            self.max_cycle = 0
            self.disp: str | None = None
            self.scf_summary: dict[str, float] = {}

        def do_disp(self) -> bool:
            return True

        def get_dispersion(self) -> float:
            nonlocal inner_energy_calls
            inner_energy_calls += 1
            return -0.125

        def newton(self) -> FakeNewton:
            newton = FakeNewton(self)
            newton_fields.append(newton)
            return newton

    class FakeInnerScanner:
        def __init__(self, inner: FakeInner) -> None:
            self.mol = inner.mol
            self.max_memory = inner.max_memory
            self.disp = inner.disp

        def do_disp(self) -> bool:
            return True

        def get_dispersion(self) -> float:
            nonlocal inner_energy_calls
            inner_energy_calls += 1
            return -0.125

    class FakeNewtonScanner:
        def __init__(self, inner: FakeInner) -> None:
            self._scf = FakeInnerScanner(inner)
            self.mol = inner.mol
            self.max_memory = inner.max_memory
            self.disp = inner.disp
            self.converged = True
            self.e_tot = -10.0

        def do_disp(self) -> bool:
            return True

    class FakeGradientScanner:
        def __init__(self, inner: FakeInner) -> None:
            self.base = FakeNewtonScanner(inner)
            self.converged = True
            self.e_tot = -10.0

        def get_dispersion(self) -> list[list[float]]:
            return [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]

    class FakeGradient:
        def __init__(self, inner: FakeInner) -> None:
            self.inner = inner

        def as_scanner(self) -> FakeGradientScanner:
            return FakeGradientScanner(self.inner)

    class FakeNewton:
        def __init__(self, inner: FakeInner) -> None:
            self._scf = inner
            self.mol = inner.mol
            self.max_memory = inner.max_memory
            self.max_cycle = 0
            self.disp = inner.disp
            self.converged = False

        def do_disp(self) -> bool:
            return True

        def nuc_grad_method(self) -> FakeGradient:
            return FakeGradient(self._scf)

        def kernel(self) -> float:
            dispersion = float(self._scf.get_dispersion())
            self._scf.scf_summary = {
                "nuc": 10.0,
                "e1": -120.0,
                "coul": 20.0,
                "exc": -10.0,
                "dispersion": dispersion,
            }
            self.converged = True
            if owner_drift == "final_outer_d3":
                self.disp = "d4"
            elif owner_drift == "final_inner_d3":
                self._scf.disp = "d4"
            elif owner_drift == "final_outer_memory":
                self.max_memory = 6_000
            elif owner_drift == "final_inner_memory":
                self._scf.max_memory = 6_000
            return -100.125

    class FakeGTO:
        @staticmethod
        def M(**kwargs: object) -> FakeMolecule:
            assert kwargs["max_memory"] == runner.PYSCF_MAX_MEMORY_MB
            assert kwargs["basis"] == "def2-svp"
            assert kwargs["charge"] == 1
            assert kwargs["spin"] == 0
            assert kwargs["unit"] == "Angstrom"
            return FakeMolecule()

    class FakeDFT:
        @staticmethod
        def RKS(molecule: FakeMolecule) -> FakeInner:
            inner = FakeInner(molecule)
            inner_fields.append(inner)
            return inner

    class FakeGeometricSolver:
        @staticmethod
        def kernel(scanner: FakeGradientScanner, **kwargs: object) -> tuple[bool, FakeMolecule]:
            scanner.base._scf.get_dispersion()
            scanner.get_dispersion()
            callback = kwargs["callback"]
            assert callable(callback)
            callback({"g_scanner": scanner})
            if owner_drift == "optimization_outer_d3":
                scanner.base.disp = "d4"
            elif owner_drift == "optimization_inner_d3":
                scanner.base._scf.disp = "d4"
            elif owner_drift == "optimization_outer_memory":
                scanner.base.max_memory = 6_000
            elif owner_drift == "optimization_inner_memory":
                scanner.base._scf.max_memory = 6_000
            return True, FakeMolecule()

    class FakeAdapter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def get_dispersion(self, *, grad: bool) -> dict[str, object]:
            assert grad is True
            final_outer = newton_fields[-1]
            if owner_drift == "audit_outer_d3":
                final_outer.disp = "d4"
            elif owner_drift == "audit_inner_d3":
                final_outer._scf.disp = "d4"
            elif owner_drift == "audit_outer_memory":
                final_outer.max_memory = 6_000
            elif owner_drift == "audit_inner_memory":
                final_outer._scf.max_memory = 6_000
            return {
                "energy": -0.125,
                "gradient": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            }

    class FakeD3:
        DFTD3Dispersion = FakeAdapter

    modules = runner._PySCFModules(  # pyright: ignore[reportPrivateUsage]
        gto=FakeGTO(),
        dft=FakeDFT(),
        geometric_solver=FakeGeometricSolver(),
        lib=_FakePySCFLib(),
        dftd3=FakeD3(),
        thread_environment=tuple(sorted(runner.THREAD_ENVIRONMENT.items())),
        pyscf_threads=runner.COMPUTE_THREADS,
        adapter_version=runner.PYSCF_DISPERSION_VERSION,
    )
    backend = runner.PySCFBackend(object())
    monkeypatch.setattr(backend, "_load_modules", lambda: modules)
    if owner_drift is not None and owner_drift.startswith("optimization_"):
        expected_error = (
            runner.DispersionUnavailableError
            if owner_drift.endswith("_d3")
            else runner.ResourceConfigurationError
        )
        expected_message = "dropped" if owner_drift.endswith("_d3") else "max_memory"
        with pytest.raises(expected_error, match=expected_message):
            backend.optimize(
                endpoint="cation",
                geometry=geometry,
                charge=1,
                multiplicity=1,
                strategy="soscf",
                deadline_monotonic=math.inf,
            )
        return
    optimization = backend.optimize(
        endpoint="cation",
        geometry=geometry,
        charge=1,
        multiplicity=1,
        strategy="soscf",
        deadline_monotonic=math.inf,
    )
    if owner_drift is not None:
        expected_error = (
            runner.DispersionUnavailableError
            if owner_drift.endswith("_d3")
            else runner.ResourceConfigurationError
        )
        expected_message = "dropped" if owner_drift.endswith("_d3") else "max_memory"
        with pytest.raises(expected_error, match=expected_message):
            backend.final_scf(
                endpoint="cation",
                geometry=geometry,
                charge=1,
                multiplicity=1,
                strategy="soscf",
                deadline_monotonic=math.inf,
            )
        return
    final = backend.final_scf(
        endpoint="cation",
        geometry=geometry,
        charge=1,
        multiplicity=1,
        strategy="soscf",
        deadline_monotonic=math.inf,
    )
    assert optimization.dispersion.energy_hook_calls == 1
    assert optimization.dispersion.gradient_hook_calls == 1
    assert final.dispersion.energy_hook_calls == 1
    assert final.dispersion.breakdown.dispersion_hartree == -0.125
    assert inner_energy_calls == 2
    assert len(inner_fields) == len(newton_fields) == 2
    assert all(inner.xc == "B3LYP" for inner in inner_fields)
    assert all(inner.grids.level == 3 for inner in inner_fields)
    assert all(inner.conv_tol == 1.0e-9 for inner in inner_fields)
    assert all(inner.max_cycle == 200 for inner in inner_fields)
    assert all(inner.disp == "d3bj" for inner in inner_fields)
    assert all(outer.max_cycle == 200 for outer in newton_fields)
    assert all(outer.disp == "d3bj" for outer in newton_fields)


def test_frozen_thread_configuration_is_exact_and_fake_pyscf_threads_are_verified() -> None:
    environment = dict(runner.THREAD_ENVIRONMENT)
    assert runner._validate_thread_environment(  # pyright: ignore[reportPrivateUsage]
        environment
    ) == tuple(sorted(environment.items()))
    environment["OMP_NUM_THREADS"] = "8"
    with pytest.raises(runner.ResourceConfigurationError, match="OMP_NUM_THREADS"):
        runner._validate_thread_environment(environment)  # pyright: ignore[reportPrivateUsage]

    class FakeLib:
        def __init__(self) -> None:
            self.threads = 1

        def num_threads(self, value: int | None = None) -> int:
            if value is not None:
                self.threads = value
            return self.threads

    assert (
        runner._configure_pyscf_threads(  # pyright: ignore[reportPrivateUsage]
            FakeLib()
        )
        == runner.COMPUTE_THREADS
    )


def test_exact_120_electron_helper_is_chemistry_free_and_fail_closed() -> None:
    neutral_geometry = runner.XYZGeometry(
        tuple(runner.XYZAtom("C", float(index), 0.0, 0.0) for index in range(20))
    )
    cation_geometry = runner.XYZGeometry(
        (*neutral_geometry.atoms, runner.XYZAtom("H", 0.0, 1.0, 0.0))
    )
    cation = runner.EndpointRequest(
        name="cation",
        xyz_relative_path="cation.xyz",
        xyz_path=Path("cation.xyz"),
        xyz_sha256="0" * 64,
        charge=1,
        multiplicity=1,
        electron_count=120,
        geometry=cation_geometry,
    )
    neutral = runner.EndpointRequest(
        name="neutral",
        xyz_relative_path="neutral.xyz",
        xyz_path=Path("neutral.xyz"),
        xyz_sha256="1" * 64,
        charge=0,
        multiplicity=1,
        electron_count=120,
        geometry=neutral_geometry,
    )
    assert (
        runner._validate_frozen_120_electron_pair(  # pyright: ignore[reportPrivateUsage]
            cation, neutral
        )
        == 120
    )
    with pytest.raises(runner.RequestValidationError, match="stored endpoint electron"):
        runner._validate_frozen_120_electron_pair(  # pyright: ignore[reportPrivateUsage]
            cation, replace(neutral, electron_count=118)
        )


def test_request_validates_locked_protocol_xyz_paths_and_hashes(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    assert request.protocol_sha256 == runner.LOCKED_PROTOCOL_SHA256
    assert request.runner_source_sha256 == runner.current_runner_source_sha256()
    assert request.cation.charge == 1
    assert request.neutral.charge == 0
    assert request.cation.electron_count == request.neutral.electron_count == 6
    assert len(request.cation.geometry.atoms) == 2
    assert len(request.neutral.geometry.atoms) == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"protocol": {**runner.LOCKED_PROTOCOL, "grid_level": 4}}, "unique locked"),
        ({"runner_source_sha256": "0" * 64}, "source SHA256"),
        ({"inchikey": "not-a-key"}, "canonical"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"forbidden_mode": "hessian"}, "fields mismatch"),
    ],
)
def test_request_rejects_protocol_source_identity_and_unknown_fields(
    tmp_path: Path, mutation: dict[str, object], message: str
) -> None:
    request_path = _write_request(tmp_path / "request", extra=mutation)
    with pytest.raises(runner.RequestValidationError, match=message):
        runner.load_two_endpoint_request(request_path)


def test_request_rejects_xyz_hash_drift_and_nonfinite_coordinate(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "hash-drift")
    (request_path.parent / "cation.xyz").write_text("1\nchanged\nC 0 0 0\n", encoding="utf-8")
    with pytest.raises(runner.RequestValidationError, match="SHA256 mismatch"):
        runner.load_two_endpoint_request(request_path)

    request_path = _write_request(tmp_path / "nonfinite")
    xyz = request_path.parent / "neutral.xyz"
    xyz.write_text("1\nnonfinite\nC nan 0 0\n", encoding="utf-8")
    payload = cast(dict[str, object], json.loads(request_path.read_text(encoding="utf-8")))
    endpoints = cast(dict[str, dict[str, object]], payload["endpoints"])
    endpoints["neutral"]["xyz_sha256"] = sha256_file(xyz)
    request_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(runner.RequestValidationError, match="non-finite"):
        runner.load_two_endpoint_request(request_path)


def test_request_rejects_traversal_and_symlink(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "traversal")
    payload = cast(dict[str, object], json.loads(request_path.read_text(encoding="utf-8")))
    endpoints = cast(dict[str, dict[str, object]], payload["endpoints"])
    endpoints["cation"]["xyz_path"] = "../outside.xyz"
    request_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(runner.RequestValidationError, match="unsafe path"):
        runner.load_two_endpoint_request(request_path)

    request_path = _write_request(tmp_path / "symlink")
    real = request_path.parent / "cation.xyz"
    link = request_path.parent / "linked.xyz"
    link.symlink_to(real.name)
    payload = cast(dict[str, object], json.loads(request_path.read_text(encoding="utf-8")))
    endpoints = cast(dict[str, dict[str, object]], payload["endpoints"])
    endpoints["cation"]["xyz_path"] = link.name
    request_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(runner.RequestValidationError, match="symlink"):
        runner.load_two_endpoint_request(request_path)


def test_fake_backend_success_writes_atomic_same_attempt_result_and_locked_formula(
    tmp_path: Path,
) -> None:
    request_path = _write_request(tmp_path / "request")
    output = tmp_path / "result"
    backend = FakeBackend()
    result = _execute(request_path, output, backend, attempt_id="attempt-test-success")

    expected_difference = (-99.875 - -100.125) * HARTREE_TO_KCAL_MOL
    assert result.electronic_difference_kcal == pytest.approx(expected_difference)
    assert result.dft_deprot_electronic_kcal == pytest.approx(
        expected_difference + GAS_PROTON_KCAL_MOL
    )
    assert result.exit_code == 0
    assert result.resumed is False
    assert (output / "_SUCCESS").is_file()
    assert (output / "success.json").is_file()
    assert json.loads((output / "success.json").read_text(encoding="utf-8"))["supervision"] is None
    attempt = output / "attempts" / result.attempt_id
    assert (attempt / "_ATTEMPT_SUCCESS").is_file()
    assert not any(path.name.startswith(".tmp-") for path in output.rglob("*"))

    payload = json.loads((attempt / "result.json").read_text(encoding="utf-8"))
    assert payload["attempt_id"] == result.attempt_id
    assert payload["hessian_computed"] is False
    assert payload["frequency_status"] == "not_computed"
    assert payload["n_imaginary"] is None
    assert payload["extra_single_points_computed"] is False
    assert payload["radical_computed"] is False
    assert payload["molden_written"] is False
    assert payload["label_quality"] == "electronic_energy_only"
    assert backend.calls == [
        ("optimize", "cation", "standard"),
        ("final_scf", "cation", "standard"),
        ("optimize", "neutral", "standard"),
        ("final_scf", "neutral", "standard"),
    ]


def test_standard_final_scf_gets_exactly_one_recorded_soscf_retry(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "request")
    output = tmp_path / "result"
    backend = FakeBackend(fail_standard_final_for="neutral")
    result = _execute(request_path, output, backend, attempt_id="attempt-test-soscf")
    assert backend.calls[-2:] == [
        ("final_scf", "neutral", "standard"),
        ("final_scf", "neutral", "soscf"),
    ]
    payload = json.loads((output / result.result_relative_path).read_text(encoding="utf-8"))
    attempts = payload["endpoints"]["neutral"]["final_scf"]["attempts"]
    assert payload["endpoints"]["neutral"]["optimization"]["selected_strategy"] == "standard"
    assert payload["endpoints"]["neutral"]["final_scf"]["selected_strategy"] == "soscf"
    assert attempts == [
        {
            "converged": False,
            "failure_kind": "scf_not_converged",
            "strategy": "standard",
        },
        {"converged": True, "strategy": "soscf"},
    ]


def test_standard_optimization_scf_failure_retries_same_protocol_once(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "request")
    output = tmp_path / "result"
    backend = FakeBackend(fail_standard_opt_for="cation")
    result = _execute(request_path, output, backend, attempt_id="attempt-test-opt-soscf")
    assert backend.calls[:3] == [
        ("optimize", "cation", "standard"),
        ("optimize", "cation", "soscf"),
        ("final_scf", "cation", "soscf"),
    ]
    payload = json.loads((output / result.result_relative_path).read_text(encoding="utf-8"))
    assert payload["endpoints"]["cation"]["optimization"]["selected_strategy"] == "soscf"


@pytest.mark.parametrize(
    "error_type",
    [
        runner.SCFConvergenceError,
        runner.DispersionUnavailableError,
        runner.DispersionEvaluationError,
        runner.ResourceConfigurationError,
        runner.ResourceLimitError,
        runner.GeometryConvergenceError,
        runner.BackendTimeoutError,
        runner.BackendUnknownError,
    ],
)
def test_only_typed_not_converged_failure_can_consume_soscf_retry(
    tmp_path: Path, error_type: type[runner.BackendError]
) -> None:
    request_path = _write_request(tmp_path / "request")
    backend = FakeBackend(optimization_error=error_type)
    with pytest.raises(runner.TwoEndpointRunError):
        _execute(
            request_path,
            tmp_path / "result",
            backend,
            attempt_id="attempt-non-retryable",
        )
    assert backend.calls == [("optimize", "cation", "standard")]


@pytest.mark.parametrize("invalid_state", [None, 0, 1, "false"])
@pytest.mark.parametrize("stage", ["optimization", "final_scf"])
def test_non_boolean_convergence_states_fail_without_soscf_retry(
    tmp_path: Path, invalid_state: object, stage: str
) -> None:
    request_path = _write_request(tmp_path / "request")
    backend = FakeBackend(
        optimization_scf_converged=(invalid_state if stage == "optimization" else True),
        final_scf_converged=invalid_state if stage == "final_scf" else True,
    )
    with pytest.raises(runner.TwoEndpointRunError):
        _execute(
            request_path,
            tmp_path / "result",
            backend,
            attempt_id=f"attempt-invalid-{stage.replace('_', '-')}",
        )
    expected_calls = [("optimize", "cation", "standard")]
    if stage == "final_scf":
        expected_calls.append(("final_scf", "cation", "standard"))
    assert backend.calls == expected_calls


@pytest.mark.parametrize(
    ("backend", "error_name", "exit_code"),
    [
        (FakeBackend(geometry_converged=False), "GeometryConvergenceError", 1),
        (FakeBackend(nonfinite_final_for="cation"), "BackendError", 1),
        (FakeBackend(timeout_for="neutral"), "BackendTimeoutError", 124),
    ],
)
def test_failures_are_nonzero_attempt_scoped_and_never_publish_success(
    tmp_path: Path, backend: FakeBackend, error_name: str, exit_code: int
) -> None:
    request_path = _write_request(tmp_path / "request")
    output = tmp_path / "result"
    with pytest.raises(runner.TwoEndpointRunError) as exc_info:
        _execute(request_path, output, backend, attempt_id="attempt-test-failure")
    assert exc_info.value.exit_code == exit_code
    attempt = output / "attempts" / "attempt-test-failure"
    failure = json.loads((attempt / "failure.json").read_text(encoding="utf-8"))
    assert failure["status"] == "failed"
    assert failure["error_type"] == error_name
    assert failure["exit_code"] == exit_code
    assert not (attempt / "_ATTEMPT_SUCCESS").exists()
    assert not (output / "_SUCCESS").exists()
    assert not (output / "success.json").exists()


def test_absolute_backend_deadline_is_shared_and_cannot_be_reset_or_extended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)

    for deadline, error in (
        (100.0, runner.BackendTimeoutError),
        (401.0, runner.ResourceConfigurationError),
    ):
        output = tmp_path / f"rejected-{deadline}"
        with pytest.raises(error):
            runner._execute_validated_request(  # pyright: ignore[reportPrivateUsage]
                request,
                output,
                backend=FakeBackend(),
                attempt_id="attempt-deadline-rejected",
                absolute_deadline_monotonic=deadline,
            )
        assert not output.exists()

    accepted = runner._execute_validated_request(  # pyright: ignore[reportPrivateUsage]
        request,
        tmp_path / "accepted",
        backend=FakeBackend(),
        attempt_id="attempt-deadline-accepted",
        absolute_deadline_monotonic=400.0,
    )
    assert accepted.attempt_id == "attempt-deadline-accepted"


def test_resume_reuses_only_an_exact_hash_complete_same_attempt(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "request")
    output = tmp_path / "result"
    first_backend = FakeBackend()
    first = _execute(request_path, output, first_backend, attempt_id="attempt-test-resume")
    second_backend = FakeBackend(timeout_for="cation")
    second = _execute(request_path, output, second_backend, attempt_id="attempt-unused")
    assert second == replace(first, resumed=True)
    assert second_backend.calls == []
    assert len(list((output / "attempts").iterdir())) == 1


def test_resume_hard_stops_on_output_tamper_and_input_drift(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "tamper-request")
    output = tmp_path / "tamper-result"
    first = _execute(request_path, output, FakeBackend(), attempt_id="attempt-test-tamper")
    result_path = output / first.result_relative_path
    result_path.write_text(result_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(runner.ResumeValidationError, match="hash mismatch"):
        _execute(request_path, output, FakeBackend(), attempt_id="attempt-new")

    request_path = _write_request(tmp_path / "drift-request")
    output = tmp_path / "drift-result"
    _execute(request_path, output, FakeBackend(), attempt_id="attempt-test-drift")
    neutral = request_path.parent / "neutral.xyz"
    _write_xyz(neutral, [("C", 0.2, 0.0, 0.1)])
    payload = cast(dict[str, object], json.loads(request_path.read_text(encoding="utf-8")))
    endpoints = cast(dict[str, dict[str, object]], payload["endpoints"])
    endpoints["neutral"]["xyz_sha256"] = sha256_file(neutral)
    request_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(runner.ResumeValidationError, match="identity mismatch"):
        _execute(request_path, output, FakeBackend(), attempt_id="attempt-new")


def test_resume_rejects_extra_attempt_file_even_when_unregistered(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "request")
    output = tmp_path / "result"
    result = _execute(request_path, output, FakeBackend(), attempt_id="attempt-file-set")
    attempt = output / "attempts" / result.attempt_id
    (attempt / "unexpected.dat").write_text("not allowed\n", encoding="utf-8")
    with pytest.raises(runner.ResumeValidationError, match="file set drifted"):
        _execute(request_path, output, FakeBackend(), attempt_id="attempt-new")


def test_resume_uses_strict_json_and_rejects_duplicate_keys_after_resigning(
    tmp_path: Path,
) -> None:
    request_path = _write_request(tmp_path / "request")
    output = tmp_path / "result"
    result = _execute(request_path, output, FakeBackend(), attempt_id="attempt-duplicate")
    result_path = output / result.result_relative_path
    original = result_path.read_text(encoding="utf-8")
    result_path.write_text(
        original.replace(
            '  "status": "success"\n}',
            '  "status": "success",\n  "status": "success"\n}',
            1,
        ),
        encoding="utf-8",
    )
    _resign_completed_output(output)
    with pytest.raises(runner.ResumeValidationError, match="duplicate key"):
        _execute(request_path, output, FakeBackend(), attempt_id="attempt-new")


def test_resume_rejects_resigned_result_identity_drift(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "request")
    output = tmp_path / "result"
    result = _execute(request_path, output, FakeBackend(), attempt_id="attempt-identity")
    result_path = output / result.result_relative_path
    payload = cast(dict[str, object], json.loads(result_path.read_text(encoding="utf-8")))
    payload["lower_is_better"] = False
    result_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    _resign_completed_output(output)
    with pytest.raises(runner.ResumeValidationError, match="lower_is_better"):
        _execute(request_path, output, FakeBackend(), attempt_id="attempt-new")


def test_resume_rejects_resigned_dynamic_d3_evidence_drift(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "request")
    output = tmp_path / "result"
    result = _execute(request_path, output, FakeBackend(), attempt_id="attempt-d3-evidence")
    attempt = output / "attempts" / result.attempt_id
    result_path = attempt / "result.json"
    payload = cast(dict[str, object], json.loads(result_path.read_text(encoding="utf-8")))
    endpoints = cast(dict[str, dict[str, object]], payload["endpoints"])
    cation = endpoints["cation"]
    final_scf = cast(dict[str, object], cation["final_scf"])
    dispersion = cast(dict[str, object], final_scf["dispersion"])
    dispersion["audit_calls"] = 2
    result_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (attempt / "cation.json").write_text(
        json.dumps(cation, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    _resign_completed_output(output)
    with pytest.raises(runner.ResumeValidationError, match="final evidence drifted"):
        _execute(request_path, output, FakeBackend(), attempt_id="attempt-new")


def test_resume_formula_tolerance_has_no_relative_error_loophole(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "request")
    output = tmp_path / "result"
    result = _execute(request_path, output, FakeBackend(), attempt_id="attempt-formula-tolerance")
    result_path = output / result.result_relative_path
    payload = cast(dict[str, object], json.loads(result_path.read_text(encoding="utf-8")))
    payload["electronic_difference_kcal"] = (
        float(cast(float, payload["electronic_difference_kcal"])) + 1.0e-8
    )
    result_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    _resign_completed_output(output)
    with pytest.raises(runner.ResumeValidationError, match="locked formula"):
        _execute(request_path, output, FakeBackend(), attempt_id="attempt-new")


def test_failed_attempt_endpoint_is_never_backfilled_into_later_success(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "request")
    output = tmp_path / "result"
    with pytest.raises(runner.TwoEndpointRunError):
        _execute(
            request_path,
            output,
            FakeBackend(timeout_for="neutral"),
            attempt_id="attempt-first-failed",
        )
    successful_backend = FakeBackend()
    result = _execute(request_path, output, successful_backend, attempt_id="attempt-second-success")
    assert successful_backend.calls[0] == ("optimize", "cation", "standard")
    success = json.loads((output / "success.json").read_text(encoding="utf-8"))
    assert success["attempt_id"] == "attempt-second-success"
    assert all(
        name.startswith("attempts/attempt-second-success/") for name in success["output_sha256"]
    )
    assert result.attempt_id == "attempt-second-success"


def test_module_has_no_eager_compute_import_or_forbidden_mode_switch() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    tree = compile(source, runner.__file__, "exec", flags=0, dont_inherit=True)
    assert tree is not None
    assert "from pyscf" not in source
    assert "import pyscf" not in source
    assert "dft_batch" not in source
    assert "submit_hpc" not in source
    assert "omegaB97" not in source
    assert "geometric_solver.kernel(" in source
    assert "type(value) is not bool" in source
    assert "_require_explicit_geometry_convergence(" in source
    assert "_require_explicit_scf_convergence(" in source
