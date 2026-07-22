from __future__ import annotations

import importlib
import json
import math
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


class FakeBackend:
    def __init__(
        self,
        *,
        fail_standard_final_for: str | None = None,
        fail_standard_opt_for: str | None = None,
        geometry_converged: bool = True,
        nonfinite_final_for: str | None = None,
        timeout_for: str | None = None,
    ) -> None:
        self.fail_standard_final_for = fail_standard_final_for
        self.fail_standard_opt_for = fail_standard_opt_for
        self.geometry_converged = geometry_converged
        self.nonfinite_final_for = nonfinite_final_for
        self.timeout_for = timeout_for
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
        del charge, multiplicity, deadline_monotonic
        self.calls.append(("optimize", endpoint, strategy))
        if self.timeout_for == endpoint:
            raise runner.BackendTimeoutError("synthetic timeout")
        if self.fail_standard_opt_for == endpoint and strategy == "standard":
            raise runner.SCFConvergenceError("synthetic SCF convergence failure")
        shifted = runner.XYZGeometry(
            tuple(replace(atom, x=atom.x + 0.01) for atom in geometry.atoms)
        )
        return runner.BackendOptimizationResult(
            geometry=shifted,
            geometry_converged=self.geometry_converged,
            scf_converged=True,
            last_energy_hartree=-100.0 if endpoint == "cation" else -99.0,
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
        del geometry, charge, multiplicity, deadline_monotonic
        self.calls.append(("final_scf", endpoint, strategy))
        if self.timeout_for == endpoint:
            raise runner.BackendTimeoutError("synthetic timeout")
        if self.fail_standard_final_for == endpoint and strategy == "standard":
            return runner.BackendSCFResult(converged=False, energy_hartree=-1.0)
        energy = -100.125 if endpoint == "cation" else -99.875
        if self.nonfinite_final_for == endpoint:
            energy = math.nan
        return runner.BackendSCFResult(converged=True, energy_hartree=energy)


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
    runner.PySCFBackend()
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


@pytest.mark.parametrize("geometry_converged", [True, False])
def test_pyscf_adapter_uses_geometric_kernel_and_explicit_convergence_with_fake_modules(
    monkeypatch: pytest.MonkeyPatch, geometry_converged: bool
) -> None:
    geometry = runner.XYZGeometry((runner.XYZAtom("C", 0.0, 0.0, 0.0),))
    kernel_calls: list[dict[str, object]] = []

    class FakeMolecule:
        natm = 1

        def atom_coords(self, *, unit: str) -> list[list[float]]:
            assert unit == "Angstrom"
            return [[0.01, 0.0, 0.0]]

        def atom_symbol(self, index: int) -> str:
            assert index == 0
            return "C"

    class FakeGTO:
        @staticmethod
        def M(**kwargs: object) -> FakeMolecule:
            assert kwargs["basis"] == "def2-svp"
            assert kwargs["charge"] == 1
            assert kwargs["spin"] == 0
            return FakeMolecule()

    class FakeGrids:
        level = 0

    class FakeMeanField:
        def __init__(self) -> None:
            self.xc = ""
            self.grids = FakeGrids()
            self.conv_tol = 0.0
            self.max_cycle = 0
            self.disp: str | None = None
            self.converged = True
            self.e_tot = -10.0

        def do_disp(self) -> bool:
            return True

        def newton(self) -> FakeMeanField:
            return self

    mean_field = FakeMeanField()

    class FakeDFT:
        @staticmethod
        def RKS(molecule: FakeMolecule) -> FakeMeanField:
            assert isinstance(molecule, FakeMolecule)
            return mean_field

    class FakeGeometricSolver:
        @staticmethod
        def kernel(method: FakeMeanField, **kwargs: object) -> tuple[bool, FakeMolecule]:
            assert method is mean_field
            kernel_calls.append(kwargs)
            return geometry_converged, FakeMolecule()

    backend = runner.PySCFBackend()
    monkeypatch.setattr(
        backend,
        "_load_modules",
        lambda: (FakeGTO(), FakeDFT(), FakeGeometricSolver()),
    )
    if geometry_converged:
        result = backend.optimize(
            endpoint="cation",
            geometry=geometry,
            charge=1,
            multiplicity=1,
            strategy="standard",
            deadline_monotonic=math.inf,
        )
        assert result.geometry_converged is True
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
    assert mean_field.disp == "d3bj"
    assert mean_field.xc == "B3LYP"
    assert mean_field.grids.level == 3


def test_request_validates_locked_protocol_xyz_paths_and_hashes(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    assert request.protocol_sha256 == runner.LOCKED_PROTOCOL_SHA256
    assert request.runner_source_sha256 == runner.current_runner_source_sha256()
    assert request.cation.charge == 1
    assert request.neutral.charge == 0
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
        {"converged": False, "failure_kind": "scf", "strategy": "standard"},
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
    assert "geometry_converged is not True" in source
