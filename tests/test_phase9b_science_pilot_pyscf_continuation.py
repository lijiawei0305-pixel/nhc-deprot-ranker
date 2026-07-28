from __future__ import annotations

import ast
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase9b_science_pilot_pyscf_continuation.py"


def _load_continuation() -> Any:
    spec = importlib.util.spec_from_file_location(
        "phase9b_science_pilot_pyscf_continuation", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_endpoint_charge_multiplicity_spin_and_single_candidate_are_frozen() -> None:
    continuation = _load_continuation()

    assert continuation.CANDIDATE == "LBNPGYISTSLAHY-UHFFFAOYSA-N"
    assert continuation.ENDPOINTS == ("cation", "neutral")
    assert continuation.CHARGES == {"cation": 1, "neutral": 0}
    assert continuation.MULTIPLICITIES == {"cation": 1, "neutral": 1}
    assert continuation.SPINS == {"cation": 0, "neutral": 0}
    assert continuation.ATOM_COUNTS == {"cation": 26, "neutral": 25}
    for endpoint in continuation.ENDPOINTS:
        assert continuation.SPINS[endpoint] == continuation.MULTIPLICITIES[endpoint] - 1


def test_exact_byte_copy_is_parser_input_without_reserialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    continuation = _load_continuation()
    raw = b"2\nscience_pilot_only\nH 0.0 0.0 0.0\nH 0.0 0.0 0.7\n"
    source = tmp_path / "retained" / "final.xyz"
    evidence = tmp_path / "input" / "cation_aimnet2_final.xyz"
    parser_input = tmp_path / "pyscf" / "cation" / "input.xyz"
    source.parent.mkdir()
    evidence.parent.mkdir()
    parser_input.parent.mkdir(parents=True)
    source.write_bytes(raw)
    monkeypatch.setitem(continuation.SOURCE_BYTES, "cation", len(raw))
    monkeypatch.setitem(continuation.SOURCE_SHA256, "cation", continuation._sha256(raw))

    parser_raw, receipt = continuation.validate_source_and_copy(
        endpoint="cation",
        source_path=source,
        evidence_input_path=evidence,
        parser_input_path=parser_input,
    )

    assert source.read_bytes() == evidence.read_bytes() == parser_input.read_bytes() == parser_raw
    assert receipt["source_sha256"] == receipt["copied_input_sha256"]
    assert receipt["copied_input_sha256"] == receipt["parser_input_sha256"]
    assert receipt["source_byte_count"] == receipt["parser_input_byte_count"] == len(raw)
    with pytest.raises(FileExistsError):
        continuation.validate_source_and_copy(
            endpoint="cation",
            source_path=source,
            evidence_input_path=evidence,
            parser_input_path=parser_input,
        )


def test_interpreter_capture_allows_stable_regular_hardlink(tmp_path: Path) -> None:
    continuation = _load_continuation()
    environment = tmp_path / "environment"
    executable = environment / "bin" / "python3.11"
    launcher = environment / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fake executable bytes")
    executable.chmod(0o755)
    launcher.hardlink_to(executable)
    expected = continuation._sha256(executable.read_bytes())

    evidence = continuation.capture_interpreter(launcher, expected_executable_sha256=expected)

    assert evidence["launcher_kind"] == "regular"
    assert evidence["resolved_inside_environment_root"] is True
    assert evidence["resolved_identity"]["link_count"] == 2
    assert evidence["resolved_executable_sha256"] == expected


def test_frozen_deprotonation_formula_uses_only_two_pyscf_energies() -> None:
    continuation = _load_continuation()

    result = continuation.compute_deprotonation(-100.0, -99.0)

    assert result["hartree_difference"] == pytest.approx(1.0)
    assert result["electronic_difference_kcal_per_mol"] == pytest.approx(627.509474)
    assert result["value_kcal_per_mol"] == pytest.approx(621.229474, abs=1.0e-12)
    assert result["aimnet2_energy_used"] is False
    assert result["lower_is_better"] is True
    with pytest.raises(continuation.ContinuationError, match="non-finite"):
        continuation.compute_deprotonation(math.nan, -99.0)


def test_standard_failure_only_allows_typed_scf_nonconvergence_fallback() -> None:
    continuation = _load_continuation()

    class SCFNotConvergedError(RuntimeError):
        pass

    calls: list[str] = []

    def call_scf(**kwargs: object) -> object:
        strategy = str(kwargs["strategy"])
        calls.append(strategy)
        if strategy == "standard":
            raise SCFNotConvergedError("fixture")
        return SimpleNamespace(converged=True)

    module = SimpleNamespace(SCFNotConvergedError=SCFNotConvergedError, _call_scf=call_scf)
    endpoint = SimpleNamespace(geometry=object())

    _, strategy, attempts = continuation.run_single_point(
        module=module, backend=object(), endpoint=endpoint, deadline=10.0
    )

    assert calls == ["standard", "soscf"]
    assert strategy == "soscf"
    assert [attempt["strategy"] for attempt in attempts] == ["standard", "soscf"]

    module._call_scf = lambda **_kwargs: (_ for _ in ()).throw(ValueError("not retryable"))
    with pytest.raises(ValueError, match="not retryable"):
        continuation.run_single_point(
            module=module, backend=object(), endpoint=endpoint, deadline=10.0
        )


def test_environmental_timeout_is_inconclusive_not_scientific_failure() -> None:
    continuation = _load_continuation()

    class BackendError(RuntimeError):
        pass

    class BackendTimeoutError(BackendError):
        pass

    module = SimpleNamespace(
        BackendTimeoutError=BackendTimeoutError,
        ResourceConfigurationError=type("ResourceConfigurationError", (BackendError,), {}),
        ResourceLimitError=type("ResourceLimitError", (BackendError,), {}),
        SCFNotConvergedError=type("SCFNotConvergedError", (BackendError,), {}),
        SCFConvergenceError=type("SCFConvergenceError", (BackendError,), {}),
        DispersionUnavailableError=type("DispersionUnavailableError", (BackendError,), {}),
        DispersionEvaluationError=type("DispersionEvaluationError", (BackendError,), {}),
    )

    assert continuation._failure_outcome(module, BackendTimeoutError("fixture")) == "INCONCLUSIVE"


def test_pre_handoff_failure_writes_inconclusive_terminal_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    continuation = _load_continuation()
    runs = tmp_path / "runs"
    root = runs / continuation.CONTINUATION_ROOT_NAME
    v002 = runs / "science_pilot_lbn_v002"
    wrong_source = root / "driver" / "wrong-src"
    root.mkdir(parents=True)
    v002.mkdir()
    wrong_source.mkdir(parents=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--root",
            str(root),
            "--v002-root",
            str(v002),
            "--source-root",
            str(wrong_source),
            "--source-commit",
            "a" * 40,
            "--continuation-source-sha256",
            continuation._sha256(SCRIPT.read_bytes()),
            "--expected-executable-sha256",
            "b" * 64,
        ],
    )

    assert continuation.main() == 2

    result = json.loads((root / "result.json").read_text())
    assert result["final_outcome"] == "INCONCLUSIVE"
    assert result["production_accepted"] is False
    assert (root / "file_manifest.json").is_file()


def test_initial_guess_observer_does_not_override_runtime_default() -> None:
    continuation = _load_continuation()

    class MeanField:
        def __init__(self) -> None:
            self.init_guess = "runtime-default"
            self.chkfile = None

        def get_init_guess(self, _mol: object = None, key: str = "minao") -> str:
            return key

        def kernel(self) -> float:
            self.get_init_guess(object(), key=self.init_guess)
            return -1.0

    class BaseBackend:
        def __init__(self) -> None:
            self._pilot_context: tuple[str, str, str] | None = None
            self._pilot_last_mean_field: object | None = None

        def _mean_field(self, **_kwargs: object) -> tuple[object, object, object]:
            mean_field = MeanField()
            self._pilot_last_mean_field = mean_field
            return mean_field, object(), object()

        def final_scf(self, **kwargs: object) -> float:
            self._pilot_context = (str(kwargs["endpoint"]), "final_scf", str(kwargs["strategy"]))
            mean_field, _, _ = self._mean_field()
            return float(mean_field.kernel())  # type: ignore[attr-defined]

    pilot = SimpleNamespace(
        _SciencePilotPySCFBackend=SimpleNamespace(build=lambda _module: BaseBackend())
    )
    backend = continuation.build_observed_backend(pilot=pilot, module=object())

    assert backend.final_scf(endpoint="cation", strategy="standard") == -1.0
    evidence = backend.initial_guess_evidence["cation:standard"]
    assert evidence["kernel_call_count"] == 1
    assert evidence["project_dm0_argument"] is False
    assert evidence["project_init_guess_override"] is False
    assert evidence["get_init_guess_calls"][0]["key"] == "runtime-default"
    assert evidence["owners"][0]["configured_init_guess_before"] == "runtime-default"
    assert evidence["owners"][0]["configured_init_guess_after"] == "runtime-default"


def test_continuation_has_no_optimizer_or_production_acceptance_path() -> None:
    source = SCRIPT.read_text()
    tree = ast.parse(source)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "optimize" not in calls
    assert "geometric_solver" not in source
    assert '"production_accepted": False' in source
    assert '"production_label_inserted": False' in source
    assert '"aimnet2_rerun": False' in source
