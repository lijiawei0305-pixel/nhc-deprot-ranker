from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum import worker


def _write_xyz(path: Path, atoms: list[tuple[str, float, float, float]]) -> None:
    lines = [str(len(atoms)), "synthetic Phase 8A protocol fixture"]
    lines.extend(f"{element} {x} {y} {z}" for element, x, y, z in atoms)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_request(root: Path, *, execution_authorized: bool = True) -> Path:
    root.mkdir(parents=True)
    _write_xyz(root / "cation.xyz", [("C", 0.0, 0.0, 0.0), ("H", 0.0, 0.0, 1.0)])
    _write_xyz(root / "neutral.xyz", [("C", 0.0, 0.0, 0.1)])
    payload = {
        "schema_version": runner.REQUEST_SCHEMA_VERSION,
        "request_id": "phase8a-protocol-001",
        "inchikey": "IJWCXRPLHNQISE-UHFFFAOYSA-N",
        "execution_authorized": execution_authorized,
        "timeout_seconds": 30,
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
    request_path = root / "request.json"
    request_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return request_path


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
    return runner.FinalD3Evidence(
        tag="d3bj",
        energy_hook_calls=1,
        breakdown=runner.FinalEnergyBreakdown(
            nuclear_hartree=0.0,
            one_electron_hartree=energy - dispersion,
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


class _DeterministicBackend:
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
        del multiplicity, strategy, deadline_monotonic
        return runner.BackendOptimizationResult(
            geometry=geometry,
            geometry_converged=True,
            scf_converged=True,
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
        del multiplicity, strategy, deadline_monotonic
        energy = -100.125 if endpoint == "cation" else -99.875
        return runner.BackendSCFResult(
            converged=True,
            energy_hartree=energy,
            runtime=_runtime_evidence(geometry, charge=charge),
            dispersion=_final_d3(energy, len(geometry.atoms)),
        )


class _NeutralFailureBackend(_DeterministicBackend):
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
        if endpoint == "neutral":
            raise runner.BackendUnknownError("synthetic\tneutral failure")
        return super().optimize(
            endpoint=endpoint,
            geometry=geometry,
            charge=charge,
            multiplicity=multiplicity,
            strategy=strategy,
            deadline_monotonic=deadline_monotonic,
        )


@dataclass(frozen=True)
class _FakeSupervisionResult:
    outcome: str
    returncode: int | None
    child_returncode: int | None = 0
    stdout: bytes = b""
    stderr: bytes = b""
    stdout_total_bytes: int = 0
    stderr_total_bytes: int = 0
    timed_out: bool = False
    term_sent: bool = False
    kill_sent: bool = False
    orphan_descendants_detected: bool = False
    process_started: bool = True
    group_cleanup_confirmed: bool = True
    direct_child_reaped: bool = True
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    duration_seconds: float = 0.25
    pid: int | None = 4242
    pgid: int | None = 4242
    error_message: str | None = None


def _argument_value(argv: Sequence[str], option: str) -> str:
    index = argv.index(option)
    return argv[index + 1]


def _produce_valid_worker_failure(
    request: runner.TwoEndpointRequest,
    worker_output: Path,
    attempt_id: str,
) -> Path:
    with pytest.raises(runner.TwoEndpointRunError) as exc_info:
        runner._execute_validated_request(  # pyright: ignore[reportPrivateUsage]
            request,
            worker_output,
            backend=_NeutralFailureBackend(),
            attempt_id=attempt_id,
        )
    assert exc_info.value.exit_code == 1
    failure_path = worker_output / "attempts" / attempt_id / "failure.json"
    assert failure_path.is_file()
    return failure_path


def test_atomic_write_is_private_and_fsyncs_file_and_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private.json"
    fchmod_modes: list[int] = []
    fstat_directory_kinds: list[bool] = []
    fsync_targets: list[tuple[bool, int, int]] = []
    real_fchmod = runner.os.fchmod
    real_fstat = runner.os.fstat
    real_fsync = runner.os.fsync

    def tracked_fchmod(descriptor: int, mode: int) -> None:
        fchmod_modes.append(mode)
        real_fchmod(descriptor, mode)

    def tracked_fstat(descriptor: int) -> os.stat_result:
        observed = real_fstat(descriptor)
        fstat_directory_kinds.append(stat.S_ISDIR(observed.st_mode))
        return observed

    def tracked_fsync(descriptor: int) -> None:
        observed = real_fstat(descriptor)
        fsync_targets.append((stat.S_ISDIR(observed.st_mode), observed.st_dev, observed.st_ino))
        real_fsync(descriptor)

    monkeypatch.setattr(runner.os, "fchmod", tracked_fchmod)
    monkeypatch.setattr(runner.os, "fstat", tracked_fstat)
    monkeypatch.setattr(runner.os, "fsync", tracked_fsync)

    runner._atomic_write_bytes(target, b"private\n")  # pyright: ignore[reportPrivateUsage]

    parent_stat = tmp_path.stat()
    assert target.read_bytes() == b"private\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert fchmod_modes == [0o600]
    assert fstat_directory_kinds[0] is False
    assert False in fstat_directory_kinds and True in fstat_directory_kinds
    assert fsync_targets[0][0] is False
    assert (True, parent_stat.st_dev, parent_stat.st_ino) in fsync_targets


def test_attempt_move_fsyncs_moved_directory_then_attempts_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts_root = tmp_path / "attempts"
    attempts_root.mkdir()
    source = attempts_root / ".tmp-attempt"
    source.mkdir()
    (source / "failure.json").write_text("{}\n", encoding="utf-8")
    destination = attempts_root / "attempt-fixed"
    fsynced: list[Path] = []
    monkeypatch.setattr(runner, "_fsync_directory", fsynced.append)

    runner._durably_move_attempt(  # pyright: ignore[reportPrivateUsage]
        source,
        destination,
        attempts_root=attempts_root,
    )

    assert not source.exists()
    assert destination.is_dir()
    assert fsynced == [destination, attempts_root]


def test_public_gate_is_before_request_supervisor_import_spawn_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def forbidden_request(path: Path) -> runner.TwoEndpointRequest:
        del path
        calls.append("request")
        raise AssertionError("request must not be read")

    def forbidden_import(name: str, package: str | None = None) -> object:
        del name, package
        calls.append("import")
        raise AssertionError("supervisor or compute module must not be imported")

    monkeypatch.setattr(runner, "load_two_endpoint_request", forbidden_request)
    monkeypatch.setattr(importlib, "import_module", forbidden_import)
    with pytest.raises(runner.ExecutionNotAuthorizedError):
        runner.run_two_endpoint(tmp_path / "missing.json", tmp_path / "output")
    assert calls == []
    assert not (tmp_path / "output").exists()


def test_worker_main_gate_is_before_argv_request_import_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    def closed_gate() -> None:
        events.append("gate")
        raise runner.ExecutionNotAuthorizedError("synthetic closed source gate")

    def forbidden_parse(argv: Sequence[str] | None) -> object:
        del argv
        events.append("argv")
        raise AssertionError("argv must not be inspected")

    monkeypatch.setattr(worker.runner, "_ensure_execution_authorized", closed_gate)
    monkeypatch.setattr(worker, "_parse_arguments", forbidden_parse)
    with pytest.raises(runner.ExecutionNotAuthorizedError):
        worker.main(["--output-root", str(tmp_path / "output")])
    assert events == ["gate"]
    assert not (tmp_path / "output").exists()


def test_worker_request_gate_is_before_backend_construction_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_path = _write_request(tmp_path / "request", execution_authorized=False)
    monkeypatch.setattr(worker.runner, "_ensure_execution_authorized", lambda: None)

    def forbidden_backend() -> object:
        raise AssertionError("backend must not be constructed")

    monkeypatch.setattr(worker.runner, "PySCFBackend", forbidden_backend)
    output = tmp_path / "output"
    with pytest.raises(runner.ExecutionNotAuthorizedError):
        worker.main(
            [
                "--request-path",
                str(request_path),
                "--output-root",
                str(output),
                "--attempt-id",
                "attempt-request-gate",
            ]
        )
    assert not output.exists()


def test_runner_source_hash_canonically_binds_full_pre_gate_import_chain() -> None:
    source_root = Path(runner.__file__).resolve().parents[2]
    names = runner._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    sources = {name: (source_root / name).read_bytes() for name in names}
    baseline = runner._canonical_runner_source_sha256(  # pyright: ignore[reportPrivateUsage]
        sources
    )
    assert baseline == runner.current_runner_source_sha256()
    for name in names:
        mutated = dict(sources)
        mutated[name] += b"\n# synthetic source drift\n"
        assert (
            runner._canonical_runner_source_sha256(  # pyright: ignore[reportPrivateUsage]
                mutated
            )
            != baseline
        )
    with pytest.raises(ValueError, match="exact canonical file set"):
        runner._canonical_runner_source_sha256(  # pyright: ignore[reportPrivateUsage]
            {**sources, "unexpected.py": b"pass\n"}
        )


def test_mock_supervised_worker_is_parent_validated_then_published_as_exact_six_files(
    tmp_path: Path,
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    output = tmp_path / "output"
    attempt_id = "attempt-supervised-success"
    seen: dict[str, object] = {}

    def fake_supervisor(
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> _FakeSupervisionResult:
        seen.update({"argv": list(argv), "policy": policy, "cwd": cwd, "env": env})
        worker_request = runner.load_two_endpoint_request(
            Path(_argument_value(argv, "--request-path"))
        )
        worker_output = Path(_argument_value(argv, "--output-root"))
        worker_attempt = _argument_value(argv, "--attempt-id")
        runner._execute_validated_request(  # pyright: ignore[reportPrivateUsage]
            worker_request,
            worker_output,
            backend=_DeterministicBackend(),
            attempt_id=worker_attempt,
        )
        assert not (output / "_SUCCESS").exists()
        assert not (output / "attempts" / attempt_id).exists()
        return _FakeSupervisionResult(outcome="clean", returncode=0)

    policy = object()
    result = runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
        request,
        output,
        run_supervised=fake_supervisor,
        supervision_policy=policy,
        attempt_id=attempt_id,
        python_executable="/synthetic/python",
    )
    assert result.attempt_id == attempt_id
    assert result.resumed is False
    assert {path.name for path in output.iterdir()} == {"_SUCCESS", "success.json", "attempts"}
    attempt = output / "attempts" / attempt_id
    assert {path.name for path in attempt.iterdir()} == {
        "_ATTEMPT_SUCCESS",
        "cation.json",
        "cation.optimized.xyz",
        "neutral.json",
        "neutral.optimized.xyz",
        "result.json",
    }
    assert seen["policy"] is policy
    assert seen["cwd"] == Path(runner.__file__).resolve().parents[2]
    assert seen["argv"][0] == "/synthetic/python"  # type: ignore[index]
    assert seen["argv"][1:4] == ["-I", "-B", "-c"]  # type: ignore[index]
    environment = seen["env"]
    assert isinstance(environment, dict)
    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    assert "PYTHONSTARTUP" not in environment
    success = json.loads((output / "success.json").read_text(encoding="utf-8"))
    assert success["supervision"] == {
        "outcome": "clean",
        "public_returncode": 0,
        "child_returncode": 0,
        "duration_seconds": 0.25,
        "pid": 4242,
        "pgid": 4242,
        "stdout_total_bytes": 0,
        "stdout_captured_bytes": 0,
        "stdout_captured_sha256": hashlib.sha256(b"").hexdigest(),
        "stdout_truncated": False,
        "stderr_total_bytes": 0,
        "stderr_captured_bytes": 0,
        "stderr_captured_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_truncated": False,
        "timed_out": False,
        "term_sent": False,
        "kill_sent": False,
        "orphan_descendants_detected": False,
        "process_started": True,
        "group_cleanup_confirmed": True,
        "direct_child_reaped": True,
        "error_message": None,
    }
    assert not list(tmp_path.glob(f".worker-{attempt_id}-*"))


def test_deferred_acceptance_publishes_only_hash_bound_supervisor_provisional(
    tmp_path: Path,
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    output = tmp_path / "output"
    attempt_id = "attempt-deferred-acceptance"

    def fake_supervisor(
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> _FakeSupervisionResult:
        del policy, cwd, env
        worker_request = runner.load_two_endpoint_request(
            Path(_argument_value(argv, "--request-path"))
        )
        runner._execute_validated_request(  # pyright: ignore[reportPrivateUsage]
            worker_request,
            Path(_argument_value(argv, "--output-root")),
            backend=_DeterministicBackend(),
            attempt_id=_argument_value(argv, "--attempt-id"),
        )
        return _FakeSupervisionResult(outcome="clean", returncode=0)

    first = runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
        request,
        output,
        run_supervised=fake_supervisor,
        supervision_policy=object(),
        attempt_id=attempt_id,
        defer_final_acceptance=True,
    )
    assert first.resumed is False
    assert {path.name for path in output.iterdir()} == {
        "_SUPERVISOR_SUCCESS",
        "supervisor_success.json",
        "attempts",
    }
    assert not (output / "_SUCCESS").exists()
    assert not (output / "success.json").exists()
    provisional_path = output / "supervisor_success.json"
    provisional = json.loads(provisional_path.read_text(encoding="utf-8"))
    marker = json.loads((output / "_SUPERVISOR_SUCCESS").read_text(encoding="utf-8"))
    assert provisional["schema_version"] == runner.SUPERVISOR_SUCCESS_SCHEMA_VERSION
    assert provisional["supervision"]["group_cleanup_confirmed"] is True
    assert marker["supervisor_success_sha256"] == sha256_file(provisional_path)

    def forbidden_supervisor(*args: object, **kwargs: object) -> _FakeSupervisionResult:
        del args, kwargs
        raise AssertionError("exact provisional resume must not spawn another worker")

    resumed = runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
        request,
        output,
        run_supervised=forbidden_supervisor,
        supervision_policy=object(),
        attempt_id="attempt-unused",
        defer_final_acceptance=True,
    )
    assert resumed.resumed is True
    assert resumed.attempt_id == attempt_id


def test_clean_worker_with_truncated_stream_is_published_only_as_failure(
    tmp_path: Path,
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    output = tmp_path / "output"
    attempt_id = "attempt-truncated-stream"

    def fake_supervisor(
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> _FakeSupervisionResult:
        del policy, cwd, env
        worker_request = runner.load_two_endpoint_request(
            Path(_argument_value(argv, "--request-path"))
        )
        runner._execute_validated_request(  # pyright: ignore[reportPrivateUsage]
            worker_request,
            Path(_argument_value(argv, "--output-root")),
            backend=_DeterministicBackend(),
            attempt_id=_argument_value(argv, "--attempt-id"),
        )
        return _FakeSupervisionResult(
            outcome="clean",
            returncode=0,
            child_returncode=0,
            stdout=b"abcd",
            stdout_total_bytes=5,
            stdout_truncated=True,
        )

    with pytest.raises(runner.TwoEndpointRunError) as exc_info:
        runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
            request,
            output,
            run_supervised=fake_supervisor,
            supervision_policy=object(),
            attempt_id=attempt_id,
        )
    assert exc_info.value.exit_code == 1
    failure = json.loads(
        (output / "attempts" / attempt_id / "failure.json").read_text(encoding="utf-8")
    )
    assert failure["error_type"] == "WorkerOutputTruncatedError"
    assert failure["supervision"]["stdout_total_bytes"] == 5
    assert failure["supervision"]["stdout_captured_bytes"] == 4
    assert failure["supervision"]["stdout_truncated"] is True
    assert not (output / "_SUCCESS").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("child_returncode", 1),
        ("duration_seconds", -1.0),
        ("pgid", 4243),
        ("stdout_truncated", True),
        ("group_cleanup_confirmed", False),
    ],
)
def test_recorded_clean_supervision_schema_fails_closed(field: str, value: object) -> None:
    evidence = runner._supervision_evidence_payload(  # pyright: ignore[reportPrivateUsage]
        _FakeSupervisionResult(outcome="clean", returncode=0)
    )
    evidence[field] = value
    with pytest.raises(runner.ResumeValidationError):
        runner._validate_recorded_supervision(  # pyright: ignore[reportPrivateUsage]
            evidence, require_success=True
        )


def test_successful_supervision_rejects_duration_one_float_past_frozen_wall() -> None:
    frozen_wall = runner._SUPERVISOR_HARD_WALL_SECONDS  # pyright: ignore[reportPrivateUsage]
    epsilon_over = math.nextafter(frozen_wall, math.inf)
    at_limit = runner._supervision_evidence_payload(  # pyright: ignore[reportPrivateUsage]
        _FakeSupervisionResult(
            outcome="clean",
            returncode=0,
            duration_seconds=frozen_wall,
        )
    )
    runner._validate_recorded_supervision(  # pyright: ignore[reportPrivateUsage]
        at_limit, require_success=True
    )

    with pytest.raises(runner.ResumeValidationError, match="frozen hard wall-time"):
        runner._supervision_evidence_payload(  # pyright: ignore[reportPrivateUsage]
            _FakeSupervisionResult(
                outcome="clean",
                returncode=0,
                duration_seconds=epsilon_over,
            )
        )

    at_limit["duration_seconds"] = epsilon_over
    with pytest.raises(runner.ResumeValidationError, match="frozen hard wall-time"):
        runner._validate_recorded_supervision(  # pyright: ignore[reportPrivateUsage]
            at_limit, require_success=True
        )


@pytest.mark.parametrize(
    ("supervision", "error_type", "exit_code"),
    [
        (
            _FakeSupervisionResult(
                outcome="timeout",
                returncode=124,
                child_returncode=-9,
                timed_out=True,
                term_sent=True,
                kill_sent=True,
            ),
            "HardWallTimeoutError",
            124,
        ),
        (
            _FakeSupervisionResult(
                outcome="nonzero",
                returncode=1,
                child_returncode=1,
            ),
            "WorkerExitError",
            1,
        ),
    ],
)
def test_timeout_and_nonzero_publish_only_atomic_failure_after_supervisor_returns(
    tmp_path: Path,
    supervision: _FakeSupervisionResult,
    error_type: str,
    exit_code: int,
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    output = tmp_path / "output"
    attempt_id = "attempt-supervised-failure"
    returned = False
    worker_failure_sha256: str | None = None

    def fake_supervisor(
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> _FakeSupervisionResult:
        del policy, cwd, env
        worker_output = Path(_argument_value(argv, "--output-root"))
        if supervision.outcome == "nonzero":
            worker_request = runner.load_two_endpoint_request(
                Path(_argument_value(argv, "--request-path"))
            )
            worker_failure_path = _produce_valid_worker_failure(
                worker_request, worker_output, attempt_id
            )
            nonlocal worker_failure_sha256
            worker_failure_sha256 = sha256_file(worker_failure_path)
        else:
            (worker_output / "partial-endpoint.dat").write_text("partial\n", encoding="utf-8")
        assert not (output / "attempts" / attempt_id).exists()
        nonlocal returned
        returned = True
        return supervision

    with pytest.raises(runner.TwoEndpointRunError) as exc_info:
        runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
            request,
            output,
            run_supervised=fake_supervisor,
            supervision_policy=object(),
            attempt_id=attempt_id,
        )
    assert returned is True
    assert exc_info.value.exit_code == exit_code
    attempt = output / "attempts" / attempt_id
    assert {path.name for path in attempt.iterdir()} == {"failure.json"}
    failure = json.loads((attempt / "failure.json").read_text(encoding="utf-8"))
    assert failure["error_type"] == error_type
    assert failure["exit_code"] == exit_code
    assert failure["supervision"]["outcome"] == supervision.outcome
    assert failure["supervision"]["child_returncode"] == supervision.child_returncode
    assert failure["supervision"]["stdout_captured_sha256"] == hashlib.sha256(b"").hexdigest()
    if supervision.outcome == "nonzero":
        assert failure["worker_failure_sha256"] == worker_failure_sha256
        assert failure["worker_failure"]["stage"] == "neutral"
        assert failure["worker_failure"]["error_type"] == "BackendUnknownError"
        assert failure["worker_failure"]["error_message"] == "synthetic neutral failure"
    else:
        assert "worker_failure" not in failure
        assert "worker_failure_sha256" not in failure
    assert not (output / "_SUCCESS").exists()
    assert not (output / "success.json").exists()
    assert not list(tmp_path.glob(f".worker-{attempt_id}-*"))


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_identity",
        "missing_failure",
        "unexpected.dat",
        "result.json",
        "_ATTEMPT_SUCCESS",
        "cross_attempt",
    ],
)
def test_nonzero_worker_with_invalid_failure_evidence_is_protocol_failure_and_preserved(
    tmp_path: Path,
    mutation: str,
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    output = tmp_path / "output"
    attempt_id = "attempt-invalid-failure-evidence"
    observed_scratch: Path | None = None

    def fake_supervisor(
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> _FakeSupervisionResult:
        del policy, cwd, env
        nonlocal observed_scratch
        observed_scratch = Path(_argument_value(argv, "--output-root"))
        worker_request = runner.load_two_endpoint_request(
            Path(_argument_value(argv, "--request-path"))
        )
        failure_path = _produce_valid_worker_failure(worker_request, observed_scratch, attempt_id)
        worker_attempt = failure_path.parent
        if mutation == "wrong_identity":
            payload = json.loads(failure_path.read_text(encoding="utf-8"))
            payload["request_id"] = "wrong-request"
            failure_path.write_text(
                json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        elif mutation == "missing_failure":
            failure_path.unlink()
        elif mutation == "cross_attempt":
            (observed_scratch / "attempts" / "attempt-cross-state").mkdir()
        else:
            (worker_attempt / mutation).write_text("forbidden\n", encoding="utf-8")
        return _FakeSupervisionResult(outcome="nonzero", returncode=1, child_returncode=1)

    with pytest.raises(runner.TwoEndpointRunError) as exc_info:
        runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
            request,
            output,
            run_supervised=fake_supervisor,
            supervision_policy=object(),
            attempt_id=attempt_id,
        )
    assert exc_info.value.exit_code == 1
    assert observed_scratch is not None and observed_scratch.is_dir()
    parent_failure = json.loads(
        (output / "attempts" / attempt_id / "failure.json").read_text(encoding="utf-8")
    )
    assert parent_failure["error_type"] == "WorkerProtocolError"
    assert "worker_failure" not in parent_failure
    assert "worker_failure_sha256" not in parent_failure
    assert not (output / "_SUCCESS").exists()


def test_clean_exit_with_invalid_worker_state_is_protocol_failure_not_success(
    tmp_path: Path,
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    output = tmp_path / "output"
    attempt_id = "attempt-invalid-worker-state"

    def fake_supervisor(
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> _FakeSupervisionResult:
        del policy, cwd, env
        worker_output = Path(_argument_value(argv, "--output-root"))
        (worker_output / "untrusted-success.txt").write_text("success\n", encoding="utf-8")
        return _FakeSupervisionResult(outcome="clean", returncode=0)

    with pytest.raises(runner.TwoEndpointRunError) as exc_info:
        runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
            request,
            output,
            run_supervised=fake_supervisor,
            supervision_policy=object(),
            attempt_id=attempt_id,
        )
    assert exc_info.value.exit_code == 1
    attempt = output / "attempts" / attempt_id
    assert {path.name for path in attempt.iterdir()} == {"failure.json"}
    failure = json.loads((attempt / "failure.json").read_text(encoding="utf-8"))
    assert failure["error_type"] == "WorkerProtocolError"
    assert not (output / "_SUCCESS").exists()


def test_unconfirmed_cleanup_never_publishes_or_removes_worker_scratch(
    tmp_path: Path,
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    output = tmp_path / "output"
    attempt_id = "attempt-unconfirmed-cleanup"

    def unsafe_supervisor(
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> _FakeSupervisionResult:
        del policy, cwd, env
        worker_output = Path(_argument_value(argv, "--output-root"))
        (worker_output / "still-owned-by-unconfirmed-worker.dat").write_text(
            "partial\n", encoding="utf-8"
        )
        return _FakeSupervisionResult(
            outcome="supervision_error",
            returncode=1,
            timed_out=True,
            kill_sent=True,
            group_cleanup_confirmed=False,
            direct_child_reaped=True,
        )

    with pytest.raises(runner.TwoEndpointRunError) as exc_info:
        runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
            request,
            output,
            run_supervised=unsafe_supervisor,
            supervision_policy=object(),
            attempt_id=attempt_id,
        )
    assert exc_info.value.exit_code == 1
    assert exc_info.value.attempt_dir is None
    assert not (output / "_SUCCESS").exists()
    assert not (output / "success.json").exists()
    assert not (output / "attempts" / attempt_id).exists()
    scratch = list(tmp_path.glob(f".worker-{attempt_id}-*"))
    assert len(scratch) == 1
    assert (scratch[0] / "still-owned-by-unconfirmed-worker.dat").is_file()
